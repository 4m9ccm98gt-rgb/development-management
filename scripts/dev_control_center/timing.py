"""Opt-in timing diagnostics (env DCC_TIMING=1). Silent and near-free when disabled."""

from __future__ import annotations

from contextlib import contextmanager
import os
import sys
import threading
import time
from typing import Callable, Iterator


def _env_enabled() -> bool:
    return os.environ.get("DCC_TIMING", "").strip() == "1"


class Timing:
    """Records durations and events. Thread-safe; emits only when enabled."""

    def __init__(
        self,
        enabled: bool | None = None,
        sink: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.enabled = _env_enabled() if enabled is None else enabled
        self._sink = sink or (lambda line: print(line, file=sys.stderr, flush=True))
        self._clock = clock
        self._lock = threading.Lock()
        self.durations: dict[str, list[float]] = {}
        self.events: list[tuple[str, dict[str, object]]] = []
        self._marks: dict[str, float] = {}

    def record(self, label: str, seconds: float) -> None:
        if not self.enabled:
            return
        with self._lock:
            self.durations.setdefault(label, []).append(seconds)
        self._sink(f"[DCC_TIMING] {label} {seconds * 1000:.1f}ms")

    @contextmanager
    def span(self, label: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        started = self._clock()
        try:
            yield
        finally:
            self.record(label, self._clock() - started)

    def event(self, name: str, **fields: object) -> None:
        if not self.enabled:
            return
        with self._lock:
            self.events.append((name, dict(fields)))
        detail = " ".join(f"{k}={v}" for k, v in fields.items())
        self._sink(f"[DCC_TIMING] event {name} {detail}".rstrip())

    def mark(self, label: str) -> None:
        if self.enabled:
            with self._lock:
                self._marks[label] = self._clock()

    def since_mark(self, label: str, *, record_as: str | None = None) -> float | None:
        """Seconds since mark(label); records it (and forgets the mark) if enabled."""
        if not self.enabled:
            return None
        with self._lock:
            started = self._marks.pop(label, None)
        if started is None:
            return None
        elapsed = self._clock() - started
        self.record(record_as or label, elapsed)
        return elapsed

    def summary(self) -> dict[str, dict[str, float]]:
        with self._lock:
            return {
                label: {
                    "count": float(len(values)),
                    "median_ms": _percentile(values, 50) * 1000,
                    "max_ms": max(values) * 1000,
                }
                for label, values in self.durations.items()
            }


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]


class HeartbeatMonitor:
    """UI event-loop lag: an after(interval) heartbeat records how late each beat ran."""

    def __init__(self, interval: float = 0.05) -> None:
        self.interval = interval
        self._last: float | None = None
        self.lags: list[float] = []

    def beat(self, now: float) -> float:
        lag = 0.0
        if self._last is not None:
            lag = max(0.0, (now - self._last) - self.interval)
            self.lags.append(lag)
        self._last = now
        return lag

    def stats(self) -> dict[str, float]:
        return {
            "beats": float(len(self.lags)),
            "p95": _percentile(self.lags, 95),
            "max": max(self.lags) if self.lags else 0.0,
        }

    def reset(self) -> None:
        self.lags.clear()


TIMING = Timing()

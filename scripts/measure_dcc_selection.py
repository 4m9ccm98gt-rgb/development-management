"""Measure the DCC repo-selection path on THIS machine (read-only).

Runs inspect_repo, discover_entrypoints and the REAL fetch_github_state (per gh
endpoint) for each managed repo, N times, and prints medians/maxima. It only
reads: git status/rev-parse/ls-files and gh API GET/list calls. Nothing is
modified, pushed or built.

    python scripts/measure_dcc_selection.py [--repo NAME ...] [--iterations 5] [--skip-github]
"""

from __future__ import annotations

import argparse
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dev_control_center.core import (  # noqa: E402
    active_repo_definitions,
    discover_entrypoints,
    fetch_github_state,
    inspect_repo,
)
from scripts.dev_control_center.timing import Timing  # noqa: E402
import scripts.dev_control_center.core as core  # noqa: E402


def _fmt(values: list[float]) -> str:
    return f"median {statistics.median(values) * 1000:8.1f}ms  max {max(values) * 1000:8.1f}ms"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", action="append", default=[])
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--skip-github", action="store_true")
    args = parser.parse_args()

    timing = Timing(enabled=True, sink=lambda line: None)
    core.TIMING = timing  # capture per-gh-endpoint spans without printing each call

    definitions = active_repo_definitions(
        ROOT / "scripts" / "repo_types.toml", ROOT / "scripts" / "dev_control_center_repos.toml"
    )
    if args.repo:
        definitions = [d for d in definitions if d.name in args.repo]
    for definition in definitions:
        root = ROOT.parent / definition.name
        samples: dict[str, list[float]] = {"inspect_repo": [], "discover_entrypoints": [], "fetch_github_state": []}
        for _ in range(args.iterations):
            started = time.perf_counter()
            inspect_repo(root, definition)
            samples["inspect_repo"].append(time.perf_counter() - started)
            started = time.perf_counter()
            discover_entrypoints(root, definition.repo_type,
                                 application_implemented=definition.application_implemented)
            samples["discover_entrypoints"].append(time.perf_counter() - started)
            if not args.skip_github:
                started = time.perf_counter()
                fetch_github_state(definition)
                samples["fetch_github_state"].append(time.perf_counter() - started)
        print(f"== {definition.name} ({root})")
        for label, values in samples.items():
            if values:
                print(f"   {label:22s} {_fmt(values)}")
        serial = sum(statistics.median(v) for v in samples.values() if v)
        print(f"   serial selection cost (old UI-thread freeze) ~ {serial * 1000:.0f}ms")
    print("\nper-gh-endpoint:")
    for label, stats in sorted(timing.summary().items()):
        print(f"   {label:70s} median {stats['median_ms']:8.1f}ms  max {stats['max_ms']:8.1f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

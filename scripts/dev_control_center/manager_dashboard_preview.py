"""Read-only independent preview: python -m scripts.dev_control_center.manager_dashboard_preview.

Collector runs in a single daemon worker; queue polling and ALL Tk calls run on
Tk's thread. Closing cancels scheduling and discards late results. A read already
blocked in OS I/O may finish in the daemon; shutdown never joins it or starts
another collection. There are no write/action endpoints.

Standalone mode cannot access App._workflow_runner_state. Disk Run associations
are explicitly provisional. Future in-process callers may inject runner_state
(the App's existing instance); app.py is deliberately not connected here.
"""
from __future__ import annotations

import copy
from datetime import datetime
import queue
import threading
import tkinter as tk

from .manager_collector import ManagerCollector
from .manager_dashboard_view import ManagerDashboardWindow
from .manager_inbox import build_inbox, empty_inbox
from .manager_visual_overview import build_overview, empty_overview
from .manager_organization_map import build_map, empty_map

INTERVAL_MS = 10_000
POLL_MS = 100
DISK_SCOPE = '観測範囲：ディスク上のRun対応記録のみ。本体メモリ内の最新対応は未確認（確認待ち）。'
MEMORY_SCOPE = '観測範囲：注入された本体メモリ内のRun対応を優先し、記録がない場合はディスクを参照。'
UNAVAILABLE = dict(schema_version=1, availability='unavailable', plans=[])


def preview_data(payload, *, memory_available=False):
    """Pure safe collection envelope. Widget display performs field allowlisting.

    Plan status remains authoritative, but standalone running assertions cannot
    prove the association is the latest one held by the live DCC process.
    """
    if not isinstance(payload, dict):
        return copy.deepcopy(UNAVAILABLE), '取得不能・確認待ち'
    status = payload.get('status')
    if not isinstance(status, str) or status not in ('available', 'partial'):
        return copy.deepcopy(UNAVAILABLE), '取得不能・確認待ち'
    snapshot = payload.get('snapshot')
    if (not isinstance(snapshot, dict) or type(snapshot.get('schema_version')) is not int
        or snapshot['schema_version'] != 1 or not isinstance(snapshot.get('plans'), list)
        or snapshot.get('availability') not in ('available', 'partial')):
        return copy.deepcopy(UNAVAILABLE), '取得不能・確認待ち'
    snapshot = copy.deepcopy(snapshot)
    if not memory_available:
        for plan in snapshot['plans']:
            if not isinstance(plan, dict) or not isinstance(plan.get('tasks'), list):
                continue
            for task in plan['tasks']:
                if not isinstance(task, dict):
                    continue
                if task.get('status') == 'running':
                    task.update(category='check_required', availability='unavailable')
                if isinstance(task.get('run'), dict):
                    task['run'].update(availability='unavailable', liveness='unknown')
    if status == 'partial' or snapshot['availability'] == 'partial':
        label = '一部取得不能・確認待ち'
    elif not snapshot['plans']:
        label = '保存済み計画なし'
    else:
        label = '取得済み' if memory_available else 'ディスク取得済み・メモリ未確認'
    return snapshot, label


def _launch(job):
    threading.Thread(target=job, name='manager-preview-reader', daemon=True).start()


class PreviewController:
    def __init__(self, view, *, collector=None, runner_state=None, scheduler=None,
                 launch=None, now=None, on_close=None, quota_display_fn=None):
        self.view = view
        self._inbox = getattr(view, 'inbox', None)
        self._overview = getattr(view, 'overview', None)
        self._map = getattr(view, 'organization_map', None)
        self.scheduler = scheduler if scheduler is not None else view.window
        if collector is not None:
            self.collector = collector
        else:
            # DCC Task UI-D2: quota_display_fn is omitted entirely (never passed as None) for
            # every existing caller (standalone preview, every pre-existing test) -- the
            # ManagerCollector(...) call is then byte-for-byte what it was before this task. An
            # in-process caller (app.py, via orchestrator_view.py's OrchestratorWindow) injects
            # orchestrator_requeue.quota_display bound to its own RequeueState, mirroring how
            # runner_state is already optionally injected above.
            collector_kwargs = dict(runner_state=runner_state)
            if quota_display_fn is not None:
                collector_kwargs['quota_display_fn'] = quota_display_fn
            self.collector = ManagerCollector(**collector_kwargs)
        self.memory_available = runner_state is not None
        self._launch = launch or _launch
        self._now = now or datetime.now
        self._on_close = on_close or view.window.destroy
        self._results = queue.Queue()
        self._stop = threading.Event()
        self._closed = False
        self._busy = False
        self._poll_id = None
        self._refresh_id = None
        self._last_update = '未更新'
        self.view.notice.configure(wraplength=700)
        self.view.window.protocol('WM_DELETE_WINDOW', self.close)
        self.view.window.bind('<Destroy>', self._destroyed, add='+')
        self.request_refresh()
        self._poll_id = self.scheduler.after(POLL_MS, self._poll)

    def _notice(self, status):
        scope = MEMORY_SCOPE if self.memory_available else DISK_SCOPE
        self.view.notice.configure(text=f'最終更新時刻：{self._last_update}　収集状態：{status}\n{scope}')

    def request_refresh(self):
        if self._closed or self._busy:
            return
        if self._refresh_id is not None:
            self.scheduler.after_cancel(self._refresh_id)
            self._refresh_id = None
        self._busy = True
        self._notice('更新中（前回表示の最新状態は未確認）')
        if self._inbox is not None:
            self._inbox.set_model(empty_inbox('updating'))
        if self._overview is not None:
            self._overview.set_model(empty_overview('updating', self.memory_available))
        if self._map is not None:
            self._map.set_model(empty_map('updating', self.memory_available))
        # Worker captures only collector, queue and stop event, never Tk objects.
        collector, results, stop = self.collector, self._results, self._stop
        def read():
            if stop.is_set():
                return
            try:
                payload = collector.collect()
            except Exception:
                payload = None  # never queue exception text, paths or tracebacks
            running = None
            if not stop.is_set():
                # DCC Task UI-D1: a second, independent read on the same worker/cycle -- never
                # the generation/fingerprint collect() issues for AI-decision validation.
                try:
                    running = collector.collect_running_tasks()
                except Exception:
                    running = None
                if not isinstance(running, list):
                    running = None
            if not stop.is_set():
                results.put((payload, running))
        try:
            self._launch(read)
        except Exception:
            self._results.put((None, None))

    def _poll(self):
        self._poll_id = None
        if self._closed:
            return
        try:
            item = self._results.get_nowait()
        except queue.Empty:
            pass
        else:
            payload, running = item if isinstance(item, tuple) and len(item) == 2 else (item, None)
            self._busy = False
            snapshot, status = preview_data(payload, memory_available=self.memory_available)
            self.view.set_snapshot(snapshot)  # replaces stale rows on EVERY result, including failure
            set_running = getattr(self.view, 'set_running_tasks', None)
            if set_running is not None:
                set_running(running if isinstance(running, list) else [])
            if self._inbox is not None or self._overview is not None or self._map is not None:
                data = payload if isinstance(payload, dict) else {}
                inbox_model = build_inbox(snapshot,
                    observation_id=data.get('observation_id'), collection_status=data.get('status'),
                    memory_available=self.memory_available, issues=data.get('issues', ()))
                if self._inbox is not None:
                    self._inbox.set_model(inbox_model)
                if self._overview is not None:
                    self._overview.set_model(build_overview(snapshot, inbox_model,
                        observation_id=data.get('observation_id'), memory_available=self.memory_available))
                if self._map is not None:
                    self._map.set_model(build_map(snapshot, inbox_model,
                        observation_id=data.get('observation_id'), memory_available=self.memory_available))
            try:
                stamp = self._now()
                self._last_update = stamp.strftime('%Y-%m-%d %H:%M:%S') if isinstance(stamp, datetime) else '時刻確認待ち'
            except Exception:
                self._last_update = '時刻確認待ち'
            self._notice(status)
            self._refresh_id = self.scheduler.after(INTERVAL_MS, self._scheduled_refresh)
        self._poll_id = self.scheduler.after(POLL_MS, self._poll)

    def _scheduled_refresh(self):
        self._refresh_id = None
        self.request_refresh()

    def _destroyed(self, event):
        if event.widget is self.view.window:
            self._shutdown()

    def _shutdown(self):
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        for token in (self._poll_id, self._refresh_id):
            if token is not None:
                self.scheduler.after_cancel(token)
        self._poll_id = self._refresh_id = None

    def close(self):
        if not self._closed:
            self._shutdown()
            self._on_close()


def main():
    from .app import configure_dark_theme
    root = tk.Tk()
    root.withdraw()
    configure_dark_theme(root)
    view = ManagerDashboardWindow(root, copy.deepcopy(UNAVAILABLE), inbox=True)
    controller = PreviewController(view, on_close=root.destroy)
    # Keep controller alive throughout Tk's event loop.
    try:
        root.mainloop()
    finally:
        controller._shutdown()


if __name__ == '__main__':
    main()

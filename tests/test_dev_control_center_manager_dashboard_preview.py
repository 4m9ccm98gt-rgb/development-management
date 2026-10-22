"""Fake Collector, scheduler, launcher and Tk only; no real data or window."""
import copy
from contextlib import ExitStack
from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.dev_control_center import manager_dashboard_preview as preview
from scripts.dev_control_center.manager_dashboard_view import display_model
from tests.test_dev_control_center_manager_dashboard_view import snapshot


class Scheduler:
    def __init__(self):
        self.jobs = {}
        self.counter = 0
    def after(self, delay, callback):
        self.counter += 1
        self.jobs[self.counter] = (delay, callback)
        return self.counter
    def after_cancel(self, token):
        self.jobs.pop(token, None)
    def run(self, delay):
        key = next(k for k, (d, _) in self.jobs.items() if d == delay)
        _, callback = self.jobs.pop(key)
        callback()


class Window:
    def __init__(self):
        self.protocols = {}
        self.bindings = {}
        self.destroy = Mock()
    def protocol(self, key, callback): self.protocols[key] = callback
    def bind(self, key, callback, **kwargs): self.bindings[key] = callback


class View:
    def __init__(self):
        self.window = Window()
        self.notice = Mock()
        self.snapshots = []
    def set_snapshot(self, data):
        self.snapshots.append(data)
        self.model = display_model(data)


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ('tkinter.Tk', 'tkinter.Toplevel', 'subprocess.Popen', 'socket.socket',
            'scripts.dev_control_center.workflow_plan.load_plan',
            'scripts.dev_control_center.workflow_plan.save_plan',
            'scripts.dev_control_center.workflow_plan.update_plan',
            'scripts.dev_control_center.candidate.approve',
            'scripts.dev_control_center.candidate.push',
            'scripts.dev_control_center.candidate.run_dev',
            'scripts.dev_control_center.provenance.build',
            'scripts.dev_control_center.release_update.plan',
            'tools.ai_orchestrator.orchestrator.start_run'):
            forbidden = self.stack.enter_context(patch(target, side_effect=AssertionError('FORBIDDEN')))
            self.addCleanup(forbidden.assert_not_called)

    def make(self, payloads=None, **kwargs):
        self.view = View()
        self.scheduler = Scheduler()
        self.work = []
        self.collector = Mock()
        self.collector.collect.side_effect = payloads or [dict(status='available', snapshot=snapshot())]
        defaults = dict(collector=self.collector, scheduler=self.scheduler,
                        launch=self.work.append, now=lambda: datetime(2026, 10, 21, 14, 30))
        defaults.update(kwargs)
        return preview.PreviewController(self.view, **defaults)

    def complete(self):
        self.work.pop(0)()
        self.scheduler.run(preview.POLL_MS)

    def notice(self):
        return self.view.notice.configure.call_args.kwargs['text']

    def test_success_background_only_queues_and_ui_poll_updates(self):
        controller = self.make()
        self.assertEqual(self.collector.collect.call_count, 0)
        self.assertIn('更新中', self.notice())
        calls = self.view.notice.configure.call_count
        self.work.pop(0)()
        self.assertEqual(self.view.snapshots, [])
        self.assertEqual(self.view.notice.configure.call_count, calls)
        self.scheduler.run(preview.POLL_MS)
        self.assertEqual(len(self.view.snapshots), 1)
        self.assertIn('2026-10-21 14:30:00', self.notice())
        self.assertIn(preview.DISK_SCOPE, self.notice())
        self.assertIn('メモリ未確認', self.notice())
        self.assertFalse(controller._busy)

    def test_ten_second_refresh_and_no_overlapping_reads(self):
        controller = self.make([dict(status='available', snapshot=snapshot())] * 2)
        for _ in range(3):
            controller.request_refresh()
            self.scheduler.run(preview.POLL_MS)
        self.assertEqual(len(self.work), 1)
        self.complete()
        self.scheduler.run(preview.INTERVAL_MS)
        controller.request_refresh()
        self.assertEqual(len(self.work), 1)
        self.assertIn('前回表示の最新状態は未確認', self.notice())
        self.complete()
        self.assertEqual(self.collector.collect.call_count, 2)

    def test_failure_replaces_old_rows_and_never_displays_exception(self):
        controller = self.make([dict(status='available', snapshot=snapshot()), OSError('SECRET C:/private')])
        self.complete()
        self.assertGreater(len(self.view.model['rows']), 0)
        self.scheduler.run(preview.INTERVAL_MS)
        self.complete()
        self.assertEqual(self.view.model['rows'], [])
        self.assertIn('取得不能・確認待ち', self.notice())
        self.assertNotIn('SECRET', str(self.view.snapshots) + self.notice())
        self.assertFalse(controller._busy)

    def test_partial_and_empty_collections(self):
        self.make([dict(status='partial', snapshot=snapshot()),
                   dict(status='available', snapshot=dict(schema_version=1, availability='available', plans=[]))])
        self.complete()
        self.assertIn('一部取得不能', self.notice())
        self.assertGreater(len(self.view.model['rows']), 0)
        self.scheduler.run(preview.INTERVAL_MS)
        self.complete()
        self.assertIn('保存済み計画なし', self.notice())
        self.assertEqual(self.view.model['rows'], [])

    def test_disk_only_running_is_provisional_without_mutating_payload(self):
        source = snapshot()
        row = source['plans'][0]['tasks'][3]
        row.update(category='running', availability='available')
        row['run'] = dict(run_id='20261021-123331-908753', stage='testing', liveness='running', availability='available')
        before = copy.deepcopy(source)
        data, label = preview.preview_data(dict(status='available', snapshot=source))
        self.assertEqual(display_model(data)['counts']['running'], 0)
        self.assertIn('確認待ち', display_model(data)['rows'][3]['detail'])
        self.assertIn('メモリ未確認', label)
        self.assertEqual(source, before)
        data, _ = preview.preview_data(dict(status='available', snapshot=source), memory_available=True)
        self.assertEqual(display_model(data)['counts']['running'], 1)

    def test_runner_state_injection_and_scope(self):
        state = object()
        view, scheduler, work = View(), Scheduler(), []
        collector = Mock()
        collector.collect.return_value = dict(status='available', snapshot=snapshot())
        with patch.object(preview, 'ManagerCollector', return_value=collector) as factory:
            preview.PreviewController(view, runner_state=state, scheduler=scheduler, launch=work.append)
        factory.assert_called_once_with(runner_state=state)
        work.pop()()
        scheduler.run(preview.POLL_MS)
        self.assertIn(preview.MEMORY_SCOPE, view.notice.configure.call_args.kwargs['text'])

    def test_close_cancels_timers_discards_late_result_and_no_more_reads(self):
        controller = self.make()
        controller.close()
        self.assertEqual(self.scheduler.jobs, {})
        self.work.pop(0)()
        self.collector.collect.assert_not_called()
        controller.request_refresh()
        self.assertEqual(self.work, [])
        self.view.window.destroy.assert_called_once()
        controller.close()
        self.view.window.destroy.assert_called_once()

    def test_close_during_read_discards_result_without_widget_calls(self):
        controller = self.make()
        def blocking_fake():
            controller.close()
            return dict(status='available', snapshot=snapshot())
        self.collector.collect.side_effect = blocking_fake
        self.work.pop()()
        self.assertTrue(controller._results.empty())
        self.assertEqual(self.view.snapshots, [])
        self.assertEqual(self.scheduler.jobs, {})

    def test_destroy_event_stops_only_for_own_window(self):
        controller = self.make()
        callback = self.view.window.bindings['<Destroy>']
        callback(SimpleNamespace(widget=object()))
        self.assertFalse(controller._closed)
        callback(SimpleNamespace(widget=self.view.window))
        self.assertTrue(controller._closed)
        self.assertEqual(self.scheduler.jobs, {})

    def test_invalid_payloads_launch_failure_and_timestamp_failure(self):
        for bad in (None, {}, dict(status='SECRET'), dict(status='available', snapshot={}),
                    dict(status='available', snapshot=preview.UNAVAILABLE)):
            data, label = preview.preview_data(bad)
            self.assertEqual(data, preview.UNAVAILABLE)
            self.assertEqual(label, '取得不能・確認待ち')
        controller = self.make(launch=Mock(side_effect=RuntimeError('SECRET')),
                               now=Mock(side_effect=RuntimeError('SECRET')))
        self.scheduler.run(preview.POLL_MS)
        self.assertFalse(controller._busy)
        self.assertNotIn('SECRET', self.notice())
        self.assertIn('時刻確認待ち', self.notice())

    def test_failure_recovery_and_close_after_result_cancel_refresh(self):
        controller = self.make([RuntimeError('SECRET'), dict(status='available', snapshot=snapshot())])
        self.complete()
        self.assertEqual(self.view.model['rows'], [])
        self.scheduler.run(preview.INTERVAL_MS)
        self.complete()
        self.assertGreater(len(self.view.model['rows']), 0)
        controller.close()
        self.assertEqual(self.scheduler.jobs, {})
        controller._poll()
        self.assertEqual(self.scheduler.jobs, {})

    def test_default_launcher_uses_daemon_without_real_thread(self):
        job = Mock()
        with patch.object(preview.threading, 'Thread') as thread:
            preview._launch(job)
        thread.assert_called_once_with(target=job, name='manager-preview-reader', daemon=True)
        thread.return_value.start.assert_called_once()
        job.assert_not_called()

    def test_main_reuses_theme_without_real_tk_or_collection(self):
        from scripts.dev_control_center import app
        root = Mock()
        view = View()
        with patch.object(preview, 'tk', SimpleNamespace(Tk=Mock(return_value=root))), \
             patch.object(app, 'configure_dark_theme') as theme, \
             patch.object(preview, 'ManagerDashboardWindow', return_value=view) as window, \
             patch.object(preview, 'PreviewController') as controller:
            preview.main()
        theme.assert_called_once_with(root)
        root.withdraw.assert_called_once()
        root.mainloop.assert_called_once()
        window.assert_called_once_with(root, preview.UNAVAILABLE, inbox=True)
        controller.assert_called_once_with(view, on_close=root.destroy)
        controller.return_value._shutdown.assert_called_once()


if __name__ == '__main__':
    unittest.main()

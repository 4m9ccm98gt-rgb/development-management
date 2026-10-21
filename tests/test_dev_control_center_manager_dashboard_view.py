"""All widgets are fakes; no Tk root, collection or external process is started."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.dev_control_center import manager_dashboard_view as view
from scripts.dev_control_center import manager_overview as overview
from tests.test_dev_control_center_manager_overview import plan, task, KEYS, RID


class Widget:
    def __init__(self, *args, **kwargs):
        self.options = kwargs
        self.rows = {}
        self.selected = ()
        self.bindings = {}
        self.configurations = {}
        self.maps = {}
        self.bg = '#0f1419'
    def configure(self, **kwargs):
        self.options.update(kwargs)
    def pack(self, **kwargs): pass
    def grid(self, **kwargs): pass
    def columnconfigure(self, *args, **kwargs): pass
    def rowconfigure(self, *args, **kwargs): pass
    def title(self, value): self.caption = value
    def geometry(self, value): pass
    def minsize(self, *args): pass
    def heading(self, *args, **kwargs): pass
    def column(self, *args, **kwargs): pass
    def xview(self, *args): pass
    def yview(self, *args): pass
    def set(self, *args): pass
    def bind(self, event, callback, **kwargs): self.bindings[event] = callback
    def selection(self): return self.selected
    def selection_set(self, iid): self.selected = (iid,)
    def get_children(self): return tuple(self.rows)
    def delete(self, iid):
        del self.rows[iid]
        if iid in self.selected: self.selected = ()
    def insert(self, parent, where, iid, values): self.rows[iid] = values
    def theme_use(self): return 'clam'
    def lookup(self, *args): return self.bg
    def map(self, name, **kwargs): self.maps[name] = kwargs


class FakeStyle(Widget):
    def configure(self, name, **kwargs): self.configurations[name] = kwargs


def snapshot():
    return overview.build_snapshot([plan(task('T1', 'landed'), task('T2', 'needs_human'),
        task('T3', 'failed'), task('T4', 'running'), task('T5', 'proposed'),
        task('T6', 'approved', ['T1']), task('T7', 'cancelled'))], registered_keys=KEYS)


class ModelTests(unittest.TestCase):
    def test_summary_and_no_mutation(self):
        source = snapshot()
        before = copy.deepcopy(source)
        result = view.display_model(source)
        self.assertEqual(result['counts'], dict(total=7, running=0, waiting=2, completed=1,
            needs_human=1, failed=1, unavailable=1, cancelled=1))
        self.assertEqual(source, before)
        self.assertIn('T1: 完了', result['rows'][5]['detail'])
        self.assertIn('確認待ち', result['rows'][3]['detail'])
        self.assertIn('TASK総数: 7', view.summary_text(result))

    def test_running_requires_observation_and_never_inferred_from_assignment(self):
        p = plan(task('T1', 'running'))
        p['tasks'][0].update(main_ai='claude', reviewer_ai='codex')
        source = overview.build_snapshot([p], registered_keys=KEYS,
            associations={('Plan-1', 'T1'): {'run_id': RID}},
            observations={RID: {'record': {'run_id': RID, 'stage': 'testing'}, 'liveness': 'running'}})
        row = view.display_model(source)['rows'][0]
        self.assertIn('Executor: Claude / Reviewer: Codex', row['values'])
        self.assertIn(RID, row['detail'])
        self.assertEqual(view.display_model(source)['counts']['running'], 1)
        source['plans'][0]['tasks'][0]['run']['liveness'] = 'lost'
        self.assertEqual(view.display_model(source)['counts']['unavailable'], 1)
        self.assertIn('未実装', view.MANAGER_TEXT)

    def test_multiple_plans_candidate_and_held(self):
        other = plan(task('T1', 'candidate_ready'), task('T2', 'held'))
        other['plan_id'] = 'Plan-2'
        source = overview.build_snapshot([plan(task('T1', 'landed')), other], registered_keys=KEYS)
        model = view.display_model(source)
        self.assertEqual(model['counts']['total'], 3)
        self.assertEqual(model['counts']['completed'], 1)
        self.assertEqual(model['counts']['needs_human'], 1)
        self.assertEqual(model['counts']['waiting'], 1)
        self.assertNotEqual(model['rows'][0]['identity'], model['rows'][1]['identity'])

    def test_invalid_collection_and_plan_are_visible(self):
        for bad in (None, {}, [], {'schema_version': 9, 'plans': []}):
            self.assertEqual(view.display_model(bad)['availability'], '確認待ち')
        source = overview.build_snapshot([None], registered_keys=KEYS)
        model = view.display_model(source)
        self.assertEqual(model['unavailable_plans'], 1)
        self.assertEqual(model['counts']['total'], 0)
        self.assertEqual(model['availability'], '一部取得不能')

    def test_no_free_text_leaks_even_from_malformed_snapshot(self):
        secret = 'SECRET C:\\private\\file\nAI output'
        source = snapshot()
        row = source['plans'][0]['tasks'][0]
        for field in ('task_id', 'plan_id', 'repo_key', 'status', 'category', 'main_ai', 'reviewer_ai'):
            bad = copy.deepcopy(source)
            bad['plans'][0]['tasks'][0][field] = secret
            self.assertNotIn('SECRET', str(view.display_model(bad)))
        row.update(body=secret, exception=secret, dependencies=[dict(task_id=secret, status=secret)],
                   run=dict(run_id=secret, stage=secret, liveness=secret))
        self.assertNotIn('SECRET', str(view.display_model(source)))
        for field in ('status', 'category', 'main_ai', 'run', 'dependencies'):
            row[field] = []
            self.assertNotIn('SECRET', str(view.display_model(source)))


class WindowTests(unittest.TestCase):
    def test_construct_select_update_and_clear_with_fakes(self):
        fake_ttk = SimpleNamespace(**{name: Widget for name in
            ('Frame', 'Label', 'LabelFrame', 'Treeview', 'Scrollbar')}, Style=FakeStyle)
        with patch.object(view, 'tk', SimpleNamespace(Toplevel=Widget)), \
             patch.object(view, 'ttk', fake_ttk), \
             patch('subprocess.Popen', side_effect=AssertionError('no process')):
            window = view.ManagerDashboardWindow(None, snapshot())
            self.assertEqual(len(window.tree.rows), 7)
            self.assertIn('TASKを選択', window.detail.options['text'])
            window.tree.selection_set('row-1')
            window.tree.bindings['<<TreeviewSelect>>'](None)
            self.assertIn('T2', window.detail.options['text'])
            self.assertIn('人間対応待ち', window.detail.options['text'])
            source = snapshot()
            source['plans'][0]['tasks'].reverse()
            window.set_snapshot(source)
            self.assertIn('T2', window.detail.options['text'])
            window.tree.selection_set('row-4')
            window._on_select()
            self.assertIn('失敗', window.detail.options['text'])
            window.set_snapshot(overview.build_snapshot([], registered_keys=KEYS))
            self.assertEqual(window.tree.rows, {})
            self.assertIn('TASKを選択', window.detail.options['text'])
            window.window.bindings['<<ThemeChanged>>'](None)

    def test_theme_matches_dcc_and_light_restores_native_styles(self):
        style = FakeStyle()
        window, tree, horizontal, vertical = Widget(), Widget(), Widget(), Widget()
        view.apply_table_theme(window, tree, horizontal, vertical, style)
        self.assertEqual(tree.options['style'], 'Manager.Treeview')
        self.assertEqual(style.configurations['Manager.Treeview']['foreground'], '#e6edf3')
        self.assertEqual(style.maps['Manager.Treeview']['background'], [('selected', '#1f6feb')])
        self.assertEqual(window.options['background'], '#0f1419')
        self.assertIn('Manager.Vertical.TScrollbar', style.configurations)
        style.bg = '#ffffff'
        view.apply_table_theme(window, tree, horizontal, vertical, style)
        self.assertEqual(tree.options['style'], 'Treeview')
        self.assertEqual(horizontal.options['style'], 'Horizontal.TScrollbar')
        self.assertEqual(vertical.options['style'], 'Vertical.TScrollbar')


if __name__ == '__main__':
    unittest.main()

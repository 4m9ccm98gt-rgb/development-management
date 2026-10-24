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
    def element_names(self): return tuple(getattr(self, 'elements', {}))
    def element_create(self, name, *args):
        if not hasattr(self, 'elements'): self.elements = {}
        assert name not in self.elements
        self.elements[name] = args
    def layout(self, name, value):
        if not hasattr(self, 'layouts'): self.layouts = {}
        self.layouts[name] = value


class FakeCanvas(Widget):
    def create_oval(self, *args, **kwargs): return self._create(args, kwargs)
    def create_polygon(self, *args, **kwargs): return self._create(args, kwargs)
    def create_line(self, *args, **kwargs): return self._create(args, kwargs)
    def tag_bind(self, tag, event, callback): self.bindings[(tag, event)] = callback
    def create_text(self, *args, **kwargs): return self._create(args, kwargs)
    def create_rectangle(self, *args, **kwargs): return self._create(args, kwargs)
    def _create(self, args, kwargs):
        key = max(self.rows, default=0) + 1
        self.rows[key] = (args, kwargs)
        return key
    def delete(self, iid): self.rows.clear() if iid == 'all' else self.rows.pop(iid, None)
    def bbox(self, iid):
        args, _ = self.rows[iid]
        return (args[0], args[1], args[0]+100, args[1]+18)
    def coords(self, *args): pass


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


class RunningTasksModelTests(unittest.TestCase):
    """DCC Task UI-D1: pure allowlisted presentation for 動いているタスク rows."""

    def test_valid_rows_pass_through_with_fixed_labels(self):
        rows = [dict(run_id=RID, repo='sample-repo', stage='testing', origin='報告',
                     main_agent='claude', review_agent='codex')]
        self.assertEqual(view.running_tasks_model(rows),
                         [dict(run_id=RID, repo='sample-repo', stage_label='テスト中', origin_label='報告')])

    def test_invalid_run_id_stage_or_origin_is_dropped(self):
        base = dict(run_id=RID, repo='sample-repo', stage='testing', origin='報告')
        for bad in (dict(base, run_id='../secret'), dict(base, stage='completed'),
                    dict(base, stage='created'), dict(base, origin='SECRET'),
                    dict(base, run_id=None), {}, None, []):
            self.assertEqual(view.running_tasks_model([bad]), [])
        self.assertEqual(view.running_tasks_model(None), [])
        self.assertEqual(view.running_tasks_model('not-a-list'), [])

    def test_unsafe_repo_value_becomes_unknown_not_leaked(self):
        secret = 'C:\\private\\data\nAI output'
        rows = view.running_tasks_model([dict(run_id=RID, repo=secret, stage='testing', origin='報告')])
        self.assertEqual(rows[0]['repo'], view.UNKNOWN)
        self.assertNotIn('private', str(rows))


class WindowTests(unittest.TestCase):
    def test_notebook_dark_elements_states_and_light_restore(self):
        style, notebook = FakeStyle(), Widget()
        with patch.object(style, 'theme_use', wraps=style.theme_use) as theme_use:
            view.apply_notebook_theme(notebook, style)
            theme_use.assert_not_called()  # never change global theme
        self.assertEqual(notebook.options['style'], 'Manager.TNotebook')
        self.assertEqual(style.configurations['Manager.TNotebook']['background'], '#0f1419')
        for part in ('client', 'tab', 'padding', 'focus', 'label'):
            self.assertEqual(style.elements[f'Manager.Notebook.{part}'], ('from', 'clam', f'Notebook.{part}'))
        self.assertEqual(style.maps['Manager.TNotebook.Tab']['background'][1:],
                         [('selected', '#1f6feb'), ('active', '#30363d'), ('!selected', '#20262d')])
        self.assertTrue(all(color == '#e6edf3' for _, color in style.maps['Manager.TNotebook.Tab']['foreground'][1:]))
        self.assertEqual(style.layouts['Manager.TNotebook'][0][0], 'Manager.Notebook.client')
        view.apply_notebook_theme(notebook, style)
        self.assertEqual(len(style.elements), 5)
        style.bg = '#ffffff'
        view.apply_notebook_theme(notebook, style)
        self.assertEqual(notebook.options['style'], 'TNotebook')
        style.bg = '#0f1419'
        view.apply_notebook_theme(notebook, style)
        self.assertEqual(notebook.options['style'], 'Manager.TNotebook')
        self.assertEqual(len(style.elements), 5)

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

    def test_set_running_tasks_renders_badges_and_clears(self):
        """DCC Task UI-D1: widget-level check only -- the update-path (appear/disappear through
        PreviewController) is covered separately in test_dev_control_center_manager_dashboard_preview."""
        fake_ttk = SimpleNamespace(**{name: Widget for name in
            ('Frame', 'Label', 'LabelFrame', 'Treeview', 'Scrollbar')}, Style=FakeStyle)
        with patch.object(view, 'tk', SimpleNamespace(Toplevel=Widget)), \
             patch.object(view, 'ttk', fake_ttk), \
             patch('subprocess.Popen', side_effect=AssertionError('no process')):
            window = view.ManagerDashboardWindow(None, snapshot())
            self.assertEqual(window.running_tree.rows, {})
            window.set_running_tasks([dict(run_id=RID, repo='sample-repo', stage='testing', origin='報告')])
            self.assertEqual(len(window.running_tree.rows), 1)
            values = next(iter(window.running_tree.rows.values()))
            self.assertEqual(values, ('報告', RID, 'sample-repo', 'テスト中'))
            window.set_running_tasks([])
            self.assertEqual(window.running_tree.rows, {})
            window.set_running_tasks('not-a-list')
            self.assertEqual(window.running_tree.rows, {})

    def test_theme_matches_dcc_and_light_restores_native_styles(self):
        style = FakeStyle()
        window, tree, horizontal, vertical = Widget(), Widget(), Widget(), Widget()
        view.apply_table_theme(window, tree, horizontal, vertical, style)
        self.assertEqual(tree.options['style'], 'Manager.Treeview')
        self.assertEqual(style.configurations['Manager.Treeview']['foreground'], '#e6edf3')
        self.assertEqual(style.maps['Manager.Treeview']['background'], [('selected', '#1f6feb')])
        self.assertEqual(window.options['background'], '#0f1419')
        self.assertIn('Manager.Vertical.TScrollbar', style.configurations)
        for orientation, arrows in (('Horizontal', ('leftarrow', 'rightarrow')), ('Vertical', ('uparrow', 'downarrow'))):
            name = f'Manager.{orientation}.TScrollbar'
            prefix = f'Manager.{orientation}.Scrollbar'
            for part in ('trough', 'thumb', *arrows):
                self.assertEqual(style.elements[f'{prefix}.{part}'],
                                 ('from', 'clam', f'{orientation}.Scrollbar.{part}'))
            children = style.layouts[name][0][1]['children']
            self.assertEqual(children[-1], (f'{prefix}.thumb', dict(expand=1, sticky='nswe')))
            self.assertIn(('!active', '#20262d'), style.maps[name]['background'])
        view.apply_table_theme(window, tree, horizontal, vertical, style)
        self.assertEqual(len(style.elements), 8)  # repeated refresh does not recreate elements
        style.bg = '#ffffff'
        view.apply_table_theme(window, tree, horizontal, vertical, style)
        self.assertEqual(tree.options['style'], 'Treeview')
        self.assertEqual(horizontal.options['style'], 'Horizontal.TScrollbar')
        self.assertEqual(vertical.options['style'], 'Vertical.TScrollbar')

    def test_apply_table_theme_styles_extra_trees_without_their_own_scrollbars(self):
        style = FakeStyle()
        window, tree, horizontal, vertical, extra = Widget(), Widget(), Widget(), Widget(), Widget()
        view.apply_table_theme(window, tree, horizontal, vertical, style, extra)
        self.assertEqual(extra.options['style'], 'Manager.Treeview')
        style.bg = '#ffffff'
        view.apply_table_theme(window, tree, horizontal, vertical, style, extra)
        self.assertEqual(extra.options['style'], 'Treeview')


if __name__ == '__main__':
    unittest.main()

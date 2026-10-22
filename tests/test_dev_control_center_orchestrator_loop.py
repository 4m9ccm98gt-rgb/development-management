"""Circular display uses only fake widgets and existing safe card projections."""
import copy
import struct
import unittest
import zlib
from types import SimpleNamespace
from unittest.mock import Mock, patch
from scripts.dev_control_center import orchestrator_loop as loop, orchestrator_lanes as lanes, character
from tests.test_dev_control_center_manager_dashboard_view import Widget, FakeCanvas, FakeStyle
from tests.test_dev_control_center_orchestrator_lanes import run

class FakeWidget(Widget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.destroyed = False
    def pack_forget(self): pass
    def destroy(self): self.destroyed = True
    def state(self, states): self.options['state'] = states
    def winfo_rooty(self): return 0
    def winfo_height(self): return 300
    def focus_get(self): return None

class Canvas(FakeCanvas):
    def create_image(self, *args, **kwargs): return self._create(args, kwargs)
    def after(self, *args): return 1
    def after_cancel(self, *args): pass
    def create_window(self, *args, **kwargs): return self._create(args, kwargs)
    def itemconfigure(self, *args, **kwargs): pass
    def tag_lower(self, *args): pass
    def yview_scroll(self, *args): pass
    def yview_moveto(self, *args): pass
    def canvasy(self, y): return y
    def winfo_rooty(self): return 0
    def winfo_height(self): return 300
    def bbox(self, *args): return (0, 0, 600, 1000)
    def delete(self, tag):
        for key, (_, opts) in list(self.rows.items()):
            if tag == 'all' or opts.get('tags') == tag: del self.rows[key]

class ProjectionTests(unittest.TestCase):
    def test_measured_stages_multiple_unique_and_immutable(self):
        runs = [run(s, rid=f'20261022-000000-{i:06}') for i, s in enumerate(
            ['implementing', 'implementing', 'testing', 'reviewing', 'repairing'], 1)]
        model = lanes.build_lanes([], runs)
        before = copy.deepcopy(model)
        result = loop.project_loop(model)
        self.assertEqual([len(result[s]) for s in loop.STATIONS], [2, 1, 1, 1])
        self.assertEqual(sum(map(len, result.values())), 5)
        self.assertEqual(model, before)
        model['Manager'].append(model['Implementer'][0])
        self.assertEqual(sum(map(len, loop.project_loop(model).values())), 5)

    def test_unknown_and_stale_never_confirmed_as_running(self):
        model = lanes.build_lanes([], [run('testing')])
        card = model['Implementer'][0]
        card.update(priority='PX', task_unknown=True)
        self.assertEqual(len(loop.project_loop(model)['ManagerWait']), 1)
        card.update(stale=True)
        result = loop.project_loop(model, {card['key']: ('Testing', 0)})
        self.assertTrue(result['Testing'][0]['stale'])
        self.assertEqual(result['Testing'][0]['priority'], 'PX')

    def test_actual_workflow_projection_keeps_approval_dependency_and_completion(self):
        from scripts.dev_control_center.manager_overview import build_snapshot
        from tests.test_dev_control_center_manager_overview import plan, task, KEYS
        payload = dict(status='available', observation_id=1,
            snapshot=build_snapshot([plan(task('T1', 'proposed'), task('T2', 'failed'),
                task('T3', 'landed'), task('T4', 'approved', ['T1']))], registered_keys=KEYS))
        cards, _ = lanes.workflow_cards(payload)
        result = loop.project_loop(lanes.build_lanes(cards, []))
        self.assertEqual(len(result['Approval']), 1)
        self.assertEqual(len(result['Feedback']), 1)
        self.assertEqual(len(result['Archive']), 1)
        self.assertEqual(len(result['ManagerWait']), 1)
        self.assertEqual(sum(len(result[s]) for s in loop.STATIONS), 0)

    def test_human_sections_and_archive_are_view_only(self):
        model = {name: [] for name in lanes.LANES}
        for i, (status, stage, lane) in enumerate([
            ('proposed', 'unknown', 'Human'), ('needs_human', 'needs_human', 'Human'),
            ('failed', 'failed', 'Human'), ('landed', 'completed', 'Manager'),
            ('candidate_ready', 'completed', 'Human'), ('cancelled', 'unknown', 'Manager')]):
            model[lane].append(dict(key=str(i), priority='P2', workflow_status=status, observed_stage=stage))
        result = loop.project_loop(model)
        self.assertEqual([len(result[g]) for g in ('Approval', 'Decision', 'Feedback', 'Archive')], [2, 1, 1, 2])

class BoardTests(unittest.TestCase):
    def make_board(self):
        widgets = SimpleNamespace(Frame=FakeWidget, Label=FakeWidget, Button=FakeWidget, Scrollbar=FakeWidget, Style=FakeStyle)
        for module in (loop, lanes):
            ctx = patch.object(module, 'ttk', widgets); ctx.start(); self.addCleanup(ctx.stop)
        ctx = patch.object(loop, 'tk', SimpleNamespace(Canvas=Canvas)); ctx.start(); self.addCleanup(ctx.stop)
        for name, value in [('ArtWorker', lambda: Mock(available=False)), ('CanvasCard', FakeWidget), ('PanelSurface', lambda *args, **kwargs: Mock(content=FakeWidget()))]:
            ctx = patch.object(loop, name, value); ctx.start(); self.addCleanup(ctx.stop)
        return loop.LoopBoard(FakeWidget(), Mock())

    def test_diff_selection_move_archive_and_resize(self):
        board = self.make_board()
        model = lanes.build_lanes([], [run('testing')])
        board.set_model(model)
        button = board.cards['Testing'][0]
        board.set_model(copy.deepcopy(model))
        self.assertIs(board.cards['Testing'][0], button)
        button.bindings['<Return>'](None)
        board.on_select.assert_called_once()
        board.set_model(lanes.build_lanes([], [run('reviewing')]))
        self.assertTrue(button.destroyed)
        self.assertEqual(len(board.cards['Reviewing']), 1)
        self.assertFalse(board._archive_open)
        board.toggle_archive(); self.assertTrue(board._archive_open)
        board.toggle_archive(); self.assertFalse(board._archive_open)
        agent = Mock(); board.attach_character(agent)
        station_ids = dict(board._station_items)
        for w, h in ((600, 650), (800, 840), (500, 250)):
            board._resize(SimpleNamespace(width=w, height=h))
            board._finish_resize()
        self.assertEqual(board._station_items, station_ids)
        self.assertEqual(board._size, (500, 630))
        agent.set_scale.assert_called_with(2)
        self.assertIn('<MouseWheel>', board.loop.bindings)
        self.assertEqual(set(board.headers), set(loop.GROUPS))

    def test_stale_headers_and_scoped_theme(self):
        board = self.make_board()
        model = lanes.build_lanes([], [run('testing')]); board.set_model(model)
        model['Implementer'][0].update(stale=True, priority='PX', state='確認待ち')
        board.set_model(model)
        self.assertIn('未確認 1', board.headers['Testing'].options['text'])
        self.assertIn('確認待ち', board.cards['Testing'][0].options['text'])
        style = FakeStyle()
        with patch.object(style, 'theme_use') as switch:
            loop.configure_loop_styles(style); switch.assert_not_called()
        for name in loop.GROUPS:
            self.assertEqual(style.configurations[f'Loop{name}.TButton']['background'], loop.SURFACE)

class SpriteTests(unittest.TestCase):
    def test_palette_key_preserves_pixels_and_existing_alpha(self):
        def chunk(kind, value):
            payload = kind+value
            return struct.pack('>I', len(value))+payload+struct.pack('>I', zlib.crc32(payload))
        header = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 1, 8, 3, 0, 0, 0))
        data = header+chunk(b'PLTE', bytes([8, 15, 32, 240, 230, 255]))+chunk(b'IDAT', zlib.compress(b'\0\0\1'))+chunk(b'IEND', b'')
        result = character.transparent_sprite(data)
        self.assertIn(chunk(b'tRNS', b'\0\xff'), result)
        self.assertIn(chunk(b'IDAT', zlib.compress(b'\0\0\1')), result)
        self.assertEqual(character.transparent_sprite(result), result)
        self.assertEqual(character.transparent_sprite(b'bad'), b'bad')

    def test_shared_canvas_scale_preserves_timer_and_owns_only_image(self):
        canvas = Mock(); canvas.create_image.return_value = 42
        with patch.object(character.tk, 'PhotoImage', return_value=Mock()):
            agent = character.CharacterView(canvas, background=loop.BG, canvas=canvas, asset_dir=__import__('pathlib').Path('/missing-ui4-assets'))
            agent._sheet = Mock(); agent._after_id = 'timer'; agent.index = 7
            agent.set_scale(2); agent.move(300, 320)
            self.assertEqual(agent.index, 7)
            self.assertEqual(agent._after_id, 'timer')
            canvas.coords.assert_called_with(42, 300, 320)
            agent.destroy(); canvas.after_cancel.assert_called_once_with('timer')
            canvas.delete.assert_called_once_with(42); canvas.destroy.assert_not_called()

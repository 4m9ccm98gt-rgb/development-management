"""Opt-in UI benchmark. Synthetic data only; no monitor, Collector, AI or network.

python -m tests.benchmark_orchestrator_ui --tk
Real Tk is withdrawn, so these timings exclude Windows compositor/presentation.
The unittest suite never calls this entry point.
"""
import argparse
import importlib.util
import json
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.dev_control_center import orchestrator_loop, orchestrator_lanes, character
from tests.test_dev_control_center_orchestrator_lanes import run
from tests.test_dev_control_center_orchestrator_view import FakeOrchestratorWindowCase

BASE='358e472cfb648a05f64e86cb41e0de97ae213136'

def measure(fn,n=50):
    start=time.perf_counter()
    for _ in range(n):fn()
    return round((time.perf_counter()-start)*1000/n,4)


def baseline(name):
    path='scripts/dev_control_center/'+name+'.py'
    source=subprocess.run(['git','show',BASE+':'+path],check=True,capture_output=True,encoding='utf-8').stdout
    if name=='orchestrator_loop':source=source.replace('.orchestrator_lanes import','._ui5_baseline_orchestrator_lanes import')
    fullname='scripts.dev_control_center._ui5_baseline_'+name
    module=importlib.util.module_from_spec(importlib.util.spec_from_loader(fullname,loader=None))
    module.__file__=str(__import__('pathlib').Path(character.__file__).with_name(name+'.py'))
    sys.modules[fullname]=module
    exec(compile(source,path,'exec'),module.__dict__)
    return module


def fake_window():
    case=FakeOrchestratorWindowCase();case.setUp();window=case.window
    snapshot=dict(runs=[run('testing')],usage={},selected=None)
    window._workflow_feed.poll.return_value=([], 'synthetic')
    with patch.object(window,'_refresh_board',wraps=window._refresh_board) as calls:
        window.monitor.queue.put(snapshot);window._tick();count=calls.call_count
    result={'refresh_calls_combined_tick':count}
    for name,fn in [('_tick',window._tick),('apply_snapshot',lambda:window.apply_snapshot(snapshot)),('_refresh_board',window._refresh_board)]:
        result[name+'_ms']=measure(fn,100)
    case.doCleanups();return result


def tk_benchmark():
    import tkinter as tk
    import faulthandler
    faulthandler.dump_traceback_later(45, exit=True)
    print('starting withdrawn Tk benchmark', file=sys.stderr, flush=True)
    from scripts.dev_control_center.ui_theme import configure_dark_containers
    old_lanes=baseline('orchestrator_lanes');old_loop=baseline('orchestrator_loop');old_character=baseline('character')
    root=tk.Tk();root.withdraw()
    print('Tk initialized', file=sys.stderr, flush=True)
    from tkinter import ttk
    configure_dark_containers(ttk.Style(root))
    result={}
    try:
        for label,module in [('before',old_loop),('after',orchestrator_loop)]:
            print(label, file=sys.stderr, flush=True)
            rows=[]
            for count in (5,20,50):
                print('tasks', count, file=sys.stderr, flush=True)
                board=module.LoopBoard(root,lambda card:None)
                model=orchestrator_lanes.build_lanes([], [run('testing',rid=f'20261022-000000-{i:06}') for i in range(count)])
                first=measure(lambda:board.set_model(model),1)
                unchanged=measure(lambda:board.set_model(model),100)
                with patch.object(board,'_draw_ring',wraps=board._draw_ring) as draw:
                    resize=measure(lambda:board._resize(SimpleNamespace(width=700+draw.call_count,height=700)),100)
                    if hasattr(board,'_finish_resize'):board._finish_resize()
                    calls=draw.call_count
                ring_cached=measure(board._draw_ring)
                rows.append(dict(tasks=count,first_ms=first,unchanged_ms=unchanged,resize_event_ms=resize,
                    resize_draw_calls=calls,ring_repeat_ms=ring_cached))
                if hasattr(board,'close'):board.close()
                board.frame.destroy()
            result[label]=rows
        print(json.dumps(result), file=sys.stderr, flush=True)
        print('character benchmark', file=sys.stderr, flush=True)
        canvas=tk.Canvas(root)
        before=old_character.CharacterView(canvas,canvas=canvas,background='#080f20')
        result['character_before']={'frame_ms':measure(before._draw,100),'mood_load_ms':measure(lambda:before._load('idle'),1)}
        before.destroy()
        after=character.CharacterView(canvas,canvas=canvas,background='#080f20')
        deadline=time.monotonic()+5
        while after._worker.request('idle',1) is None and time.monotonic()<deadline:time.sleep(.005)
        after._draw()
        result['character_after']={'frame_ms':measure(after._draw,100),'prepared_cache_lookup_ms':measure(lambda:after._worker.request('idle',1),1000)}
        after.destroy();canvas.destroy()
    finally:
        root.destroy()
        faulthandler.cancel_dump_traceback_later()
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--tk',action='store_true');args=parser.parse_args()
    result={'scope':'synthetic; withdrawn Tk excludes compositor', 'fake_window_after':fake_window()}
    if args.tk:result['tk']=tk_benchmark()
    print(json.dumps(result,indent=2))

"""Opt-in withdrawn-Tk frame-transfer benchmark; no app data or AI adapters."""
import faulthandler
import json
import time
import tkinter as tk
from scripts.dev_control_center.character import CharacterView
from scripts.dev_control_center.sprite_renderer import frame_dimensions


def benchmark():
    faulthandler.dump_traceback_later(30,exit=True)
    root=tk.Tk();root.withdraw();canvas=tk.Canvas(root)
    view=CharacterView(canvas,canvas=canvas,background='#080f20')
    results=[]
    try:
        for factor in (1.0,1.4):
            started=time.perf_counter()
            view.set_display_scale(factor)
            deadline=time.monotonic()+10
            while view._worker.request('idle',view.scale) is None:
                if time.monotonic()>deadline:raise RuntimeError('SPRITE_PREPARE_TIMEOUT')
                time.sleep(.002)
            prepared=(time.perf_counter()-started)*1000
            started=time.perf_counter();view._draw();first=(time.perf_counter()-started)*1000
            timings=[]
            for i in range(144):
                view.index=i%72
                started=time.perf_counter();view._draw();timings.append((time.perf_counter()-started)*1000)
            warm=[]
            for i in range(144):
                view.index=i%72
                started=time.perf_counter();view._draw();warm.append((time.perf_counter()-started)*1000)
            results.append(dict(factor=factor,dimensions=frame_dimensions(view.scale),prepare_ms=round(prepared,3),
                first_upload_ms=round(first,3),mean_frame_ms=round(sum(timings)/len(timings),3),
                p95_frame_ms=round(sorted(timings)[int(len(timings)*.95)-1],3),
                cache_entries=len(view._worker._cache),tk_frames=len(view._tk_frames),
                warm_mean_ms=round(sum(warm)/len(warm),3),warm_p95_ms=round(sorted(warm)[int(len(warm)*.95)-1],3)))
    finally:
        view.destroy();root.destroy();faulthandler.cancel_dump_traceback_later()
    return dict(scope='Windows withdrawn Tk; idle 144 transfers; excludes compositor/input latency',results=results)

if __name__=='__main__':
    print(json.dumps(benchmark(),indent=2))

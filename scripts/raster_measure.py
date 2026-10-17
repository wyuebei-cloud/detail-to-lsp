#!/usr/bin/env python3
"""raster_measure.py - pixel measurement for screenshots / scanned sheets.

Measure with numbers, not by eye. Subcommands (all coordinates in source pixels):

  zoom   IMG x0 y0 x1 y1 [--k 4] --out z.png    nearest-neighbour zoom for visual reading
  col    IMG x y0 y1 [--thr 200]                dark runs down a column  -> edge positions
  row    IMG y x0 x1 [--thr 200]                dark runs along a row
  bbox   IMG x0 y0 x1 y1 [--thr 120]            ink bounding box inside a window
  lines  IMG x0 y0 x1 y1 --axis rows|cols       runs of rows/cols that contain ink (text lines,
                                                 parallel edges); widen the window until the
                                                 runs stop changing - a clipped window lies
  dots   IMG y0 y1 [--x0 --x1 --cell 40]        map of where faint/dotted rows exist
  edge   IMG x0 y0 x1 y1                        sub-pixel centre of a thin line crossing the
                                                 window (intensity-weighted), for calibration
  fitarc IMG x0 y0 x1 y1 [--thr 150]            circle fit to ink pixels in the window

Library: from raster_measure import load, runs, ink_bbox, row_runs, col_runs, weighted_center
"""
import sys, os, argparse, math
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def load(path):
    return np.asarray(Image.open(path).convert('L')).astype(int)

def runs(vec, thr, off=0):
    """[(start, end, min_gray, centre)] of consecutive values < thr."""
    out, s = [], None
    for i, v in enumerate(list(vec) + [255]):
        if v < thr and s is None: s = i
        elif v >= thr and s is not None:
            seg = vec[s:i]; w = (255 - np.asarray(seg, float))
            c = s + (w * np.arange(len(seg))).sum() / w.sum() if w.sum() else (s + i - 1) / 2
            out.append((s + off, i - 1 + off, int(min(seg)), round(c + off, 2))); s = None
    return out

def ink_bbox(a, x0, y0, x1, y1, thr=120):
    ys, xs = np.where(a[y0:y1, x0:x1] < thr)
    if len(xs) == 0: return None
    return (xs.min() + x0, ys.min() + y0, xs.max() + x0, ys.max() + y0)

def row_runs(a, x0, y0, x1, y1, thr=120):
    """Runs of rows that contain ink -> [(y_start, y_end)]."""
    has = (a[y0:y1, x0:x1] < thr).any(1)
    return [(s + y0, e + y0) for s, e, _, _ in runs(np.where(has, 0, 255), 128)]

def col_runs(a, x0, y0, x1, y1, thr=120):
    has = (a[y0:y1, x0:x1] < thr).any(0)
    return [(s + x0, e + x0) for s, e, _, _ in runs(np.where(has, 0, 255), 128)]

def weighted_center(a, x0, y0, x1, y1):
    w = 255.0 - a[y0:y1, x0:x1]
    w[w < 30] = 0
    ys, xs = np.mgrid[y0:y1, x0:x1]
    s = w.sum()
    return (float((w * xs).sum() / s), float((w * ys).sum() / s)) if s else None

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    z = sp.add_parser('zoom'); z.add_argument('img'); [z.add_argument(n, type=int) for n in ('x0', 'y0', 'x1', 'y1')]
    z.add_argument('--k', type=int, default=4); z.add_argument('--out', required=True)
    c = sp.add_parser('col'); c.add_argument('img'); [c.add_argument(n, type=int) for n in ('x', 'y0', 'y1')]
    c.add_argument('--thr', type=int, default=200)
    r = sp.add_parser('row'); r.add_argument('img'); [r.add_argument(n, type=int) for n in ('y', 'x0', 'x1')]
    r.add_argument('--thr', type=int, default=200)
    b = sp.add_parser('bbox'); b.add_argument('img'); [b.add_argument(n, type=int) for n in ('x0', 'y0', 'x1', 'y1')]
    b.add_argument('--thr', type=int, default=120)
    l = sp.add_parser('lines'); l.add_argument('img'); [l.add_argument(n, type=int) for n in ('x0', 'y0', 'x1', 'y1')]
    l.add_argument('--axis', choices=['rows', 'cols'], default='rows'); l.add_argument('--thr', type=int, default=120)
    d = sp.add_parser('dots'); d.add_argument('img'); d.add_argument('y0', type=int); d.add_argument('y1', type=int)
    d.add_argument('--x0', type=int, default=0); d.add_argument('--x1', type=int); d.add_argument('--cell', type=int, default=40)
    d.add_argument('--thr', type=int, default=235)
    e = sp.add_parser('edge'); e.add_argument('img'); [e.add_argument(n, type=int) for n in ('x0', 'y0', 'x1', 'y1')]
    f = sp.add_parser('fitarc'); f.add_argument('img'); [f.add_argument(n, type=int) for n in ('x0', 'y0', 'x1', 'y1')]
    f.add_argument('--thr', type=int, default=150)
    a = ap.parse_args()
    img = load(a.img)
    if a.cmd == 'zoom':
        im = Image.open(a.img).crop((a.x0, a.y0, a.x1, a.y1))
        im.resize((im.width * a.k, im.height * a.k), Image.NEAREST).save(a.out)
        print(f'{a.out}: zoom x{a.k}; source px = {a.x0} + zx/{a.k}, {a.y0} + zy/{a.k}')
    elif a.cmd == 'col':
        for s, e_, m, cc in runs(img[a.y0:a.y1, a.x], a.thr, a.y0): print(f'y {s}-{e_}  min {m}  centre {cc}')
    elif a.cmd == 'row':
        for s, e_, m, cc in runs(img[a.y, a.x0:a.x1], a.thr, a.x0): print(f'x {s}-{e_}  min {m}  centre {cc}')
    elif a.cmd == 'bbox':
        print(ink_bbox(img, a.x0, a.y0, a.x1, a.y1, a.thr))
        bb = ink_bbox(img, a.x0, a.y0, a.x1, a.y1, a.thr)
        if bb and (bb[0] == a.x0 or bb[1] == a.y0 or bb[2] == a.x1 - 1 or bb[3] == a.y1 - 1):
            print('WARNING: ink touches the window edge - widen the window, the bbox may be clipped')
    elif a.cmd == 'lines':
        rr = row_runs(img, a.x0, a.y0, a.x1, a.y1, a.thr) if a.axis == 'rows' else col_runs(img, a.x0, a.y0, a.x1, a.y1, a.thr)
        for s, e_ in rr: print(f'{a.axis[:-1]} {s}-{e_}  (size {e_ - s + 1}, centre {(s + e_) / 2})')
    elif a.cmd == 'dots':
        x1 = a.x1 or img.shape[1]
        for y in range(a.y0, a.y1):
            row = ''.join('#' if (img[max(0, y - 1):y + 2, x:x + a.cell] < a.thr).sum() > 3 else '.' for x in range(a.x0, x1, a.cell))
            if '#' in row: print(f'{y:5d} {row}')
    elif a.cmd == 'edge':
        print(weighted_center(img, a.x0, a.y0, a.x1, a.y1))
    elif a.cmd == 'fitarc':
        from detail_model import fit_circle
        ys, xs = np.where(img[a.y0:a.y1, a.x0:a.x1] < a.thr)
        cx, cy, r, rms = fit_circle(list(zip(xs + a.x0, ys + a.y0)))
        print(f'centre ({cx:.2f}, {cy:.2f})  r {r:.2f} px  rms {rms:.2f} px  ({len(xs)} ink px)')

if __name__ == '__main__':
    main()

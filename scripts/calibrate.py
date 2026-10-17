#!/usr/bin/env python3
"""calibrate.py - scale from several known dimensions, with residuals.

  python calibrate.py 1245.0=13\\'-0\\ 1/4\\" 483=60.727 273.5=34.5 --axis x,x,y
  python calibrate.py --pairs pairs.json

Each pair is SOURCE_LENGTH=TRUE_LENGTH. Source length is in pixels or PDF
points; true length is inches or architectural text (5'-0 3/4", 1'-6").
Prints the least-squares scale (source units per inch) per axis and the
residual of every pair. A residual well above the measuring precision means
either the pair was misread or the screenshot was scaled non-uniformly - do
not proceed until it is explained.
"""
import sys, os, json, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from detail_model import ftin

def parse_true(s):
    try:
        return float(s)
    except ValueError:
        return ftin(s)

def fit(pairs):
    """pairs: [(src_len, true_in)] -> (scale, [(src, true, model_len, err_in, err_pct)])."""
    num = sum(s * t for s, t in pairs); den = sum(t * t for s, t in pairs)
    k = num / den
    res = [(s, t, s / k, s / k - t, 100 * (s / k - t) / t) for s, t in pairs]
    return k, res

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pairs', nargs='*', help='SRC=TRUE')
    ap.add_argument('--axis', help='comma list x/y per pair (fit separately)')
    ap.add_argument('--json')
    a = ap.parse_args()
    if a.json:
        raw = json.load(open(a.json))
        pairs = [(float(p[0]), parse_true(str(p[1]))) for p in raw]
        axes = [p[2] if len(p) > 2 else 'x' for p in raw]
    else:
        pairs = [(float(p.split('=', 1)[0]), parse_true(p.split('=', 1)[1])) for p in a.pairs]
        axes = a.axis.split(',') if a.axis else ['x'] * len(pairs)
    groups = {}
    for p, ax in zip(pairs, axes):
        groups.setdefault(ax, []).append(p)
    allk, allres = fit(pairs)
    for ax, ps in sorted(groups.items()):
        k, res = fit(ps)
        print(f'axis {ax}: {k:.5f} src units per inch  ({len(ps)} pairs)')
        for s, t, m, e, pc in res:
            print(f'   src {s:9.3f}  true {t:9.4f} in  -> {m:9.4f} in   err {e:+.4f} in ({pc:+.2f}%)')
    if len(groups) > 1:
        print(f'combined: {allk:.5f}   x/y ratio {fit(groups.get("x", pairs))[0] / fit(groups.get("y", pairs))[0]:.4f}'
              '  (should be 1.000 +- measurement noise)')

if __name__ == '__main__':
    # A pipe on Windows uses the ANSI code page (cp1252); drawing text can contain
    # characters it cannot encode (private-use symbol glyphs, U+2248). Escape them
    # instead of crashing, so the tools behave the same on every platform.
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, 'reconfigure'):
            _s.reconfigure(errors='backslashreplace')
    main()

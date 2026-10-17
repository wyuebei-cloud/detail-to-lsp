#!/usr/bin/env python3
"""pdf_extract.py - pull vector paths and text out of a PDF region.

  python pdf_extract.py sheet.pdf --page 0 --bbox 697,409,1016,652 --render crop.png --dpi 300 --json ext.json

Prints a stroke-class table (width x colour x dash), arc fits for curved paths,
and every word with its position. Coordinates are pdfplumber's: x to the right,
'top' downward, in points. Use to_model() to convert to model inches once the
scale (pt per inch) and origin are known (see calibrate.py).

Library use:
    from pdf_extract import extract, to_model, sample_path, path_arcs
    ex = extract('sheet.pdf', 0, (x0, top, x1, bottom))
    for p in ex['paths']: ...
"""
import sys, os, re, json, math, argparse
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ARCH = re.compile(r"^\d+'(-\d+)?(\s?\d+/\d+)?\"?$|^\d+(\s?\d+/\d+)?\"$|^\d+/\d+\"$|^\d+½\"?$")

def _segs_from_obj(o, kind):
    segs = []
    if kind == 'rect':
        x0, t0, x1, t1 = o['x0'], o['top'], o['x1'], o['bottom']
        P = [(x0, t0), (x1, t0), (x1, t1), (x0, t1)]
        return [('L', P[i], P[(i + 1) % 4]) for i in range(4)], True
    path = o.get('path')
    if path:
        cur = start = None
        for cmd in path:
            op = cmd[0]
            if op == 'm':
                cur = start = tuple(cmd[1])
            elif op == 'l':
                p = tuple(cmd[1]); segs.append(('L', cur, p)); cur = p
            elif op == 'c':
                c1, c2, p = tuple(cmd[1]), tuple(cmd[2]), tuple(cmd[3])
                segs.append(('C', cur, c1, c2, p)); cur = p
            elif op == 'h' and cur and start and cur != start:
                segs.append(('L', cur, start)); cur = start
        closed = bool(segs) and segs[0][1] == segs[-1][-1]
        return segs, closed
    pts = [tuple(p) for p in o.get('pts', [])]
    return [('L', pts[i], pts[i + 1]) for i in range(len(pts) - 1)], False

def extract(pdf_path, page=0, bbox=None):
    import pdfplumber
    pg = pdfplumber.open(pdf_path).pages[page]
    reg = pg.crop(bbox) if bbox else pg
    paths = []
    for kind, objs in (('line', reg.lines), ('curve', reg.curves), ('rect', reg.rects)):
        for o in objs:
            segs, closed = _segs_from_obj(o, kind)
            if not segs:
                continue
            col = o.get('stroking_color'); fcol = o.get('non_stroking_color')
            paths.append({'kind': kind, 'lw': round(float(o.get('linewidth') or 0), 3),
                          'color': _col(col), 'fill': bool(o.get('fill')), 'fill_color': _col(fcol),
                          'stroke': bool(o.get('stroke', True)), 'dash': _dash(o.get('dash')),
                          'segs': segs, 'closed': closed})
    words = []
    for w in reg.extract_words(extra_attrs=['size', 'fontname', 'upright'], keep_blank_chars=False, use_text_flow=False):
        words.append({'text': w['text'], 'x0': w['x0'], 'x1': w['x1'], 'top': w['top'], 'bottom': w['bottom'],
                      'size': round(w['size'], 2), 'font': w['fontname'], 'upright': w['upright']})
    return {'pdf': os.path.abspath(pdf_path), 'page': page, 'bbox': list(bbox) if bbox else None,
            'paths': paths, 'words': words}

def _col(c):
    if c is None: return None
    if isinstance(c, (list, tuple)): return tuple(round(float(x), 3) for x in c)
    return c

def _dash(d):
    if not d: return None
    try:
        arr = d[0] if isinstance(d, (list, tuple)) else d
        return tuple(round(float(x), 2) for x in arr) or None
    except Exception:
        return str(d)

def bezier(p0, c1, c2, p1, n=12):
    out = []
    for i in range(n + 1):
        t = i / n; a = (1 - t) ** 3; b = 3 * (1 - t) ** 2 * t; c = 3 * (1 - t) * t * t; d = t ** 3
        out.append((a * p0[0] + b * c1[0] + c * c2[0] + d * p1[0], a * p0[1] + b * c1[1] + c * c2[1] + d * p1[1]))
    return out

def sample_path(p, n=12):
    """Dense point list (pt, top-down) for one extracted path."""
    pts = []
    for s in p['segs']:
        if s[0] == 'L':
            if not pts: pts.append(s[1])
            pts.append(s[2])
        else:
            b = bezier(*s[1:], n=n)
            pts += b if not pts else b[1:]
    return pts

def path_arcs(p, min_sweep_deg=20, tol=0.08):
    """Fit a circle to each Bezier segment, then merge neighbours that share a centre
    (within tol x r). -> [(cx, cy, r, rms, sweep_deg, nsegs)] in pt."""
    from detail_model import fit_circle
    fits = []
    for s in p['segs']:
        if s[0] != 'C':
            fits.append(None); continue
        pts = bezier(*s[1:], n=8)
        try:
            cx, cy, r, rms = fit_circle(pts)
        except Exception:
            fits.append(None); continue
        a = [math.atan2(y - cy, x - cx) for x, y in pts]
        sw = sum(((a[i + 1] - a[i] + math.pi) % (2 * math.pi) - math.pi) for i in range(len(a) - 1))
        fits.append([cx, cy, r, rms, sw, 1])
    out, cur = [], None
    for f in fits:
        if f and cur and math.hypot(f[0] - cur[0], f[1] - cur[1]) < tol * cur[2] + 0.1 and abs(f[2] - cur[2]) < tol * cur[2] + 0.1 \
                and (f[4] > 0) == (cur[4] > 0):
            n = cur[5]; cur = [(cur[0] * n + f[0]) / (n + 1), (cur[1] * n + f[1]) / (n + 1), (cur[2] * n + f[2]) / (n + 1),
                               max(cur[3], f[3]), cur[4] + f[4], n + 1]
            continue
        if cur and abs(math.degrees(cur[4])) >= min_sweep_deg:
            out.append((cur[0], cur[1], cur[2], cur[3], math.degrees(cur[4]), cur[5]))
        cur = list(f) if f else None
    if cur and abs(math.degrees(cur[4])) >= min_sweep_deg:
        out.append((cur[0], cur[1], cur[2], cur[3], math.degrees(cur[4]), cur[5]))
    return out

def text_lines(words, gap=1.2):
    """Join upright words on the same baseline into lines -> [{text,x0,x1,top,bottom,size,mid}].
    gap: max horizontal gap between words as a multiple of font size."""
    ws = sorted([w for w in words if w['upright']], key=lambda w: (round(w['bottom'], 0), w['x0']))
    lines = []
    for w in ws:
        L = lines[-1] if lines else None
        if L and abs(L['bottom'] - w['bottom']) < 0.3 * w['size'] and abs(L['size'] - w['size']) < 0.5 \
                and 0 <= w['x0'] - L['x1'] < gap * w['size']:
            L['text'] += ' ' + w['text']; L['x1'] = w['x1']; L['top'] = min(L['top'], w['top'])
            L['words'].append(w)
        else:
            lines.append({'text': w['text'], 'x0': w['x0'], 'x1': w['x1'], 'top': w['top'],
                          'bottom': w['bottom'], 'size': w['size'], 'words': [w]})
    for L in lines:
        L['mid'] = (L['top'] + L['bottom']) / 2.0    # ~ middle of cap height for caps text
    return lines

def to_model(pt, origin_pt, pt_per_in):
    """(x, top) in pt -> model inches with Y up."""
    return ((pt[0] - origin_pt[0]) / pt_per_in, (origin_pt[1] - pt[1]) / pt_per_in)

def stroke_classes(ex):
    c = Counter(); ext = defaultdict(lambda: [1e9, 1e9, -1e9, -1e9])
    for p in ex['paths']:
        key = (p['lw'], p['color'], p['dash'], 'fill' if p['fill'] else 'stroke')
        c[key] += 1
        for s in p['segs']:
            for q in s[1:]:
                e = ext[key]; e[0] = min(e[0], q[0]); e[1] = min(e[1], q[1]); e[2] = max(e[2], q[0]); e[3] = max(e[3], q[1])
    return c, ext

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pdf'); ap.add_argument('--page', type=int, default=0)
    ap.add_argument('--bbox', help='x0,top,x1,bottom in pt (pdfplumber coords)')
    ap.add_argument('--render'); ap.add_argument('--dpi', type=int, default=300)
    ap.add_argument('--json'); ap.add_argument('--arcs', action='store_true', help='list circle fits of curved stroked paths')
    ap.add_argument('--minlw', type=float, default=0.3, help='min stroke width for --arcs (skips glyph outlines)')
    a = ap.parse_args()
    bbox = tuple(float(v) for v in a.bbox.split(',')) if a.bbox else None
    ex = extract(a.pdf, a.page, bbox)
    c, ext = stroke_classes(ex)
    print(f"paths: {len(ex['paths'])}   words: {len(ex['words'])}")
    print('\nstroke classes (width, colour, dash, mode): count, extent x0,top-x1,bottom')
    for k, n in c.most_common():
        e = ext[k]
        print(f'  {str(k):<52} {n:5d}   {e[0]:7.1f},{e[1]:7.1f} - {e[2]:7.1f},{e[3]:7.1f}')
    if a.arcs:
        print('\narc fits (cx, cy, r in pt; rms; sweep deg) for curved paths:')
        for i, p in enumerate(ex['paths']):
            if p['fill'] or p['lw'] < a.minlw:
                continue
            for f in path_arcs(p):
                print(f'  path {i:4d} lw {p["lw"]}: c=({f[0]:.2f},{f[1]:.2f}) r={f[2]:.3f} rms={f[3]:.3f} sweep={f[4]:.0f} segs={f[5]}')
    print('\nwords (x0, top, size) - dimension-like strings marked *')
    for w in sorted(ex['words'], key=lambda w: (round(w['top']), w['x0'])):
        mark = '*' if ARCH.match(w['text'].replace(' ', '')) else ' '
        rot = '' if w['upright'] else ' (rotated)'
        print(f"  {mark} {w['x0']:7.1f} {w['top']:7.1f} {w['size']:5.2f}  {w['text']}{rot}")
    if a.render:
        import pdfplumber
        pg = pdfplumber.open(a.pdf).pages[a.page]
        im = (pg.crop(bbox) if bbox else pg).to_image(resolution=a.dpi).original
        im.save(a.render)
        print(f'\nrendered -> {a.render} ({im.width}x{im.height}); px = (pt - bbox origin) * {a.dpi / 72:.4f}')
    if a.json:
        json.dump(ex, open(a.json, 'w'), indent=0)
        print('json ->', a.json)

if __name__ == '__main__':
    main()

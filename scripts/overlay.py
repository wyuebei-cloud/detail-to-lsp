#!/usr/bin/env python3
"""overlay.py - render what the .lsp WOULD draw (via lisp_sim) on top of the source.

  python overlay.py out/UB-X.lsp --out out/check            # uses out/UB-X.calib.json
  python overlay.py out/UB-X.lsp --out out/check --crop 40,-40,80,0 --crop 120,-20,170,5
  python overlay.py out/UB-X.lsp --out out/check --tiles 3x2 --roi -2,-70,185,20

Outputs in --out:
  overlay.png            source (faded) + simulated entities, coloured by layer
  tile_*.png / crop_*.png zoomed views for junction checks
  coverage.png           red = source ink nobody claimed, blue = model ink with no source ink
  coverage.txt           percentages + largest blobs with MODEL coordinates

Because the overlay renders the simulated entities, it shows the script itself,
not a separate Python drawing of the intent.
"""
import sys, os, math, json, re, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import lisp_sim
from detail_model import fmt_arch, arc_from_bulge, line_x

HERE = os.path.dirname(os.path.abspath(__file__))
FONTDIR = os.path.join(os.path.dirname(HERE), 'assets', 'fonts')
PALETTE = [(220, 30, 30), (0, 110, 230), (0, 160, 60), (200, 0, 200), (240, 120, 0),
           (0, 170, 170), (130, 80, 0), (90, 90, 220), (180, 150, 0), (120, 120, 120)]

# ------------------------------------------------------------------ source
def load_source(calib, zoom=None):
    if calib['kind'] == 'image':
        im = Image.open(calib['image']).convert('RGB')
        s = calib['px_per_in']; sy = calib.get('py_per_in', s)
        z = zoom or max(1, min(4, math.ceil(22.0 / s)))
        u0, v0 = calib['origin_px']
        big = im.resize((im.width * z, im.height * z), Image.LANCZOS) if z > 1 else im
        return im, big, z, (lambda p: (z * (u0 + p[0] * s), z * (v0 - p[1] * sy))), s
    import pdfplumber
    pg = pdfplumber.open(calib['pdf']).pages[calib['page']]
    x0, t0, x1, t1 = calib['bbox_pt']
    k = calib['dpi'] / 72.0
    im = pg.crop((x0, t0, x1, t1)).to_image(resolution=calib['dpi']).original.convert('RGB')
    ox, ot = calib['origin_pt']; ppi = calib['pt_per_in'] * k
    u0, v0 = (ox - x0) * k, (ot - t0) * k
    return im, im, 1, (lambda p: (u0 + p[0] * ppi, v0 - p[1] * ppi)), ppi

def inv_T(T, z):
    a = T((0.0, 0.0)); b = T((1.0, 1.0))
    sx, sy = b[0] - a[0], a[1] - b[1]
    return lambda u, v: ((u * z - a[0]) / sx, (a[1] - v * z) / sy)

# ------------------------------------------------------------------ text
_fcache = {}
def font_for(style_font, size_px):
    f = (style_font or '').lower()
    bold = 'bd' in f or 'bold' in f or f.endswith('b.ttf')
    path = os.path.join(FONTDIR, 'LiberationSans-Bold.ttf' if bold else 'LiberationSans-Regular.ttf')
    key = (path, max(4, int(round(size_px))))
    if key not in _fcache:
        try:
            _fcache[key] = ImageFont.truetype(path, key[1])
        except OSError:
            _fcache[key] = ImageFont.load_default()
    return _fcache[key]

def cap_ratio(style_font):
    f = font_for(style_font, 200)
    try:
        b = f.getbbox('H'); return (b[3] - b[1]) / 200.0
    except Exception:
        return 0.72

def decode_text(s):
    s = re.sub(r'\\U\+([0-9A-Fa-f]{4})', lambda m: chr(int(m.group(1), 16)), s)
    return s.replace('%%c', '\u00d8').replace('%%C', '\u00d8').replace('%%d', '\u00b0').replace('%%p', '\u00b1')

JUST = {(0, 0): 'L', (1, 0): 'C', (2, 0): 'R', (4, 0): 'M', (0, 1): 'BL', (1, 1): 'BC', (2, 1): 'BR',
        (0, 2): 'ML', (1, 2): 'MC', (2, 2): 'MR', (0, 3): 'TL', (1, 3): 'TC', (2, 3): 'TR'}

def draw_text(img, s, at, cap_px, rot_deg, just, color, style_font, mask=False):
    """Draw text with AutoCAD-like justification. cap_px = TTF text height (cap height)."""
    under = '%%u' in s.lower()
    s = re.sub(r'%%[uUoO]', '', decode_text(s))
    if not s.strip() or cap_px < 1:
        return
    fnt = font_for(style_font, cap_px / cap_ratio(style_font))
    w = fnt.getlength(s); asc, desc = fnt.getmetrics()
    pad = 4
    cv = Image.new('L', (int(w) + 2 * pad, asc + desc + 2 * pad), 0)
    ImageDraw.Draw(cv).text((pad, pad), s, font=fnt, fill=255)
    base = pad + asc
    if under:
        uy = min(cv.height - 1, int(base + cap_px * 0.25))
        ImageDraw.Draw(cv).line([(pad, uy), (pad + w, uy)], fill=255, width=max(1, int(cap_px * 0.08)))
    hj = {'L': 0, 'C': 0.5, 'R': 1, 'M': 0.5}.get(just[-1] if just not in ('M',) else 'M', 0)
    ax = pad + w * hj
    v = just[0] if len(just) == 2 else ('M' if just == 'M' else 'B')
    ay = {'B': base, 'M': base - cap_px / 2, 'T': base - cap_px}[v]
    cx, cy = cv.width / 2, cv.height / 2
    th = math.radians(rot_deg)
    if abs(rot_deg) > 0.01:
        cv2 = cv.rotate(rot_deg, expand=True, resample=Image.BICUBIC)
        dx, dy = ax - cx, ay - cy
        nx = dx * math.cos(th) + dy * math.sin(th); ny = -dx * math.sin(th) + dy * math.cos(th)
        ax2, ay2 = cv2.width / 2 + nx, cv2.height / 2 + ny
        cv = cv2
    else:
        ax2, ay2 = ax, ay
    pos = (int(round(at[0] - ax2)), int(round(at[1] - ay2)))
    if mask:
        img.paste(255, pos, cv)
    else:
        img.paste(Image.new('RGB', cv.size, color), pos, cv)

# ------------------------------------------------------------------ geometry from entities
def items_dict(items):
    d = {}
    for c, v in items:
        d.setdefault(c, []).append(v)
    return d

def catmull(pts, n=10):
    if len(pts) < 3:
        return pts
    P = [pts[0]] + pts + [pts[-1]]; out = []
    for i in range(1, len(P) - 2):
        for j in range(n):
            t = j / n
            out.append(tuple(0.5 * (2 * P[i][k] + (-P[i - 1][k] + P[i + 1][k]) * t
                                    + (2 * P[i - 1][k] - 5 * P[i][k] + 4 * P[i + 1][k] - P[i + 2][k]) * t * t
                                    + (-P[i - 1][k] + 3 * P[i][k] - 3 * P[i + 1][k] + P[i + 2][k]) * t ** 3) for k in range(2)))
    out.append(pts[-1]); return out

def arrow_poly(tip, frm, size):
    L = math.hypot(frm[0] - tip[0], frm[1] - tip[1]) or 1.0
    ux, uy = (frm[0] - tip[0]) / L, (frm[1] - tip[1]) / L
    b = (tip[0] + ux * size, tip[1] + uy * size); w = size / 6.0
    return [tip, (b[0] - uy * w, b[1] + ux * w), (b[0] + uy * w, b[1] - ux * w)]

def dim_parts(d, dv, style_font):
    """Approximate AutoCAD rendering of a DIMENSION -> (polys, fills, texts) in model coords."""
    p1, p2, dl = d[13][0][:2], d[14][0][:2], d[10][0][:2]
    kind = d.get(70, [0])[0]
    sc = dv.get('DIMSCALE', 1.0) or 1.0
    rot = math.atan2(p2[1] - p1[1], p2[0] - p1[0]) if kind == 1 else d.get(50, [0.0])[0]
    obl = d.get(52, [0.0])[0]
    u = (math.cos(rot), math.sin(rot)); n = (-u[1], u[0])
    w = (math.cos(obl), math.sin(obl)) if abs(obl) > 1e-9 else n
    q = (dl[0] + u[0], dl[1] + u[1])
    f1 = line_x(p1, (p1[0] + w[0], p1[1] + w[1]), dl, q) or p1
    f2 = line_x(p2, (p2[0] + w[0], p2[1] + w[1]), dl, q) or p2
    exo, exe = dv.get('DIMEXO', 0.0625) * sc, dv.get('DIMEXE', 0.18) * sc
    polys, fills, texts = [], [], []
    for p, f in ((p1, f1), (p2, f2)):
        L = math.hypot(f[0] - p[0], f[1] - p[1])
        if L > 1e-6:
            e = ((f[0] - p[0]) / L, (f[1] - p[1]) / L)
            polys.append([(p[0] + e[0] * exo, p[1] + e[1] * exo), (f[0] + e[0] * exe, f[1] + e[1] * exe)])
    val = abs((p2[0] - p1[0]) * u[0] + (p2[1] - p1[1]) * u[1]) if kind != 1 else math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if dv.get('DIMLUNIT', 2) == 4:
        txt = fmt_arch(val, dv.get('DIMDEC', 2), dv.get('DIMZIN', 3))
    else:
        txt = f"{val:.{dv.get('DIMDEC', 2)}f}"
    ov = d.get(1, [''])[0] or ''
    if ov:
        txt = ov.replace('<>', txt)
    h = dv.get('DIMTXT', 0.18) * sc; asz = dv.get('DIMASZ', 0.18) * sc; gap = dv.get('DIMGAP', 0.09) * sc
    fnt = font_for(style_font, 100)
    tw = fnt.getlength(decode_text(txt)) / 100.0 * h / cap_ratio(style_font)
    Ld = math.hypot(f2[0] - f1[0], f2[1] - f1[1])
    inside = Ld >= tw + 2 * asz + 2 * gap
    polys.append([f1, f2])
    for a, b in ((f1, f2), (f2, f1)):
        if inside:
            fills.append(arrow_poly(a, b, asz))
        else:
            out = (2 * a[0] - b[0], 2 * a[1] - b[1])
            fills.append(arrow_poly(a, out, asz))
            e = ((a[0] - b[0]) / (Ld or 1), (a[1] - b[1]) / (Ld or 1))
            polys.append([a, (a[0] + e[0] * 2 * asz, a[1] + e[1] * 2 * asz)])
    ang = math.degrees(rot)
    while ang > 90.0001: ang -= 180
    while ang <= -90: ang += 180
    ra = math.radians(ang); nn = (-math.sin(ra), math.cos(ra))
    mid = ((f1[0] + f2[0]) / 2, (f1[1] + f2[1]) / 2)
    off = (gap + h / 2) if dv.get('DIMTAD', 0) else 0.0
    texts.append((txt, (mid[0] + nn[0] * off, mid[1] + nn[1] * off), h, ang, 'MC'))
    return polys, fills, texts

def entity_parts(rec, tables, A):
    """-> polys, fills, texts (model coords) for one simulated entity."""
    d = items_dict(rec['items'])
    t = rec['type']; polys, fills, texts = [], [], []
    if t == 'LINE':
        polys.append([d[10][0][:2], d[11][0][:2]])
    elif t == 'LWPOLYLINE':
        vs = d[10]; bs = d.get(42, [0.0] * len(vs)); closed = bool(d.get(70, [0])[0] & 1)
        from detail_model import sample_verts
        pts = sample_verts([(v[0], v[1], b) for v, b in zip(vs, bs)], closed)
        w = d.get(43, [0.0])[0]
        if w and w > 0:
            if len(vs) == 2 and closed and all(abs(abs(b) - 1) < 1e-6 for b in bs):   # donut / dot
                c = ((vs[0][0] + vs[1][0]) / 2, (vs[0][1] + vs[1][1]) / 2)
                ro = math.hypot(vs[1][0] - vs[0][0], vs[1][1] - vs[0][1]) / 2 + w / 2
                fills.append([(c[0] + ro * math.cos(a), c[1] + ro * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 37)])
            else:
                for i in range(len(pts) - 1):
                    a, b2 = pts[i], pts[i + 1]; L = math.hypot(b2[0] - a[0], b2[1] - a[1]) or 1
                    nx, ny = -(b2[1] - a[1]) / L * w / 2, (b2[0] - a[0]) / L * w / 2
                    fills.append([(a[0] + nx, a[1] + ny), (b2[0] + nx, b2[1] + ny), (b2[0] - nx, b2[1] - ny), (a[0] - nx, a[1] - ny)])
        polys.append(pts)
    elif t == 'CIRCLE':
        c, r = d[10][0], d[40][0]
        polys.append([(c[0] + r * math.cos(a), c[1] + r * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 73)])
    elif t == 'ARC':
        c, r, a0, a1 = d[10][0], d[40][0], d[50][0], d[51][0]
        sw = (a1 - a0) % (2 * math.pi)
        polys.append([(c[0] + r * math.cos(a0 + sw * k / 48), c[1] + r * math.sin(a0 + sw * k / 48)) for k in range(49)])
    elif t == 'SOLID':
        fills.append([d[10][0][:2], d[11][0][:2], d[13][0][:2], d[12][0][:2]])
    elif t == 'TEXT':
        j = JUST.get((d.get(72, [0])[0], d.get(73, [0])[0]), 'L')
        p = d[10][0] if j == 'L' else d.get(11, d[10])[0]
        texts.append((d[1][0], p[:2], d[40][0], math.degrees(d.get(50, [0.0])[0]), j, d.get(7, ['Standard'])[0]))
    elif t == 'LEADER':
        pts = [v[:2] for v in d[10]]
        path = catmull(pts) if d.get(72, [0])[0] == 1 else pts
        polys.append(path)
        if d.get(71, [1])[0] == 1:
            dv = A.tables['DIMSTYLE'].get(str(d.get(3, ['STANDARD'])[0]).upper(), {})
            asz = dv.get('DIMASZ', 0.18) * (dv.get('DIMSCALE', 1.0) or 1.0)
            fills.append(arrow_poly(path[0], path[1], asz))
    elif t == 'DIMENSION':
        dv = rec.get('dimvars', {})
        sty = A.tables['STYLE'].get(str(dv.get('DIMTXSTY', 'STANDARD')).upper(), {}).get('3', 'arial.ttf')
        p, f, tx = dim_parts(d, dv, sty)
        polys += p; fills += f; texts += [x + (sty,) for x in tx]
    return polys, fills, texts

# ------------------------------------------------------------------ main render
def render(lsp, cmd, calib, outdir, crops=(), tiles=None, roi=None, tol=None, thr=150, zoom=None, ignore=(), thr_faint=235):
    os.makedirs(outdir, exist_ok=True)
    it = lisp_sim.simulate(lsp, cmd)
    A = it.acad
    src, big, z, T, ppi = load_source(calib, zoom)
    layers = [k for k in A.tables['LAYER'] if k != '0']
    col = {l: PALETTE[i % len(PALETTE)] for i, l in enumerate(sorted(layers))}
    parts = []
    for rec in A.ents:
        lay = str(items_dict(rec['items']).get(8, ['0'])[0]).upper()
        parts.append((lay,) + entity_parts(rec, A.tables, A))
    stylefont = lambda name: A.tables['STYLE'].get(str(name).upper(), {}).get('3', 'arial.ttf')

    # --- overlay
    ov = Image.blend(big, Image.new('RGB', big.size, (255, 255, 255)), 0.55)
    dr = ImageDraw.Draw(ov)
    lw = max(1, z)
    for lay, polys, fills, texts in parts:
        c = col.get(lay, (0, 0, 0))
        for pl in polys:
            dr.line([T(p) for p in pl], fill=c, width=lw)
        for fl in fills:
            dr.polygon([T(p) for p in fl], fill=c)
        for tx in texts:
            s, p, h, rot, j, sty = tx
            draw_text(ov, s, T(p), h * ppi * z, rot, j, c, stylefont(sty) if not sty.lower().endswith('.ttf') else sty)
    # legend
    y = 6
    for l in sorted(col):
        dr.rectangle([6, y, 22, y + 12], fill=col[l]); dr.text((28, y), l, fill=(0, 0, 0)); y += 16
    ov.save(os.path.join(outdir, 'overlay.png'))

    def crop_model(box, name, scale=2):
        x0, y0, x1, y1 = box
        a = T((x0, y1)); b = T((x1, y0))
        c = ov.crop((int(min(a[0], b[0])), int(min(a[1], b[1])), int(max(a[0], b[0])), int(max(a[1], b[1]))))
        if scale != 1 and c.width * scale < 2400:
            c = c.resize((c.width * scale, c.height * scale), Image.LANCZOS)
        c.save(os.path.join(outdir, name))

    for i, box in enumerate(crops):
        crop_model(box, f'crop_{i + 1}.png')
    if tiles:
        nx, ny = tiles
        W, H = ov.size
        for i in range(nx):
            for j in range(ny):
                ov.crop((W * i // nx, H * j // ny, W * (i + 1) // nx, H * (j + 1) // ny)).save(
                    os.path.join(outdir, f'tile_{j + 1}_{i + 1}.png'))

    # --- coverage at source resolution (zoom 1)
    T1 = (lambda p: (T(p)[0] / z, T(p)[1] / z))
    ppx = ppi
    tol = tol if tol is not None else max(2, int(round(0.2 * ppx)))
    gray = np.asarray(src.convert('L'))
    src_ink = gray < thr
    src_faint = gray < thr_faint      # faint/dotted source ink still supports model ink
    mimg = Image.new('L', src.size, 0); md = ImageDraw.Draw(mimg)
    timg = Image.new('L', src.size, 0)            # text-only mask -> annotation zones
    for lay, polys, fills, texts in parts:
        for pl in polys:
            md.line([T1(p) for p in pl], fill=255, width=1)
        for fl in fills:
            md.polygon([T1(p) for p in fl], fill=255)
        for tx in texts:
            s, p, h, rot, j, sty = tx
            fnt = stylefont(sty) if not sty.lower().endswith('.ttf') else sty
            draw_text(mimg, s, T1(p), h * ppx, rot, j, None, fnt, mask=True)
            draw_text(timg, s, T1(p), h * ppx, rot, j, None, fnt, mask=True)
    model_ink = np.asarray(mimg) > 0
    text_ink = np.asarray(timg) > 0
    from scipy import ndimage
    st = np.ones((2 * tol + 1, 2 * tol + 1), bool)
    model_d = ndimage.binary_dilation(model_ink, st)
    src_d = ndimage.binary_dilation(src_faint, st)
    region = np.ones_like(src_ink)
    inv = inv_T(T, z)
    def model_box_px(box):
        a = T1((box[0], box[3])); b = T1((box[2], box[1]))
        return (max(0, int(a[0])), max(0, int(a[1])), int(b[0]) + 1, int(b[1]) + 1)
    if roi:
        region[:] = False
        x0, y0, x1, y1 = model_box_px(roi); region[y0:y1, x0:x1] = True
    for box in ignore:
        x0, y0, x1, y1 = model_box_px(box); region[y0:y1, x0:x1] = False
    unclaimed = src_ink & ~model_d & region
    spurious = model_ink & ~src_d & region
    # annotation zones: around model text, generous enough to absorb font-width differences
    zr = max(3, int(round(1.6 * d_capmax(parts) * ppx)))
    zone = ndimage.binary_dilation(text_ink, np.ones((zr, 3 * zr), bool)) if text_ink.any() else text_ink
    n_src = int((src_ink & region).sum()); n_mod = int((model_ink & region).sum())
    cov = np.stack([gray] * 3, -1).astype(np.uint8)
    cov = (255 - (255 - cov) * 0.35).astype(np.uint8)
    cov[unclaimed] = (230, 0, 0); cov[spurious] = (0, 80, 255)
    Image.fromarray(cov).save(os.path.join(outdir, 'coverage.png'))
    ug, sg = unclaimed & ~zone, spurious & ~zone
    n_srcg = int((src_ink & region & ~zone).sum()); n_modg = int((model_ink & region & ~zone).sum())
    rep = [f'tolerance {tol}px, ink threshold {thr} (support threshold {thr_faint}), {ppx:.2f} px/in at source resolution',
           'ALL INK',
           f'  source ink unclaimed by model : {100.0 * unclaimed.sum() / max(1, n_src):5.2f} %  ({int(unclaimed.sum())} px)',
           f'  model ink with no source ink  : {100.0 * spurious.sum() / max(1, n_mod):5.2f} %  ({int(spurious.sum())} px)',
           'OUTSIDE TEXT ZONES (geometry, leaders, dims, missing text) - the number to drive to ~0',
           f'  source ink unclaimed by model : {100.0 * ug.sum() / max(1, n_srcg):5.2f} %  ({int(ug.sum())} px)',
           f'  model ink with no source ink  : {100.0 * sg.sum() / max(1, n_modg):5.2f} %  ({int(sg.sum())} px)',
           'Text inside zones differs mostly by font; judge text by eye on overlay.png.']
    cov[zone & ~unclaimed & ~spurious & (gray > 200)] = (255, 250, 215)
    Image.fromarray(cov).save(os.path.join(outdir, 'coverage.png'))
    for name, m in (('UNCLAIMED source ink (outside text zones)', ug), ('SPURIOUS model ink (outside text zones)', sg)):
        lab, n = ndimage.label(ndimage.binary_dilation(m, np.ones((3, 3), bool)) & region)
        if n == 0:
            continue
        sizes = ndimage.sum(m, lab, range(1, n + 1))
        objs = ndimage.find_objects(lab)
        order = np.argsort(-sizes)[:15]
        rep.append(f'\n{name}: largest blobs (model coords x0,y0 - x1,y1 ; px)')
        for k in order:
            if sizes[k] < 4:
                break
            sl = objs[k]
            a = inv(sl[1].start, sl[0].stop); b = inv(sl[1].stop, sl[0].start)
            rep.append(f'  ({a[0]:8.2f},{a[1]:8.2f}) - ({b[0]:8.2f},{b[1]:8.2f})   {int(sizes[k])} px')
    open(os.path.join(outdir, 'coverage.txt'), 'w').write('\n'.join(rep))
    summary = lisp_sim.summary(it)
    open(os.path.join(outdir, 'sim.txt'), 'w').write(summary)
    return summary, '\n'.join(rep)

def d_capmax(parts):
    hs = [tx[2] for _, _, _, texts in parts for tx in texts]
    return max(hs) if hs else 0.0

def parse_box(s):
    v = [float(x) for x in s.split(',')]
    assert len(v) == 4
    return (min(v[0], v[2]), min(v[1], v[3]), max(v[0], v[2]), max(v[1], v[3]))

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('lsp'); ap.add_argument('--cmd', help='C:NAME (default from file name)')
    ap.add_argument('--calib', help='calib json (default <lsp stem>.calib.json)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--crop', action='append', default=[], help='model box x0,y0,x1,y1')
    ap.add_argument('--tiles', help='NxM grid of zoom tiles, e.g. 3x2')
    ap.add_argument('--roi', help='model box limiting the coverage check')
    ap.add_argument('--ignore', action='append', default=[], help='model box excluded from coverage')
    ap.add_argument('--tol', type=int); ap.add_argument('--thr', type=int, default=150)
    ap.add_argument('--zoom', type=int)
    a = ap.parse_args()
    stem = os.path.splitext(a.lsp)[0]
    calib = json.load(open(a.calib or stem + '.calib.json'))
    cmd = a.cmd or 'C:' + os.path.basename(stem).upper()
    tiles = tuple(int(x) for x in a.tiles.lower().split('x')) if a.tiles else None
    s, r = render(a.lsp, cmd, calib, a.out, [parse_box(c) for c in a.crop], tiles,
                  parse_box(a.roi) if a.roi else None, a.tol, a.thr, a.zoom, [parse_box(c) for c in a.ignore])
    print(s); print(); print(r)

if __name__ == '__main__':
    # A pipe on Windows uses the ANSI code page (cp1252); drawing text can contain
    # characters it cannot encode (private-use symbol glyphs, U+2248). Escape them
    # instead of crashing, so the tools behave the same on every platform.
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, 'reconfigure'):
            _s.reconfigure(errors='backslashreplace')
    main()

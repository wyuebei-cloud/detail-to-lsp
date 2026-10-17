"""detail_model.py - modeling API for detail-to-lsp.

A per-task model.py builds a Detail, adds geometry/annotation in MODEL INCHES
(origin = a meaningful physical point, +Y up), records where each key value
came from, and calls emit(). Everything downstream (LSP, simulation, overlay,
report) derives from this one object, so the preview and the script cannot
drift apart.

    import sys; sys.path.insert(0, '<skill>/scripts')
    from detail_model import *
    d = Detail('CB Gutter Pan', 'UB-CBGP', scale=16)
    R = d.param('R', 60.0, 'dim', '5\\'-0" R. callout')
    d.pline([...], layer='DTL-GEOM', closed=True)
    d.text('PLAN VIEW', (78.2, -54.4), size='label', just='MC')
    d.dim((0, 0), (60.73, 0), (30, 9.9), override=APPROX, expect='5\\'-0 3/4"')
    d.calibrate_image('src.png', origin_px=(23, 180), px_per_in=7.958)
    d.emit('out/UB-CBGP.lsp')
"""
import math, json, os, re, datetime
from fractions import Fraction

APPROX = '≈ <>'          # "approximately" prefix for derived dimensions

# ---------------------------------------------------------------- units
def ftin(s):
    """Parse architectural text to inches: 5'-0 3/4", 2'-10 1/2", 1'-6", 5", 3/8", 2½"."""
    t = s.replace('½', ' 1/2').replace('¼', ' 1/4').replace('¾', ' 3/4')
    t = t.replace('≈', '').replace('~', '').replace('"', '').replace('′', "'").strip()
    ft = 0.0
    if "'" in t:
        a, t = t.split("'", 1)
        ft = float(a.strip() or 0)
        t = t.strip().lstrip('-').strip()
    inch = 0.0
    for part in t.replace('-', ' ').split():
        inch += float(Fraction(part))
    return ft * 12 + inch

def fmt_arch(v, dec=2, zin=3):
    """Format inches like AutoCAD architectural units (DIMLUNIT 4, DIMFRAC 2).
    dec: DIMDEC (0=1", 1=1/2, 2=1/4, 3=1/8, 4=1/16 ...). zin: DIMZIN (3 = 5" and 5'-0")."""
    den = 2 ** dec
    tot = math.floor(abs(v) * den + 0.5 + 1e-9) / den
    ft = int(tot // 12)
    inch = tot - ft * 12
    whole = int(inch)
    fr = Fraction(inch - whole).limit_denominator(den)
    ins = (str(whole) if (whole or not fr) else ('0' if ft else '')) + ((' ' if whole or ft else '') + f'{fr.numerator}/{fr.denominator}' if fr else '')
    ins = ins.strip() or '0'
    if ft == 0 and zin in (0, 3):
        s = ins + '"'
    else:
        s = f"{ft}'-{ins}\""
    return ('-' if v < 0 else '') + s

def norm_dimtext(s):
    return re.sub(r'[\s≈~]', '', s).replace('\\U+2248', '').replace('<>', '')

# ---------------------------------------------------------------- geometry
def polar(p, ang, dist):
    return (p[0] + dist * math.cos(ang), p[1] + dist * math.sin(ang))

def dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])

def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

def line_x(p1, p2, p3, p4):
    """Intersection of infinite lines p1p2 and p3p4 (None if parallel)."""
    d = (p1[0] - p2[0]) * (p3[1] - p4[1]) - (p1[1] - p2[1]) * (p3[0] - p4[0])
    if abs(d) < 1e-12:
        return None
    a = p1[0] * p2[1] - p1[1] * p2[0]
    b = p3[0] * p4[1] - p3[1] * p4[0]
    return ((a * (p3[0] - p4[0]) - (p1[0] - p2[0]) * b) / d,
            (a * (p3[1] - p4[1]) - (p1[1] - p2[1]) * b) / d)

def bulge_from_center(p0, p1, c, ccw=True):
    """Bulge for the arc p0->p1 about center c (ccw or cw)."""
    a0 = math.atan2(p0[1] - c[1], p0[0] - c[0])
    a1 = math.atan2(p1[1] - c[1], p1[0] - c[0])
    sweep = (a1 - a0) % (2 * math.pi) if ccw else -((a0 - a1) % (2 * math.pi))
    return math.tan(sweep / 4.0)

def arc_from_bulge(p0, p1, b):
    """-> (center, radius, start_angle, sweep) for a bulged segment."""
    sweep = 4 * math.atan(b)
    ch = dist(p0, p1)
    r = ch / (2 * math.sin(abs(sweep) / 2))
    m = lerp(p0, p1, 0.5)
    h = r * math.cos(sweep / 2)                     # center distance from chord midpoint
    ux, uy = (p1[0] - p0[0]) / ch, (p1[1] - p0[1]) / ch
    s = 1 if sweep > 0 else -1
    c = (m[0] - uy * h * s, m[1] + ux * h * s)
    a0 = math.atan2(p0[1] - c[1], p0[0] - c[0])
    return c, r, a0, sweep

def sample_verts(verts, closed=False, step_deg=3.0):
    """Expand (x,y,bulge) vertices into a dense point list (for preview/coverage)."""
    pts = []
    n = len(verts)
    segs = n if closed else n - 1
    for i in range(segs):
        x0, y0, b = verts[i]
        x1, y1, _ = verts[(i + 1) % n]
        pts.append((x0, y0))
        if abs(b) > 1e-9:
            c, r, a0, sw = arc_from_bulge((x0, y0), (x1, y1), b)
            k = max(2, int(abs(math.degrees(sw)) / step_deg))
            for j in range(1, k):
                a = a0 + sw * j / k
                pts.append((c[0] + r * math.cos(a), c[1] + r * math.sin(a)))
    last = verts[0] if closed else verts[-1]
    pts.append((last[0], last[1]))
    return pts

class Path:
    """Polyline builder with true arcs.  p = Path((0,0)).line_to((5,0)).arc_to((8,3), center=(5,3), ccw=True)"""
    def __init__(self, start):
        self.v = [[start[0], start[1], 0.0]]
    @property
    def end(self):
        return (self.v[-1][0], self.v[-1][1])
    def line_to(self, p):
        self.v.append([p[0], p[1], 0.0]); return self
    def arc_to(self, p, center=None, ccw=True, bulge=None):
        b = bulge if bulge is not None else bulge_from_center(self.end, p, center, ccw)
        self.v[-1][2] = b
        self.v.append([p[0], p[1], 0.0]); return self
    def arc_center(self, center, sweep_deg):
        """Arc about center by signed sweep (deg, +CCW) from current end."""
        a0 = math.atan2(self.end[1] - center[1], self.end[0] - center[0])
        r = dist(self.end, center)
        a1 = a0 + math.radians(sweep_deg)
        p = (center[0] + r * math.cos(a1), center[1] + r * math.sin(a1))
        self.v[-1][2] = math.tan(math.radians(sweep_deg) / 4)
        self.v.append([p[0], p[1], 0.0]); return self
    def extend(self, other):
        """Append another Path/verts whose first point equals this end."""
        ov = other.v if isinstance(other, Path) else other
        self.v[-1][2] = ov[0][2]
        self.v += [list(x) for x in ov[1:]]; return self
    def verts(self):
        return [tuple(x) for x in self.v]

def reverse_verts(verts):
    """Reverse direction: bulge of segment i moves to the new start vertex and flips sign."""
    pts = [(v[0], v[1]) for v in verts][::-1]
    bs = [v[2] for v in verts[:-1]][::-1]
    return [(pts[i][0], pts[i][1], -bs[i] if i < len(bs) else 0.0) for i in range(len(pts))]

def mirror_verts(verts, xm=None, ym=None):
    """Mirror about x = xm (vertical axis) or y = ym. Bulges flip sign."""
    out = []
    for x, y, b in verts:
        out.append((2 * xm - x if xm is not None else x, 2 * ym - y if ym is not None else y, -b))
    return out

def fillet_path(pts, radii, closed=False):
    """Corner points -> verts with tangent arcs.  radii: number or list per interior corner."""
    n = len(pts)
    if not isinstance(radii, (list, tuple)):
        radii = [radii] * n
    out = []
    rng = range(n) if closed else range(1, n - 1)
    corners = {}
    for i in rng:
        r = radii[i if closed else i - 1] if isinstance(radii, (list, tuple)) else radii
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        if r <= 0:
            continue
        u = ((p0[0] - p1[0]) / dist(p0, p1), (p0[1] - p1[1]) / dist(p0, p1))
        w = ((p2[0] - p1[0]) / dist(p1, p2), (p2[1] - p1[1]) / dist(p1, p2))
        cosang = max(-1.0, min(1.0, u[0] * w[0] + u[1] * w[1]))
        ang = math.acos(cosang)
        if ang < 1e-6 or abs(ang - math.pi) < 1e-6:
            continue
        t = r / math.tan(ang / 2)
        a = (p1[0] + u[0] * t, p1[1] + u[1] * t)
        bpt = (p1[0] + w[0] * t, p1[1] + w[1] * t)
        cross = u[0] * w[1] - u[1] * w[0]           # >0: turn is clockwise when travelling p0->p1->p2
        sweep = math.pi - ang
        bul = math.tan(sweep / 4) * (-1 if cross > 0 else 1)
        corners[i] = (a, bpt, bul)
    for i in range(n):
        if i in corners:
            a, bpt, bul = corners[i]
            out.append((a[0], a[1], bul)); out.append((bpt[0], bpt[1], 0.0))
        else:
            out.append((pts[i][0], pts[i][1], 0.0))
    return out

def offset_verts(verts, d, closed=False):
    """Offset an open/closed bulged polyline by d (positive = left of travel).
    Tangent-continuous joints stay exact; line-line corners are mitred."""
    n = len(verts)
    segs = []
    m = n if closed else n - 1
    for i in range(m):
        x0, y0, b = verts[i]; x1, y1, _ = verts[(i + 1) % n]
        if abs(b) < 1e-12:
            L = dist((x0, y0), (x1, y1)); nx, ny = -(y1 - y0) / L, (x1 - x0) / L
            segs.append(('L', (x0 + nx * d, y0 + ny * d), (x1 + nx * d, y1 + ny * d), 0.0))
        else:
            c, r, a0, sw = arc_from_bulge((x0, y0), (x1, y1), b)
            r2 = r - d if sw > 0 else r + d
            if r2 <= 0:
                raise ValueError('offset collapses an arc')
            p0 = (c[0] + r2 * math.cos(a0), c[1] + r2 * math.sin(a0))
            p1 = (c[0] + r2 * math.cos(a0 + sw), c[1] + r2 * math.sin(a0 + sw))
            segs.append(('A', p0, p1, b))
    out = []
    for i, s in enumerate(segs):
        start = s[1]
        if i > 0 or closed:
            prev = segs[i - 1]
            if dist(prev[2], s[1]) > 1e-6:
                if prev[0] == 'L' and s[0] == 'L':
                    x = line_x(prev[1], prev[2], s[1], s[2])
                    start = x if x else s[1]
                else:
                    out.append((prev[2][0], prev[2][1], 0.0))
        out.append((start[0], start[1], s[3]))
    if not closed:
        out.append((segs[-1][2][0], segs[-1][2][1], 0.0))
    # fix mitred line ends: replace endpoints of line segments by computed joins
    return out

def fit_circle(points):
    """Algebraic (Kasa) circle fit -> (cx, cy, r, rms)."""
    import numpy as np
    P = np.asarray(points, float)
    A = np.c_[2 * P[:, 0], 2 * P[:, 1], np.ones(len(P))]
    b = (P ** 2).sum(1)
    cx, cy, c = np.linalg.lstsq(A, b, rcond=None)[0]
    r = math.sqrt(c + cx * cx + cy * cy)
    rms = float(np.sqrt(((np.hypot(P[:, 0] - cx, P[:, 1] - cy) - r) ** 2).mean()))
    return float(cx), float(cy), r, rms

# ---------------------------------------------------------------- Detail
DEFAULT_LAYERS = {
    'DTL-GEOM':        (7, 35, 'Continuous'),
    'DTL-GEOM-THIN':   (8, 18, 'Continuous'),
    'DTL-GEOM-DOT':    (8, 13, 'DOT'),
    'DTL-GEOM-HIDDEN': (8, 18, 'HIDDEN'),
    'DTL-GEOM-CENTER': (8, 13, 'CENTER'),
    'DTL-TEXT':        (2, 25, 'Continuous'),
    'DTL-DIM':         (4, 18, 'Continuous'),
}

class Detail:
    def __init__(self, title, command, scale=16.0, text_font='arialbd.ttf',
                 text_heights=None, dim_text=0.1, arrow=0.1, dim_dec=2, dim_units='arch',
                 text_layer='DTL-TEXT', dim_layer='DTL-DIM', style='DTL-ARIAL', dimstyle='DTL-DIM'):
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', command):
            raise ValueError('command must be letters/digits/-/_ (e.g. UB-CBGP)')
        self.title, self.command, self.scale = title, command.upper(), float(scale)
        self.text_font, self.style, self.dimstyle = text_font, style, dimstyle
        self.text_heights = text_heights or {'note': 0.1, 'label': 0.13, 'title': 0.15}
        self.dim_text, self.arrow, self.dim_dec, self.dim_units = dim_text, arrow, dim_dec, dim_units
        self.text_layer, self.dim_layer = text_layer, dim_layer
        self.layers = {}            # name -> (color, lw, ltype), in first-use order
        self.layer_defs = dict(DEFAULT_LAYERS)
        self.recs = []
        self.prov = []
        self.dim_checks = []
        self.notes = []
        self.calib = None
        self.source = None
        self.extra_dimvars = {}

    # ---- bookkeeping
    def layer(self, name, color=7, lw=25, ltype='Continuous'):
        """Define (or redefine) a layer. lw in 1/100 mm (25 = 0.25 mm)."""
        self.layer_defs[name] = (int(color), int(lw), ltype); return name

    def _use(self, name):
        if name not in self.layers:
            if name not in self.layer_defs:
                raise KeyError(f'layer {name} not defined; call d.layer(name, color, lw, ltype) first')
            self.layers[name] = self.layer_defs[name]
        return name

    def param(self, name, value, src, note=''):
        """Record a key value. src: 'dim' (from a dimension/callout), 'derived' (computed from
        other params), 'vector' (read from PDF vectors), 'measured' (pixels), 'standard'
        (code/standard plan), 'assumed' (judgement - must be listed for the user)."""
        assert src in ('dim', 'derived', 'vector', 'measured', 'standard', 'assumed'), src
        self.prov.append({'name': name, 'value': value, 'src': src, 'note': note})
        return value

    def note(self, s):
        """Free-text item for the delivery report (open questions, substitutions)."""
        self.notes.append(s)

    def h(self, size):
        """Model text height for a size key or plotted inches."""
        p = self.text_heights[size] if isinstance(size, str) else float(size)
        return p * self.scale

    # ---- geometry
    def line(self, p1, p2, layer='DTL-GEOM'):
        self.recs.append(('LINE', self._use(layer), _p(p1), _p(p2)))

    def pline(self, pts, layer='DTL-GEOM', closed=False, plinegen=False, width=None):
        """pts: [(x,y)] or [(x,y,bulge)] or a Path. width: constant polyline width (group 43)."""
        if isinstance(pts, Path):
            pts = pts.verts()
        v = [(float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0) for p in pts]
        if closed and len(v) > 2 and dist(v[0], v[-1]) < 1e-9:
            v = v[:-1]
        if len(v) < 2:
            raise ValueError('pline needs >= 2 points')
        flags = (1 if closed else 0) | (128 if plinegen else 0)
        self.recs.append(('PL', self._use(layer), flags, v, float(width) if width else None))

    def dot(self, c, dia, layer='DTL-GEOM'):
        """Solid filled circle (donut: 2-vertex closed polyline, bulge 1, width = dia/2)."""
        q = dia / 4.0
        self.pline([(c[0] - q, c[1], 1.0), (c[0] + q, c[1], 1.0)], layer, closed=True, width=dia / 2.0)

    def bar(self, center_pts, dia, bend_r=0.0, layer='DTL-GEOM'):
        """Reinforcing bar drawn as a closed double-line outline with true-arc bends.
        center_pts: corner points of the bar centreline; bend_r: centreline bend radius."""
        cl = fillet_path(center_pts, bend_r) if (bend_r and len(center_pts) > 2) else [(p[0], p[1], 0.0) for p in center_pts]
        r = dia / 2.0
        left = offset_verts(cl, r); right = offset_verts(cl, -r)
        self.pline(left + reverse_verts(right), layer, closed=True)

    def box_label(self, x0, y0, x1, y1, s, size='note', layer=None):
        layer = layer or self.text_layer
        self.rect(x0, y0, x1, y1, layer)
        self.text(s, ((x0 + x1) / 2, (y0 + y1) / 2), size, 'MC', layer=layer)

    def hex_label(self, c, s, w=6.0, h=3.0, vertical=False, size='note', layer=None):
        layer = layer or self.text_layer
        a, b = w / 2, h / 2
        P = [(-a, 0), (-a + b, b), (a - b, b), (a, 0), (a - b, -b), (-a + b, -b)]
        pts = [((c[0] + y, c[1] + x) if vertical else (c[0] + x, c[1] + y)) for x, y in P]
        self.pline(pts, layer, closed=True)
        self.text(s, c, size, 'MC', rot=90 if vertical else 0, layer=layer)

    def rect(self, x0, y0, x1, y1, layer='DTL-GEOM'):
        self.pline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer, closed=True)

    def circle(self, c, r, layer='DTL-GEOM'):
        self.recs.append(('CIRCLE', self._use(layer), _p(c), float(r)))

    def arc(self, c, r, a0_deg, a1_deg, layer='DTL-GEOM'):
        """Stand-alone ARC, CCW from a0 to a1 (degrees)."""
        self.recs.append(('ARC', self._use(layer), _p(c), float(r),
                          math.radians(a0_deg), math.radians(a1_deg)))

    def solid(self, p1, p2, p3, p4=None, layer=None):
        """Filled triangle/quad. Quad order is perimeter order p1,p2,p3,p4."""
        layer = layer or self.text_layer
        p4 = p4 or p3
        # SOLID draws 1-2-4-3, so swap 3 and 4 to accept perimeter order
        self.recs.append(('SOLID', self._use(layer), _p(p1), _p(p2), _p(p4), _p(p3)))

    def fill_convex(self, pts, layer=None):
        """Fill a convex polygon with SOLID triangles (fan)."""
        for i in range(1, len(pts) - 1):
            self.solid(pts[0], pts[i], pts[i + 1], None, layer)

    # ---- annotation
    def text(self, s, p, size='note', just='ML', rot=0.0, layer=None, height=None):
        layer = layer or self.text_layer
        h = float(height) if height else self.h(size)
        self.recs.append(('TEXT', self._use(layer), self.style, _p(p), h, math.radians(rot), just, s))

    def text_lines(self, lines, p, size='note', just='ML', spacing=1.5, **kw):
        """Stacked TEXT lines; p is the anchor of the first line; spacing x cap height."""
        h = self.h(size)
        for i, s in enumerate(lines):
            self.text(s, (p[0], p[1] - i * spacing * h), size, just, **kw)

    def leader(self, pts, arrow=True, spline=False, layer=None):
        """First point = arrowhead end."""
        layer = layer or self.text_layer
        self.recs.append(('LEADER', self._use(layer), self.dimstyle, 1 if arrow else 0,
                          1 if spline else 0, [_p(p) for p in pts]))

    def dim(self, p1, p2, dl, rot=0.0, override=None, oblique=None, kind='ROT', expect=None, layer=None):
        """Linear dimension. rot: 0 horizontal, 90 vertical (deg). kind 'ROT' or 'ALI'.
        oblique: extension-line angle in degrees (e.g. 30). expect: text shown on the source
        drawing - the report compares it with the measured value (independent check)."""
        layer = layer or self.dim_layer
        self.recs.append(('DIM', self._use(layer), self.dimstyle, kind, _p(p1), _p(p2), _p(dl),
                          math.radians(rot), override, math.radians(oblique) if oblique else None))
        if kind == 'ROT':
            a = math.radians(rot)
            val = abs((p2[0] - p1[0]) * math.cos(a) + (p2[1] - p1[1]) * math.sin(a))
        else:
            val = dist(p1, p2)
        self.dim_checks.append({'p1': p1, 'p2': p2, 'value': val, 'expect': expect, 'override': override})

    def section_marker(self, label, c, r=3.0, tip=5.0, half=4.0, tick=1.6, ang=0.0, size='note', layer=None):
        """Circle + filled pointer (triangle minus disk) + cut tick, pointing toward ang (deg)."""
        layer = layer or self.text_layer
        a = math.radians(ang)
        rot = lambda x, y: (c[0] + x * math.cos(a) - y * math.sin(a), c[1] + x * math.sin(a) + y * math.cos(a))
        self.circle(c, r, layer)
        n = 12
        def tri(t):   # distance to triangle edge along local angle t
            return 1.0 / (math.cos(t) / tip + abs(math.sin(t)) / half)
        for i in range(n):
            t0 = -math.pi / 2 + math.pi * i / n; t1 = -math.pi / 2 + math.pi * (i + 1) / n
            p0 = rot(r * math.cos(t0), r * math.sin(t0)); p1 = rot(r * math.cos(t1), r * math.sin(t1))
            q0 = rot(tri(t0) * math.cos(t0), tri(t0) * math.sin(t0)); q1 = rot(tri(t1) * math.cos(t1), tri(t1) * math.sin(t1))
            self.solid(p0, q0, q1, p1, layer)
        self.pline([rot(0, half), rot(0, half + tick)], layer)
        self.text(label, c, size, 'MC', layer=layer)

    def flag(self, base, height=3.0, w=4.7, drop=1.55, layer=None):
        """Pole from base up 'height', pennant at the top pointing +X."""
        layer = layer or self.text_layer
        x, y = base; top = (x, y + height)
        self.pline([base, top], layer)
        self.solid(top, (x + w, top[1] - 0.05), (x, top[1] - drop), None, layer)

    # ---- source registration (for overlay)
    def calibrate_image(self, path, origin_px, px_per_in, py_per_in=None):
        """Raster source: pixel (u,v) of the model origin and pixels per model inch."""
        self.calib = {'kind': 'image', 'image': os.path.abspath(path), 'origin_px': list(origin_px),
                      'px_per_in': float(px_per_in), 'py_per_in': float(py_per_in or px_per_in)}

    def calibrate_pdf(self, path, page, bbox_pt, origin_pt, pt_per_in, dpi=300):
        """Vector source: pdfplumber 'top' coordinates (y down) for bbox and origin."""
        self.calib = {'kind': 'pdf', 'pdf': os.path.abspath(path), 'page': int(page), 'bbox_pt': list(bbox_pt),
                      'origin_pt': list(origin_pt), 'pt_per_in': float(pt_per_in), 'dpi': int(dpi)}

    # ---- outputs
    def dimvars(self):
        sc = self.scale
        v = [('DIMSCALE', sc), ('DIMTXT', self.dim_text), ('DIMASZ', self.arrow), ('DIMEXO', 0.0625),
             ('DIMEXE', 0.0625), ('DIMGAP', 0.04), ('DIMDLE', 0.0), ('DIMTAD', 1), ('DIMJUST', 0),
             ('DIMTIH', 0), ('DIMTOH', 0), ('DIMTIX', 1), ('DIMATFIT', 1), ('DIMTOFL', 1),
             ('DIMLFAC', 1.0), ('DIMRND', 0.0), ('DIMTXSTY', self.style), ('DIMBLK', '.'), ('DIMLDRBLK', '.')]
        if self.dim_units == 'arch':
            v += [('DIMLUNIT', 4), ('DIMDEC', self.dim_dec), ('DIMFRAC', 2), ('DIMZIN', 3)]
        else:
            v += [('DIMLUNIT', 2), ('DIMDEC', self.dim_dec), ('DIMZIN', 8)]
        d = dict(v); d.update(self.extra_dimvars)
        return [(k, float(x) if isinstance(x, float) else x) for k, x in d.items()]

    def records(self):
        out = [('LAYER', n, c, lw, lt) for n, (c, lw, lt) in self.layers.items()]
        out.append(('STYLE', self.style, self.text_font))
        out.append(('DIMSTYLE', self.dimstyle, self.dimvars()))
        return out + self.recs

    def report(self):
        L = [f'# {self.title}  ({self.command})', '', f'scale factor {self.scale:g}; units: inches', '']
        if self.prov:
            L.append('## Key values and provenance')
            for p in self.prov:
                v = p['value']; vs = f'{v:.4g}' if isinstance(v, float) else str(v)
                L.append(f"- [{p['src']}] {p['name']} = {vs}" + (f"  - {p['note']}" if p['note'] else ''))
            L.append('')
        if self.dim_checks:
            L.append('## Dimension check (model value vs source text)')
            bad = 0
            for c in self.dim_checks:
                shown = fmt_arch(c['value'], self.dim_dec) if self.dim_units == 'arch' else f"{c['value']:.{self.dim_dec}f}"
                if c['expect']:
                    ok = norm_dimtext(shown) == norm_dimtext(c['expect'])
                    bad += (not ok)
                    L.append(f"- {'OK ' if ok else 'MISMATCH'} model {c['value']:.3f} in -> shows {shown}; source says {c['expect']}")
                else:
                    L.append(f"- (no source text) model {c['value']:.3f} in -> shows {shown}")
            L.append(f'\nmismatches: {bad}\n')
        assumed = [p for p in self.prov if p['src'] == 'assumed']
        if assumed or self.notes:
            L.append('## Items for the user to confirm')
            for p in assumed:
                L.append(f"- {p['name']} = {p['value']}  ({p['note']})")
            for n in self.notes:
                L.append(f'- {n}')
        return '\n'.join(L)

    def emit(self, path):
        """Write <path>.lsp, <stem>.calib.json and <stem>.report.md next to it."""
        from emit_lsp import write_lsp
        os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
        write_lsp(self, path)
        stem = os.path.splitext(path)[0]
        if self.calib:
            json.dump(self.calib, open(stem + '.calib.json', 'w'), indent=1)
        open(stem + '.report.md', 'w', encoding='utf-8').write(self.report())
        return path


def _p(p):
    return (float(p[0]), float(p[1]))

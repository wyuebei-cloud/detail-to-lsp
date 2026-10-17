"""Test case 1 - CATCH BASIN GUTTER PAN, plan view, from a raster screenshot.

Source: WSDOT Standard Plan F-10.16-00 (crop of the detail).
Origin: back of curb at the left end of the left transition panel. +X along curb, gutter toward -Y.
Calibration: 7.958 px per inch, origin at pixel (23, 180) - from the 13'-0 1/4" and 2'-10 1/2" dims.
"""
import os, sys, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'scripts'))
from detail_model import *

d = Detail('Catch basin gutter pan - plan view', 'UB-CBGP', scale=16)
d.layer('DTL-GEOM-FRAME', 7, 50)
d.layer('DTL-GEOM-GRATE', 7, 18)

# ---------------------------------------------------------------- key values
R    = d.param('R', 60.0, 'dim', "5'-0\" R. callouts (4x)")
WCG  = d.param('W curb&gutter', 18.0, 'dim', "1'-6\"")
WCB  = d.param('W gutter pan box', 34.5, 'dim', "2'-10 1/2\"")
JNT  = d.param('joint', 0.375, 'dim', '3/8" premolded joint filler')
WBOX = d.param('box length', 34.0, 'dim', '5" + 24" frame + 5"')
TH   = d.param('theta', math.acos(1 - (WCB - WCG) / (2 * R)), 'derived', 'reverse curve, horizontal tangents both ends')
L    = d.param('panel length', 2 * R * math.sin(TH), 'derived', 'matches source text approx 5\'-0 3/4"')
EDGE = d.param('tooled edge offset', 0.5, 'measured', 'dotted lines 0.5" inside edges')
ROWS = d.param('curb dotted rows', [0.5, 4.625, 5.5, 6.375, 7.25], 'measured', 'curb top/face lines; meaning not legible')
STUB = d.param('adjacent curb stub', 24.0, 'assumed', 'screenshot cropped; 24" shown each side')
d.param('frame', (24.0, 20.0), 'measured', 'width 24" ties to the 5" dims; height scaled')
d.param('warp outline', (26.0, 22.0), 'measured', 'depression outline around frame')
d.param('grate vanes', '8 columns, 1.125" bars, breaks every 5" offset 2"', 'measured', 'schematic pattern')

xL0, xL1 = 0.0, L
xB0, xB1 = L + JNT, L + JNT + WBOX
xR0, xR1 = xB1 + JNT, xB1 + JNT + L
xS = xR1 + JNT
xm = (xB0 + xB1) / 2

# ---------------------------------------------------------------- transition panels (true arcs)
def rev_curve(off=0.0):
    """Bottom edge of left panel from (0,-WCG) to (L,-WCB); off>0 shifts into the concrete."""
    c1 = (0.0, -WCG - R); c2 = (L, -WCB + R)
    a = math.pi / 2 - TH
    p0 = (0.0, -WCG + off)
    pm = (c1[0] + (R + off) * math.cos(a), c1[1] + (R + off) * math.sin(a))
    p1 = (L, -WCB + off)
    return Path(p0).arc_to(pm, center=c1, ccw=False).arc_to(p1, center=c2, ccw=True)

outline = Path((xL1, 0.0)).line_to((xL0, 0.0)).line_to((xL0, -WCG)).extend(rev_curve())
d.pline(outline, closed=True)
d.pline(mirror_verts(outline.verts(), xm=xm), closed=True)
for x0, x1 in ((xL0, xL1), (xR0, xR1)):
    for r in ROWS:
        d.line((x0, -r), (x1, -r), 'DTL-GEOM-DOT')
edge = rev_curve(EDGE).verts()
d.pline(edge, 'DTL-GEOM-DOT', plinegen=True)
d.pline(reverse_verts(mirror_verts(edge, xm=xm)), 'DTL-GEOM-DOT', plinegen=True)

# ---------------------------------------------------------------- center box
d.rect(xB0, 0.0, xB1, -WCB)
for r in ROWS + [WCB - EDGE]:
    d.line((xB0, -r), (xB1, -r), 'DTL-GEOM-DOT')
wx0, wx1, wy0, wy1 = xB0 + 4, xB1 - 4, -8.5, -30.5
d.rect(wx0, wy0, wx1, wy1)
d.line((xB0, -7.25), (wx0, wy0)); d.line((xB1, -7.25), (wx1, wy0))
d.line((xB0, EDGE - WCB), (wx0, wy1)); d.line((xB1, EDGE - WCB), (wx1, wy1))
fx0, fx1, fy0, fy1 = xB0 + 5, xB1 - 5, -9.5, -29.5
d.rect(fx0, fy0, fx1, fy1, 'DTL-GEOM-FRAME')

gx0, gx1, gy0, gy1 = fx0 + 1.125, fx1 - 1.125, fy0 - 1.0, fy1 + 1.0
P, BW, BRK, TAP = (gx1 - gx0) / 8, 1.125, 0.75, 0.125
for i in range(8):
    xl, xr = gx0 + i * P, gx0 + (i + 1) * P
    brks = [4.5, 9.5, 14.5] if i % 2 == 0 else [2.5, 7.5, 12.5]
    ys = [0.0] + [v for b in brks for v in (b, b + BRK)] + [gy0 - gy1]
    for k in range(0, len(ys), 2):
        d.rect(xl, gy0 - ys[k], xl + BW, gy0 - ys[k + 1], 'DTL-GEOM-GRATE')
    f = BW / P
    for b in brks:
        yt, yb = gy0 - b, gy0 - b - BRK
        d.line((xl + BW, yt - TAP * f), (xr, yt - TAP), 'DTL-GEOM-GRATE')
        d.line((xl + BW, yb + TAP * f), (xr, yb + TAP), 'DTL-GEOM-GRATE')
    d.line((xl + BW, gy0), (xr, gy0), 'DTL-GEOM-GRATE')
    d.line((xl + BW, gy1), (xr, gy1), 'DTL-GEOM-GRATE')

# ---------------------------------------------------------------- adjacent curb & gutter stubs
d.pline([(-JNT - STUB, 0), (-JNT, 0), (-JNT, -WCG), (-JNT - STUB, -WCG)])
d.pline([(xS + STUB, 0), (xS, 0), (xS, -WCG), (xS + STUB, -WCG)])
for x0, x1 in ((-JNT - STUB, -JNT), (xS, xS + STUB)):
    for r in ROWS + [WCG - EDGE]:
        d.line((x0, -r), (x1, -r), 'DTL-GEOM-DOT')

# ---------------------------------------------------------------- dimensions
d.dim((xL0, 0), (xR1, 0), (xm, 14.85), override=APPROX, expect='13\'-0 1/4"')
d.dim((xL0, 0), (xL1, 0), (L / 2, 9.93), override=APPROX, expect='5\'-0 3/4"')
d.dim((xR0, 0), (xR1, 0), (xR0 + L / 2, 9.93), override=APPROX, expect='5\'-0 3/4"')
d.dim((xR0, 0), (xR0, -WCB), (xR0 + 8.05, -WCB / 2), rot=90, oblique=30, expect='2\'-10 1/2"')
d.dim((xS, 0), (xS, -WCG), (xS + 7.66, -WCG / 2), rot=90, oblique=30, expect='1\'-6"')
d.dim((xB0, -WCB), (fx0, fy1), (xB0 + 2.5, -42.1), expect='5"')
d.dim((fx1, fy1), (xB1, -WCB), (xB1 - 2.5, -42.1), expect='5"')

# ---------------------------------------------------------------- text, leaders, symbols
T = [('3/8" PREMOLDED JOINT FILLER', (30.28, 6.95), 'note', 'MC'),
     ("5' - 0\" R.", (11.06, -26.33), 'note', 'MR'), ("5' - 0\" R.", (40.34, -38.88), 'note', 'MR'),
     ("5' - 0\" R.", (145.0, -26.33), 'note', 'ML'), ("5' - 0\" R.", (116.0, -38.88), 'note', 'ML'),
     ('GUTTER PAN', (60.8, -51.6), 'note', 'MR'),
     ('~', (49.6, -21.8), 'note', 'MC'), ('~', (72.7, -32.8), 'note', 'MC'),
     ('PLAN VIEW', (78.16, -54.4), 'label', 'MC'),
     ('CATCH BASIN GUTTER PAN', (78.16, -62.08), 'title', 'MC')]
for s, p, sz, j in T:
    d.text(s, p, sz, j)
d.text_lines(['RECTANGULAR FRAME AND GRATE ~ NOT', 'INCLUDED IN CURB AND GUTTER BID ITEM'], (94.5, -48.19), spacing=1.49)
d.text_lines(['CEMENT CONCRETE', 'CURB AND GUTTER'], (162.48, -32.11), spacing=1.49)

d.leader([(-0.19, -2.10), (3.0, -1.9), (6.0, -0.2), (6.3, 1.8), (5.1, 4.6), (7.3, 6.6), (10.2, 6.95), (12.2, 6.95)], spline=True)
d.leader([(60.92, -2.10), (57.7, -1.9), (54.7, -0.2), (54.4, 1.8), (55.6, 4.6), (53.4, 6.6), (50.5, 6.95), (48.4, 6.95)], spline=True)
d.leader([(15.75, -20.10), (14.07, -26.33), (12.5, -26.33)])
d.leader([(44.48, -32.26), (42.92, -38.88), (41.47, -38.88)])
d.leader([(140.74, -20.03), (142.15, -26.33), (143.82, -26.33)])
d.leader([(111.46, -32.33), (112.78, -38.88), (114.13, -38.88)])
d.leader([(50.39, -22.87), (63.2, -51.4), (61.2, -51.4)], arrow=False)
d.leader([(72.5, -32.67), (63.2, -51.4)], arrow=False)
d.leader([(82.4, -29.5), (91.57, -49.39), (93.17, -49.39)])
d.leader([(152.4, -18.12), (159.42, -33.3), (160.88, -33.3)])
d.leader([(166.97, -18.0), (159.42, -33.3)])

for lbl, c in (('A', (78.84, -41.92)), ('B', (129.05, -32.12))):
    d.section_marker(lbl, c)
    d.flag((c[0], 2.15))

d.note('NOTES block at the right edge of the screenshot is cut off and was not reproduced.')
d.note('Flags above the section cuts reproduced as drawn; their meaning is not stated in the crop.')

d.calibrate_image(os.path.join(HERE, 'source.png'), origin_px=(23, 180), px_per_in=7.958)

if __name__ == '__main__':
    out = os.path.join(HERE, 'out', 'UB-CBGP.lsp')
    d.emit(out)
    print('wrote', out)

"""Test case 2 - WSDOT 10.2-A6-1b TYPICAL SECTION, TRAFFIC BARRIER (vector PDF).

Origin: curb line at top of roadway, +X toward roadway, +Y up.
Calibration: 3.0 pt per inch (10", 8", 1'-1", 1'-6", 3'-6" agree), origin at (867.6, 584.15) pt.
Sheet is a half-size 11x17 of a 1"=1'-0" detail, so annotation scale = 12 and 0.1" text.
"""
import os, sys, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'scripts'))
from detail_model import *
from pdf_extract import extract, text_lines, to_model

PDF = os.path.join(HERE, 'source.pdf')
BBOX = (697, 409, 1016, 700)
ORIGIN = (867.6, 584.15)
K = 3.0

d = Detail('Typical section - traffic barrier (single slope 42 TL5)', 'UB-TBSEC', scale=12,
           text_heights={'note': 0.1, 'title': 0.2}, dim_dec=4)
d.layer('DTL-GEOM-REBAR', 1, 35)
d.layer('DTL-GEOM-CONDUIT', 3, 25)
d.param('scale', K, 'vector', '3 pt per model inch; 10", 8", 1\'-1", 1\'-6", 3\'-6" all agree')
d.param('origin', ORIGIN, 'vector', 'curb line at top of roadway')

# ---------------------------------------------------------------- concrete (from 0.84 pt strokes)
BARRIER = [(0, 0), (-8, 41), (-8.875, 41.75), (-17.25, 42), (-18, 41.25),
           (-18, -5.75), (-17.25, -6.5), (-13.75, -6.875), (-13, -6.25)]
DECK = [(0, 0), (18.25, 0), (18.25, -4.5), (19.0, -4.875), (17.5, -5.5), (18.25, -6.0),
        (18.25, -10.375), (5.75, -9.0), (5.0, -8.125), (4.125, -8.875),
        (-12.25, -7.0625), (-13, -6.25), (-13, 0)]
d.pline(BARRIER)
d.pline(DECK)
d.line((18.25, 0), (18.25, 1.5)); d.line((18.25, -10.375), (18.25, -11.875))
# roughened construction joint: 34 alternating semicircles between x = -12.73 and 0 (0.48 pt strokes)
x0j, n = (829.4 - ORIGIN[0]) / K, 34
c = -x0j / n
d.pline([(x0j + i * c, 0.0, (1.0 if i % 2 == 0 else -1.0) if i < n else 0.0) for i in range(n + 1)])

# ---------------------------------------------------------------- rebar (0.6 pt strokes, outlines -> centrelines)
d.param('bend radii', '#6 2.25", #5 1.875" (centreline)', 'vector', 'circle fits of the bar outlines')
BARS = [
    (0.75,  [(10.53, -5.62), (-1.89, -5.62), (-5.38, 12.61), (-16.6, 12.61)], 2.25),     # S1 #6
    (0.625, [(-5.07, 11.38), (-10.53, 40.03), (-16.95, 40.03)], 1.875),                 # R2 #5
    (0.625, [(-13.33, 12.93), (-9.79, -5.69), (1.93, -5.69)], 1.875),                   # S2 #5
    (0.625, [(-16.03, 5.5), (-16.03, 1.815), (-3.68, 1.815), (-4.115, 4.1)], 1.75),    # unmarked U bar
    (0.5,   [(-16.25, -5.5), (-16.25, 40.83)], 0.0),                                    # R6 #4
]
for dia, pts, r in BARS:
    d.bar(pts, dia, r, 'DTL-GEOM-REBAR')
DOTS = [(-15.4, 39.16, 0.75), (-11.6, 38.93, 0.75),
        (-15.63, 31.23, .625), (-9.53, 31.23, .625), (-8.03, 23.33, .625),
        (-15.63, 23.33, .625), (-6.53, 15.43, .625), (-15.6, 15.4, .625),
        (-12.37, 11.83, .625), (-5.27, 2.66, .625), (-14.53, 2.66, .625),
        (-15.6, -4.97, .625), (-8.57, -4.80, 0.75), (-0.07, -4.80, 0.75)]
for x, y, dia in DOTS:
    d.dot((x, y), dia, 'DTL-GEOM-REBAR')
for x, y, r in [(-14.18, 16.6, 1.1875), (-14.2, 14.2, 1.1875)]:
    d.circle((x, y), r, 'DTL-GEOM-CONDUIT')

# ---------------------------------------------------------------- tags
for x, y, r in [(-15.4, 39.16, 1.35), (-11.6, 38.93, 1.35), (-8.57, -4.80, 1.35), (-0.07, -4.80, 1.35), (5.0, -8.45, 1.4)]:
    d.circle((x, y), r, d.text_layer)
for x1, y1, x2, y2, t in [(-51.97, 51.86, -46.9, 53.96, 'R4'), (-35.53, 31.5, -30.5, 33.6, 'R6'),
                          (-2.37, 34.46, 2.67, 36.56, 'R2'), (-50.57, 26.0, -45.53, 28.1, 'R3'),
                          (-32.07, -19.1, -26.93, -17.0, 'S2'), (21.13, -11.2, 26.23, -9.1, 'S1')]:
    d.box_label(x1, y1, x2, y2, t)
d.hex_label((-29.2, 38.6), '5'); d.hex_label((21.45, 49.9), '5'); d.hex_label((14.9, 21.1), '4', vertical=True)

# ---------------------------------------------------------------- text from the PDF text layer
ex = extract(PDF, 0, BBOX)
SKIP = {'R4', 'R6', 'R2', 'R3', 'S1', 'S2', '5', '10"', '8"', "1'-1\"", "1'-6\""}   # boxes, hexes, dims
FIX = {'SPICE(': 'SPLICE ('}                          # source typo
NOTE_PT, TITLE_PT = 5.04, 10.08                       # font sizes used on this sheet
for L in text_lines(ex['words']):
    if min(abs(L['size'] - NOTE_PT), abs(L['size'] - TITLE_PT)) > 0.3:
        continue                                      # stacked-fraction digits and dim-text glyphs
    words = [w['text'] for w in L['words'] if w['text'] not in SKIP]
    if not words or 'CHAMFER' in words:               # chamfer note rebuilt below (stacked fractions)
        continue
    s = ' '.join(words)
    for a, b in FIX.items():
        s = s.replace(a, b)
    s = ''.join('(E)' if 0xE000 <= ord(ch) <= 0xF8FF else ch for ch in s)   # epoxy symbol glyph
    kept = [w for w in L['words'] if w['text'] not in SKIP]
    after_tag = L['words'][0]['text'] in SKIP          # text that follows a bar-mark box: anchor left
    x0, _ = to_model((kept[0]['x0'], L['mid']), ORIGIN, K); x1, y = to_model((L['x1'], L['mid']), ORIGIN, K)
    if L['size'] > 8:                                   # view title, underlined
        d.text('%%u' + s, ((x0 + x1) / 2, y), 'title', 'MC')
    elif s.startswith('SHOWN ON'):
        d.text(s, ((x0 + x1) / 2, y), 'note', 'MC')
    elif x1 < -1.0 and not after_tag:                   # left of barrier: leaders attach at the right end
        d.text(s, (x1, y), 'note', 'MR')
    else:
        d.text(s, (x0, y), 'note', 'ML')
d.text('3/4" CHAMFER OR 1/2" HALF', to_model((899.9, 631.4), ORIGIN, K), 'note', 'ML')
d.note('Source text "SPICE(TYP.)" corrected to "SPLICE (TYP.)".')
d.note('Epoxy-coated triangle symbol written as "(E)"; stacked fractions written inline.')

# ---------------------------------------------------------------- leaders (first point = arrow end)
LEADERS = [
    ([(-15.4, 39.16), (-26.2, 49.95)], False),
    ([(-11.6, 38.93), (-10.44, 47.37), (-26.2, 49.95)], False),
    ([(0, 49.9), (4.9, 49.9)], True),
    ([(-18.0, 34.8), (-25.0, 38.6), (-26.2, 38.6)], True),
    ([(-16.5, 29.4), (-30.3, 32.4)], True),
    ([(-8.81, 32.7), (-3.4, 35.51), (-2.37, 35.51)], True),
    ([(-15.95, 23.33), (-25.6, 24.1)], True),
    ([(-15.36, 16.75), (-25.3, 18.1)], True),
    ([(-15.36, 14.45), (-25.3, 18.1)], True),
    ([(-6.6, 0.25), (-8.7, 7.17), (-26.3, 7.17)], True),
    ([(-13.0, -4.3), (-28.0, 0.2)], True),
    ([(-0.07, -4.8), (20.2, -0.9)], False),
    ([(-8.57, -4.8), (-5.94, -2.19), (20.2, -0.9)], False),
    ([(-15.6, -6.72), (-24.0, -12.3)], True),
    ([(-6.2, -6.05), (-18.8, -18.05)], True),
    ([(10.45, -6.1), (18.6, -10.15), (21.13, -10.15)], True),
    ([(5.65, -9.6), (9.4, -15.6), (10.3, -15.6)], False),
]
for pts, arr in LEADERS:
    d.leader(pts, arrow=arr)

# ---------------------------------------------------------------- dimensions
d.dim((-18, 41.25), (-8, 41), (-13, 54), expect='10"')
d.dim((-8, 41), (0, 0), (-4, 54), expect='8"')
d.dim((-8.875, 41.75), (-8.875, 42.0), (-1.6, 41.9), rot=90, override='1/4"')
d.dim((0, 0), (-8.875, 42.0), (12.35, 21), rot=90, expect='3\'-6"')
d.dim((-13, -6.25), (0, 0), (-6.5, -14.0), expect='1\'-1"')
d.dim((-13, -6.25), (5.0, -8.125), (-4, -18.3), expect='1\'-6"')
d.dim((-7.954, 27.72), (-5.50, 28.2), (-6.727, 27.96), kind='ALI', override='2 1/2" CLR.')

d.calibrate_pdf(PDF, 0, BBOX, ORIGIN, K, dpi=300)

if __name__ == '__main__':
    out = os.path.join(HERE, 'out', 'UB-TBSEC.lsp')
    d.emit(out)
    print('wrote', out)

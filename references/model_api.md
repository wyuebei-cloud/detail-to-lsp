# Model API (scripts/detail_model.py)

All coordinates are model inches, Y up, relative to the chosen origin. Angles in
degrees unless noted. Points are `(x, y)`; polyline vertices may be `(x, y, bulge)`.

## Detail

```python
Detail(title, command, scale=16.0, text_font='arialbd.ttf',
       text_heights={'note': 0.1, 'label': 0.13, 'title': 0.15},   # plotted inches
       dim_text=0.1, arrow=0.1, dim_dec=2, dim_units='arch',
       text_layer='DTL-TEXT', dim_layer='DTL-DIM', style='DTL-ARIAL', dimstyle='DTL-DIM')
```
- `scale`: annotation scale factor (12 = 1"=1'-0", 16 = 3/4"=1'-0", 24 = 1/2"=1'-0").
  Model text height = plotted height x scale. Infer it: source cap height (model in)
  / scale should land on a standard plotted size (0.08-0.125" notes).
- `dim_dec`: architectural precision (2 = 1/4", 3 = 1/8", 4 = 1/16").
- `dim_units='dec'` switches to decimal units.
- `d.extra_dimvars = {'DIMTAD': 0}` overrides any dimension variable.

### Layers
Predefined: `DTL-GEOM` (7, 0.35), `DTL-GEOM-THIN` (8, 0.18), `DTL-GEOM-DOT` (8, 0.13, DOT),
`DTL-GEOM-HIDDEN` (8, 0.18, HIDDEN), `DTL-GEOM-CENTER` (8, 0.13, CENTER), `DTL-HATCH` (8, 0.09), `DTL-TEXT` (2, 0.25),
`DTL-DIM` (4, 0.18). `d.layer(name, color, lw_hundredths_mm, ltype)` adds/overrides one.
Only layers that receive entities are emitted.

### Bookkeeping
- `d.param(name, value, src, note='')` -> value. src: `dim`, `derived`, `vector`,
  `measured`, `standard`, `assumed`.
- `d.note(text)` - item listed under "Items for the user to confirm".

### Geometry
| call | result |
|---|---|
| `d.line(p1, p2, layer)` | LINE |
| `d.pline(pts_or_Path, layer, closed=False, plinegen=False, width=None)` | LWPOLYLINE (bulges = true arcs). `plinegen=True` for dotted curves |
| `d.rect(x0, y0, x1, y1, layer)` | closed LWPOLYLINE |
| `d.circle(c, r, layer)` / `d.arc(c, r, a0, a1, layer)` | CIRCLE / ARC (CCW a0->a1) |
| `d.dot(c, dia, layer)` | filled dot (donut polyline) - bar cross-sections |
| `d.bar(center_pts, dia, bend_r, layer)` | closed double-line bar with true-arc bends |
| `d.solid(p1, p2, p3, p4=None, layer)` | SOLID; give corners in perimeter order |
| `d.fill_convex(pts, layer)` | convex fill from SOLID triangles |
| `d.hatch(loops, pattern='ANSI31', scale=1, angle=0, layer='DTL-HATCH')` | HATCH (acad.pat name or `SOLID`), non-associative. `loops` = one boundary or a list (first outer, rest islands); points, `(x,y,bulge)` verts or `Path`. Give each material its own `DTL-HATCH-*` layer |

### Annotation
| call | notes |
|---|---|
| `d.text(s, p, size='note', just='ML', rot=0, layer=None, height=None)` | just: L C R M BL BC BR ML MC MR TL TC TR. `%%u` underline, `%%c` dia, non-ASCII -> `\U+XXXX` automatically |
| `d.text_lines(lines, p, size, just, spacing=1.5)` | stacked lines; spacing x cap height (measure it: 1.49 in the gutter-pan case) |
| `d.leader(pts, arrow=True, spline=False)` | first point = arrowhead end; no annotation attached |
| `d.dim(p1, p2, dl, rot=0, override=None, oblique=None, kind='ROT', expect=None)` | real DIMENSION. `rot` 0/90; `kind='ALI'` aligned; `override` text, `<>` = measured value; `APPROX` = "approx <>" prefix; `oblique` ext-line angle (deg); `expect` = text on the source for the report check |
| `d.section_marker(label, c, r=3, tip=5, half=4, tick=1.6, ang=0)` | circle + filled pointer + cut tick |
| `d.flag(base, height=3, w=4.7, drop=1.55)` | pole + pennant |
| `d.box_label(x0, y0, x1, y1, s)` / `d.hex_label(c, s, w=6, h=3, vertical=False)` | bar-mark box, key-note hexagon |

### Source registration (overlay)
- `d.calibrate_image(path, origin_px=(u, v), px_per_in=s, py_per_in=None)`
- `d.calibrate_pdf(path, page, bbox_pt=(x0, top, x1, bottom), origin_pt=(x, top), pt_per_in=k, dpi=300)`

### Output
`d.emit('out/UB-NAME.lsp')` writes the .lsp (ASCII, CRLF), `UB-NAME.calib.json`,
`UB-NAME.report.md`.

## Geometry helpers
- `Path(start).line_to(p).arc_to(p, center=c, ccw=True | bulge=b).arc_center(c, sweep_deg).extend(path)`; `.verts()`
- `fillet_path(corner_pts, radius_or_list, closed=False)` -> verts with tangent arcs
- `offset_verts(verts, d, closed=False)` (+d = left of travel; arcs exact, line corners mitred)
- `reverse_verts(verts)`, `mirror_verts(verts, xm=..|ym=..)` (bulges handled)
- `bulge_from_center(p0, p1, c, ccw)`, `arc_from_bulge(p0, p1, b)`, `sample_verts(verts, closed)`
- `fit_circle(points)` -> (cx, cy, r, rms); `line_x(p1, p2, p3, p4)`; `polar`, `dist`, `lerp`
- `ftin("5'-0 3/4\"")` -> 60.75; `fmt_arch(60.727, dec=2)` -> `5'-0 3/4"`

## Record formats (what the runtime consumes)
See the header of `scripts/lsp_runtime.lsp`. The emitter writes one record per line in
`(defun dtl:data-<CMD> () '( ... ))`; the runtime is identical in every file.

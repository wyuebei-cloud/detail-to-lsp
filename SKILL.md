---
name: detail-to-lsp
description: Rebuild an engineering/CAD detail shown in a PDF (vector or scanned) or a screenshot as an AutoLISP script that draws it in AutoCAD/Civil 3D - geometry, text, leaders, symbols and real dimensions on separate layers. Use whenever the user wants a detail "redrawn", "rebuilt", "traced" or "turned into LISP/LSP/CAD" from a PDF, sheet, standard plan or image.
---

# detail-to-lsp

Turn a detail on a PDF sheet or screenshot into a single `.lsp` file that draws it
at 1:1 in model space (inches). The method is: **one Python model -> generated data
-> fixed, pre-verified LISP runtime**, checked by executing the script in a LISP
simulator and overlaying what it would draw onto the source.

```
source --probe--> extract/measure --calibrate--> model.py (Detail API)
   --> emit .lsp + report --> check_lsp (parens, lint, simulate) --> overlay + coverage
   --> fix model.py --> repeat --> deliver
```

Everything lives in `scripts/` (Python 3.9+, needs numpy, Pillow, scipy; pdfplumber +
pypdfium2 for PDFs). Run scripts with `python <skill>/scripts/<tool>.py -h` for usage.

## Standing defaults (do not ask about these)

- Draw everything visible in the detail: geometry, text, leaders, symbols, dimensions.
- Layers by category: `DTL-GEOM*` (geometry; sub-layers allowed: `-DOT`, `-HIDDEN`,
  `-REBAR`, ...), `DTL-TEXT` (text, leaders, tags, symbols), `DTL-DIM` (dimensions).
  The user renames layers later; separation is what matters.
- Dotted/dashed lines are single entities on a layer with a real linetype (DOT, HIDDEN...);
  never chains of short segments. Linetype scale is left to the user.
- Arcs with a known/derivable radius are true arcs (polyline bulges, ARC, CIRCLE).
  Approximate with segments only for free-form curves.
- Units inches; command prefix `UB-`; pure-ASCII file; code and comments in English.
- No parametric LISP: to change the drawing, edit `model.py` and regenerate.

Ask before starting only about things that change the output and cannot be inferred:
which detail if the sheet has several, the insertion origin if no physical point is
obvious, and any symbol/text the user may want handled differently. List them together.

## Phase 0 - Triage

```
python scripts/probe.py source.pdf --render page.png      # VECTOR / RASTER / MIXED per page
python scripts/probe.py screenshot.png
```
Look at the render, locate the detail, note its bbox. A VECTOR page takes the
vector route; RASTER and screenshots take the raster route. Read
`references/vector_pdf.md` or `references/raster.md` before Phase 1.

## Phase 1 - Extract and calibrate

**Vector:** `pdf_extract.py sheet.pdf --bbox x0,top,x1,bottom --render crop.png --arcs --json ext.json`.
Stroke classes (width/colour/dash) usually separate concrete, rebar, annotation and
hidden lines. Words come with positions and font sizes; text that is drawn as glyph
outlines (filled 0.24 paths) is not extractable - read it from the render.

**Raster:** `raster_measure.py` (`row`, `col`, `bbox`, `lines`, `dots`, `edge`, `fitarc`,
`zoom`). Measure with numbers; zoom images are for reading, not for coordinates.

**Calibrate** with `calibrate.py`: at least two independent dimensions per axis.
Residuals must be within measuring precision and x/y ratio ~1.000; otherwise stop and
find out why (misread dimension, non-uniform scaling, wrong extension-line origin).
Pick a physical origin (curb line at top of roadway, back of curb at a joint ...).

## Phase 2 - Reconstruct design intent

Before writing coordinates, ask what the designer drew. Derive values from callouts and
geometry: e.g. two R=5'-0" reverse curves with horizontal tangents and a 16.5" offset
give a 60.727" panel - which is exactly the "approx 5'-0 3/4"" on the sheet. Snap to
standard sizes (bar diameters, bend radii, chamfers) when the evidence supports it.
Record every key value with `d.param(name, value, src, note)`, src in
`dim | derived | vector | measured | standard | assumed`. `assumed` items are reported
to the user. Wrong snapping produces systematic error that the overlay cannot reveal -
the dimension check (Phase 4) is the guard.

## Phase 3 - Write model.py

Copy `templates/model_template.py` next to the source (`work/<detail>/model.py`) and point its `SKILL` path (or the `DETAIL_TO_LSP` env var) at this skill folder. API in
`references/model_api.md`; the two cases in `tests/` are complete worked examples
(raster: `tests/gutter_pan`, vector: `tests/traffic_barrier`). Key calls:

```python
d = Detail('Title', 'UB-NAME', scale=16)            # scale = annotation scale factor
d.layer('DTL-GEOM-REBAR', 1, 35)                     # optional extra geometry layers
d.pline(Path(p0).line_to(p1).arc_to(p2, center=c, ccw=False), closed=True)
d.line(a, b, 'DTL-GEOM-DOT'); d.circle(c, r); d.bar(pts, dia, bend_r); d.dot(c, dia)
d.text('PLAN VIEW', p, 'label', 'MC'); d.text_lines([...], p)
d.leader([arrow_pt, knee, shoulder]); d.leader(pts, spline=True)
d.dim(p1, p2, dimline_pt, rot=90, oblique=30, override=APPROX, expect='2\'-10 1/2"')
d.section_marker('A', c); d.hex_label(c, '5'); d.box_label(x0, y0, x1, y1, 'R4')
d.calibrate_image('src.png', origin_px=(u, v), px_per_in=s)   # or calibrate_pdf(...)
d.emit('out/UB-NAME.lsp')
```

Text: choose justification by where the leader attaches (MR when the leader leaves the
right end, ML for the left end, MC for titles/tags) so that font-width differences do
not detach text from its leader. Text height = cap height (AutoCAD TrueType rule).
Pass `expect=` for every dimension whose text is legible.

## Phase 4 - Gate and verify (repeat until clean)

```
python model.py
python scripts/check_lsp.py out/UB-NAME.lsp --run C:UB-NAME            # must print RESULT: PASS
python scripts/overlay.py out/UB-NAME.lsp --out out/check --tiles 3x2 [--roi=..] [--ignore=..] [--crop=..]
```
(Boxes with negative numbers need the `=` form: `--roi=-60,-36,50,58`.)

- `check_lsp` = paren balance with per-line depth on failure, lint, then the whole file
  is executed in `lisp_sim.py` (AutoLISP subset + AutoCAD stub). Every `entmake` is
  validated against DXF group-code rules; unknown functions, arity errors, missing
  styles/linetypes and bad setvar calls fail the gate.
- `overlay.png` draws the **simulated entities**, so it shows the script itself.
  Inspect every junction of two members, every leader end and every dimension.
- `coverage.txt`: the "OUTSIDE TEXT ZONES" numbers are the geometry signal; drive
  unclaimed source ink toward 0 and explain each remaining blob (cropped source,
  font, notes outside scope). Text inside zones differs mainly by font - judge by eye.
- `<stem>.report.md`: provenance + dimension check. Any MISMATCH means the model or the
  calibration is wrong - fix before delivery.

Done when: gate PASS, 0 dimension mismatches (or each explained), coverage blobs
explained, crops reviewed.

## Phase 5 - Deliver

Send the `.lsp` and `out/check/overlay.png`. Reply briefly: command name and insertion
point, layers, how key values were obtained (one line on derivation/calibration),
the items from "Items for the user to confirm", and that the script was verified in a
simulator, not in AutoCAD. Note `references/autocad_notes.md` "not verifiable" items
if the user hits an error. Keep `model.py` so changes are a regenerate away.

## Files

- `scripts/detail_model.py` - Detail API, geometry helpers (Path, fillet_path,
  offset_verts, mirror/reverse, fit_circle), ftin()/fmt_arch() unit helpers, report.
- `scripts/emit_lsp.py` + `scripts/lsp_runtime.lsp` - generator and the fixed runtime.
- `scripts/lisp_sim.py`, `scripts/check_lsp.py` - simulator and delivery gate.
- `scripts/overlay.py` - overlay, zoom tiles/crops, coverage map.
- `scripts/probe.py`, `pdf_extract.py`, `raster_measure.py`, `calibrate.py` - intake tools.
- `references/` - model API, vector and raster playbooks, AutoCAD notes.
- `tests/run_tests.py` - regenerates both reference cases and checks the gates.
- `assets/fonts/` - Liberation Sans (Arial-metric, SIL OFL) for text previews.

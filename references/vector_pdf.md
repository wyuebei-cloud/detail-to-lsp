# Vector PDF playbook

Worked example: `tests/traffic_barrier` (WSDOT 10.2-A6-1b, MicroStation export).

## 1. Confirm it is vector
`probe.py` shows thousands of lines/curves and extractable chars -> vector. A scanned PDF
shows one large image and almost no paths -> use the raster playbook on its render.
Quick user-side test: in Bluebeam a single line can be selected, or text can be copied.

## 2. Isolate the detail
Render the page (`probe.py --render page.png --dpi 100`; pt = px x 72/dpi), find the
detail, take a bbox in pt (pdfplumber "top" coordinates, y down). Include the title.
Sheet border lines often cross the bbox; exclude them with `--roi` in the overlay.

## 3. Read the stroke classes
`pdf_extract.py --bbox ... --arcs` prints width x colour x dash classes with extents.
Typical CAD plot styles: heavy (0.8+ pt) outline/concrete, medium (0.5-0.6) rebar or
secondary objects, light (0.24) annotation, dims, hatch, text glyphs. Dashed classes
carry their dash array. Classify by class first, then by location.

Glyph outlines: some fonts are exported as filled paths (the "fill, 0.24" class with
hundreds of small paths). They are text, not geometry; read them from the render.

## 4. Scale and origin
Scale = pt per model inch. Pick 3+ dimensions, measure their extension-line distance in
pt from the vectors and run `calibrate.py`. Half-size (11x17) standard plans of 1"=1'-0"
details give 3 pt per inch. Origin: a physical point (curb line at top of roadway,
work point, centreline). `to_model((x, top), origin_pt, k)` converts (Y flips up).

## 5. Geometry from paths
- Polylines: take vertices directly; round to the drawing's evident precision (1/16"
  or 1/8") only when the rounding error is far below the stroke width.
- Arcs: `path_arcs()` fits each Bezier segment and merges neighbours with a shared
  centre. Coordinates in many PDFs are quantised to 0.1 pt, so tiny arcs fit noisily -
  prefer snapping radii to standards (bend diameters, chamfers) and record `standard`.
- Double-line bars: outline radii r_out and r_in give centreline R = (r_out + r_in)/2 and
  bar diameter = r_out - r_in. Rebuild with `d.bar(centre_corners, dia, R)`.
- Small filled circles (0.6 fill) are bar cross-sections -> `d.dot`. Fit centre/radius.
- Repeated tiny arcs along a line (roughened joint, scallops) -> one polyline with
  alternating bulges +-1; take count and extent from the vectors.

## 6. Text from the text layer
`text_lines(words)` joins words that share a baseline. Then:
- keep only the note/title font sizes; drop stacked-fraction digits and dimension glyphs
  (they come out as stray 1-character "lines" at other sizes or rotated);
- remove words that belong to tags you draw separately (bar-mark boxes, hex key notes)
  and dimension values (the DIMENSION objects produce their own text);
- rebuild stacked fractions inline ("3/4\" CHAMFER");
- private-use code points (U+E000-F8FF) are custom symbols (epoxy triangle etc.):
  replace with plain text and `d.note()` it;
- vertical middle of a caps line = (top + bottom)/2 from pdfplumber;
- note obvious typos in the source; fix only with a `d.note()` so the user sees it.

Font size -> text height: cap height ~ 0.7 x font size (pt) / scale(pt per in). With
3 pt/in, 5.04 pt text = ~1.2" model = 0.1" plotted at 1"=1'-0" -> `scale=12`.

## 7. Expectations for the overlay
Geometry and leaders should sit on the source strokes (sub-pixel to 1 px at 300 dpi).
Text will not match glyph-for-glyph: MicroStation fonts are wider than Arial. Anchor
text at the leader end (MR / ML) so the attachment point is right.

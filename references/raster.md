# Raster playbook (screenshots, scanned PDFs)

Worked example: `tests/gutter_pan` (1532x687 screenshot, ~8 px per inch).

## Ground rules
- Coordinates come from pixel statistics (`raster_measure.py`), never from eyeballing a
  zoomed image. Zooms are for reading text and understanding topology.
- Every measuring window must be wider than the object: if `bbox` warns that ink touches
  the window edge, widen it. A clipped window silently returns a wrong extent
  (in the gutter-pan run this put the title 6" off until the overlay exposed it).
- Lines are 1-3 px wide and anti-aliased. Use run centres (`row`/`col` print them) or
  `edge` (intensity-weighted centre) for sub-pixel positions.
- Resolution sets the floor: at 8 px/in a single read is +-0.1-0.2". Details smaller than
  ~3 px (chamfers, bar spacing) must come from callouts or standards, not pixels.

## Calibration
1. Find dimensions with long extents in both axes (overall length, overall width).
2. Measure the extension-line distance (centre to centre) in px.
3. `calibrate.py PX=TEXT ... --axis x,x,y,y` -> px per inch, residuals, x/y ratio.
   Residuals should be < 1 px; x/y ratio 1.000 +- 0.3%. Larger means a misread value,
   a wrong extension line, or a non-uniformly scaled screenshot (ask for a new one).
4. Origin = pixel of a physical point (joint at back of curb, curb line ...).

Note: "approx" dimensions (e.g. "approx 13'-0 1/4\"") are derived values; use them to
check the model, not to calibrate, unless they agree with exact dimensions.

## Reconstruct, then compare
Raster input rewards deriving geometry from the drawing's own logic:
- callouts (R=5'-0", 3/8" joint, 5" each side, 2'-10 1/2") fix most values exactly;
- tangency, symmetry, repetition (mirror panels, grate pitch = opening / count);
- standard component sizes (frame 24" x 20", curb 18").
Measure only what cannot be derived (dotted line offsets, schematic patterns) and
record those as `measured`. The overlay cannot detect a wrong global scale because the
model and the check use the same pixels - the dimension text check (`expect=`) is the
independent test, so give it for every legible dimension.

## Dotted and faint lines
`raster_measure.py dots IMG y0 y1` maps which rows carry faint dotted ink in which
x-cells. Model them as single lines on `DTL-GEOM-DOT` (DOT linetype). Coverage treats
faint ink (gray < 235) as support, so dotted model lines do not count as spurious.

## Text
Read the text from a zoom; measure each line's extent with `lines` (rows) and
`bbox`/`lines --axis cols` (x range). Cap height in px / px-per-inch = model height;
divide by the scale factor to get the plotted height and choose `scale` so the plotted
height is standard (0.1" -> scale 16 in the gutter-pan case). Line spacing of stacked
notes: measure (1.49 x cap height there). Leader knees and shoulders: measure in a zoom
(`zoom --k 4` prints the px mapping) and convert.

## Typical residuals after a good model
Outside text zones: unclaimed source ink 5-8% (anti-aliasing fringes, cropped parts of
the sheet, title glyph differences), spurious model ink < 1%. Larger blobs listed in
coverage.txt with model coordinates point straight at what is missing or misplaced.

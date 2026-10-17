# AutoCAD / AutoLISP notes for the runtime

## What the generated file does
- `(vl-load-com)`, the runtime `dtl:*` functions, one data function, one `c:` command.
- Prompts for an insertion point (Enter = 0,0), converts UCS -> WCS, wraps everything in
  one undo mark, creates layers / text style / dimension style if missing, draws all
  records, restores CMDECHO and the previously current dimension style, then prints
  "N records OK, M failed" and any warnings (e.g. a linetype that could not be loaded).
- Loading several generated files is safe: the runtime is identical; each detail has
  its own `dtl:data-<CMD>` and `c:<CMD>`.

## Conventions the emitter guarantees
- Pure ASCII, CRLF. Non-ASCII text becomes `\U+XXXX` (written `\\U+XXXX` inside LISP
  strings so the backslash survives the reader).
- Real-valued group codes always get reals (`1.0`, not `1`) - integers in real codes
  have caused failures with bulge (42) before.
- LWPOLYLINE: `(100 . "AcDbPolyline")` before vertices; 90 = vertex count; one 42 per
  vertex; 70 bit 1 closed, bit 128 linetype generation (needed for dotted curves).
- TEXT with justification other than Left needs group 11; the runtime sets 10 and 11.
- SOLID vertex order is 1-2-4-3; `d.solid()` takes perimeter order and swaps.

## Sizes and units
- TrueType text height = height of capital letters.
- DIMZIN 3 with architectural units shows `5"` and `5'-0"`; DIMZIN 0 would print `5'`.
- DIMDEC for architectural units is the fraction precision (2 = 1/4", 4 = 1/16").
- DIMTAD 1 + DIMTIH/DIMTOH 0: text above the line and aligned with it (vertical dims read
  bottom-to-top on the left side).
- DIMATFIT 1 + DIMTIX 1 + DIMTOFL 1: text forced inside, arrows move outside when tight.
- Oblique extension lines: group 52 on the dimension (radians); falls back to
  `DIMEDIT _O` if 52 is absent.
- Linetypes are loaded from acad.lin, then acadiso.lin. LTSCALE/PSLTSCALE are untouched.

## Verified by lisp_sim (before delivery)
Reader/paren errors, unknown functions, wrong argument counts, protected symbols (T, PI)
as locals, setvar names and value types, entmake group-code types and per-entity
required codes, missing text styles / linetypes / dimstyles referenced by entities,
LWPOLYLINE/LEADER vertex counts, every record's success, and the drawn result (overlay).

## Not verifiable outside AutoCAD (first things to check if a run fails)
- Whether `entmake` of a LEADER without annotation is accepted by the specific product
  version (the runtime falls back to a polyline and reports it).
- ActiveX: `vla-AddDimRotated/Aligned`, `TextOverride`, `StyleName`, `CopyFrom` -
  standard since AutoCAD 2000 but untested here; failures are caught and reported per
  dimension, the rest of the drawing still completes.
- Font availability (`arialbd.ttf`); a missing font is substituted by AutoCAD.
- Exact dimension text placement - AutoCAD's own fitting rules decide it; the overlay
  shows an approximation.
- Behaviour in Civil 3D vertical / non-English builds (the runtime uses `_` prefixed
  command names only in the DIMEDIT fallback).

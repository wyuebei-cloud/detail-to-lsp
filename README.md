# detail-to-lsp

[![tests](https://github.com/wyuebei-cloud/detail-to-lsp/actions/workflows/tests.yml/badge.svg)](https://github.com/wyuebei-cloud/detail-to-lsp/actions/workflows/tests.yml)

Rebuild an engineering/CAD detail shown in a PDF sheet or a screenshot as a single
AutoLISP file that draws it 1:1 in model space - geometry, text, leaders, symbols and
real DIMENSION objects on separate layers.

The skill is meant to be executed by an AI coding agent: one Python model per detail,
a fixed pre-verified LISP runtime, and numeric gates that must pass before anything is
delivered.

```
source --probe--> extract/measure --calibrate--> model.py (Detail API)
   --> emit .lsp + report --> check_lsp (parens, lint, simulation) --> overlay + coverage
   --> fix model.py --> repeat --> deliver
```

## Requirements

- Python 3.9 or newer.
- `pip install -r requirements.txt` for intake and the overlay. The generation and
  verification chain itself (`detail_model.py`, `emit_lsp.py`, `check_lsp.py`,
  `lisp_sim.py`) is standard library only.
- AutoCAD or Civil 3D **on Windows**. The generated runtime drives dimension styles and
  DIMENSION objects through ActiveX, which is Windows only. AutoCAD LT 2024 or newer is
  expected to work (LT 2024 added AutoLISP and supports most `VLA`/`VLAX` functions) but
  has not been tested. AutoCAD for Mac is not supported.
- An agent with **vision** capability. Phase 0 locates the detail in a rendered page,
  Phase 4 accepts the overlay by eye, and text drawn as glyph outlines or on a scanned
  sheet can only be read from the image. Coordinates never come from looking - they come
  from `raster_measure.py` and `calibrate.py`.

## Quick start

```bash
pip install -r requirements.txt
python scripts/probe.py sheet.pdf --render page.png      # VECTOR / RASTER / MIXED
python tests/run_tests.py                                # both reference cases
```

`SKILL.md` is the operating procedure. `references/` holds the model API and the vector
and raster playbooks; `references/autocad_notes.md` lists what the generated file does
and what cannot be verified outside AutoCAD.

## How it works

- One `model.py` per detail is the only place a coordinate exists. It records every key
  value with provenance (`dim`, `derived`, `vector`, `measured`, `standard`, `assumed`)
  and every dimension gets the source text it must reproduce (`expect=`).
- `emit_lsp.py` writes a self-contained `.lsp`: identical runtime + one record list +
  one `c:` command. Pure ASCII, CRLF, real-valued group codes.
- `check_lsp.py` is the delivery gate. It balances parentheses, lints, then executes the
  whole file in `lisp_sim.py` (an AutoLISP subset against an AutoCAD stub). Every
  `entmake` is validated against DXF group-code rules, so unknown functions, arity
  errors, missing text styles or linetypes and bad `setvar` calls fail before delivery.
  For files built on the runtime, the simulated run must also close at
  "N records OK, 0 failed" - a record it could not draw fails the gate even when nothing
  raised. Hand-written `.lsp` files are judged by simulator errors alone.
- `overlay.py` draws the **simulated** entities on top of the source and reports coverage
  in both directions. The number to drive to zero is unclaimed source ink outside text
  zones.
- The dimension text check is the independent guard against a wrong global scale: the
  overlay cannot detect one, because the model and the check share the same calibration.

## What is verified before delivery

Parenthesis and lint, full LISP simulation, per-entity DXF validation, coverage in both
directions, and each dimension's text against the source.
`tests/run_tests.py` also runs every intake CLI with its output forced to cp1252, the
encoding of a Windows pipe, so a tool that cannot print drawing text (private-use symbol
glyphs, U+2248) fails on any platform rather than only on a Windows workstation.

## What is not verified

Anything routed through ActiveX or `command` is stubbed in the simulator:
`vla-AddDimRotated`, `vla-put-TextOverride`, `_.DIMEDIT`. A green gate means the stub
accepted the call, not that a specific AutoCAD release will. Font availability is
substituted by AutoCAD if missing. Exact dimension text placement follows AutoCAD's own
fitting rules; the overlay shows an approximation. See `references/autocad_notes.md`.

## Scope and limits

- Model inches, Y up. Architectural units by default (`dim_units='dec'` for decimal).
- Annotation scale is fixed at generation time; text and dimension heights are sized for
  it. To change the drawing, edit `model.py` and regenerate - the LISP is not parametric.
- The method is tuned to North American standard-plan conventions. A metric source needs
  the unit handling changed, not just different numbers.
- Layers are `DTL-GEOM*`, `DTL-TEXT`, `DTL-DIM`; the command prefix is `UB-`. Both are
  defaults set in `model.py` and are meant to be renamed afterwards.

## Repository layout

```
SKILL.md              operating procedure
references/           model API, vector and raster playbooks, AutoCAD notes
scripts/              intake, model API, emitter, runtime, simulator, gate, overlay
templates/            model.py template
tests/                two reference cases and the regression runner
assets/fonts/         Liberation Sans, for text rendering in the overlay
```

## Tests

`python tests/run_tests.py` rebuilds both reference cases and checks the gates, the
dimension text and the coverage thresholds. Current result on Windows / Python 3.11:

| case | route | gate | dimension mismatches | unclaimed / spurious (outside text zones) |
|---|---|---|---|---|
| gutter_pan | raster screenshot | PASS | 0 | 5.90 % / 0.33 % |
| traffic_barrier | vector PDF | PASS | 0 | 5.69 % / 2.71 % |

`tests/gutter_pan/source.png` is a crop of WSDOT Standard Plan F-10.16-00.
`tests/traffic_barrier/source.pdf` is WSDOT 10.2-A6-1b. Both are public agency standard
plans, included as visual baselines for the regression tests.

CI runs the same suite on ubuntu-latest and windows-latest with Python 3.9 and 3.12.
Measured coverage moves by a few tenths of a percent between platforms (ubuntu py3.9:
5.97 % / 5.65 % unclaimed, 0.33 % / 2.68 % spurious); the thresholds are not
platform-specific and are not relaxed per leg.

## License

MIT, see `LICENSE`. The bundled fonts in `assets/fonts/` are Liberation Sans under the
SIL Open Font License 1.1; their license is in `assets/fonts/LICENSE-Liberation.txt` and
is unaffected by the repository license.

---

## 中文说明

把一个 PDF 图纸或截图里的工程详图重建为单个 AutoLISP 文件，在模型空间按 1:1 画出，
几何、文字、引线、符号和真实的 DIMENSION 对象分层放置。

运行前提：Python 3.9+，Windows 上的 AutoCAD 或 Civil 3D（ActiveX 仅 Windows 支持，
AutoCAD LT 2024+ 预期可用但未实测，Mac 版不支持），执行它的 agent 需要视觉能力。

方法与验收：每个详图一份 `model.py` 作为唯一坐标来源，生成后必须在 LISP 模拟器中
执行通过（逐实体校验 DXF 组码），并用模拟结果叠加源图检查覆盖率，尺寸文字须与源图
标注一致。模拟器不覆盖 ActiveX 路径，首次在 AutoCAD 中运行才算最终验证。

测试：`python tests/run_tests.py` 重建两个参考案例并检查全部门槛。

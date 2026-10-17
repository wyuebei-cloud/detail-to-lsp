"""<DETAIL TITLE> - model for detail-to-lsp.

Source : <file>, <page / crop>
Origin : <physical point>, +X <direction>, +Y up
Calib  : <px per inch | pt per inch> from <dimensions used>; origin at <px | pt>
"""
import os, sys, math
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.environ.get('DETAIL_TO_LSP', os.path.join(HERE, '..', '..'))   # folder containing SKILL.md
sys.path.insert(0, os.path.join(SKILL, 'scripts'))
from detail_model import *
# from pdf_extract import extract, text_lines, to_model      # vector sources

d = Detail('<Title>', 'UB-<NAME>', scale=16)
# d.layer('DTL-GEOM-REBAR', 1, 35)

# ---------------------------------------------------------------- key values (with provenance)
# W = d.param('width', 18.0, 'dim', "1'-6\" dimension")

# ---------------------------------------------------------------- geometry
# d.pline([...], closed=True)

# ---------------------------------------------------------------- dimensions (expect = source text)
# d.dim((0, 0), (W, 0), (W / 2, 6), expect="1'-6\"")

# ---------------------------------------------------------------- text, leaders, symbols
# d.text('NOTE', (x, y), 'note', 'ML'); d.leader([(tip), (knee), (shoulder)])

# ---------------------------------------------------------------- registration for the overlay
# d.calibrate_image(os.path.join(HERE, 'source.png'), origin_px=(u, v), px_per_in=s)
# d.calibrate_pdf(os.path.join(HERE, 'source.pdf'), 0, (x0, top, x1, bottom), (ox, otop), k, dpi=300)

if __name__ == '__main__':
    print('wrote', d.emit(os.path.join(HERE, 'out', 'UB-<NAME>.lsp')))

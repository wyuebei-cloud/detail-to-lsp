#!/usr/bin/env python3
"""probe.py - Phase 0 triage: what kind of source is this?

  python probe.py drawing.pdf [--render out.png --page 0 --dpi 100]
  python probe.py screenshot.png

PDF pages are classified as
  VECTOR  - stroked paths present and text extractable: use pdf_extract.py
  RASTER  - page is essentially one image (scan / pasted screenshot): treat as image
  MIXED   - both; extract vectors where they exist, measure pixels elsewhere
"""
import sys, os, argparse
from collections import Counter

def probe_pdf(path, render=None, page=0, dpi=100):
    import pdfplumber
    pdf = pdfplumber.open(path)
    print(f'PDF: {os.path.basename(path)}  pages={len(pdf.pages)}')
    meta = pdf.metadata or {}
    for k in ('Creator', 'Producer', 'Title'):
        if k in meta: print(f'  {k}: {meta[k]}')
    for i, pg in enumerate(pdf.pages):
        nl, nc, nr, nch, ni = len(pg.lines), len(pg.curves), len(pg.rects), len(pg.chars), len(pg.images)
        area = pg.width * pg.height
        img_cover = sum((im['x1'] - im['x0']) * (im['bottom'] - im['top']) for im in pg.images) / area if area else 0
        kind = 'VECTOR'
        if nl + nc + nr < 20 and img_cover > 0.5: kind = 'RASTER'
        elif img_cover > 0.2: kind = 'MIXED'
        lw = Counter(round(o.get('linewidth') or 0, 2) for o in pg.lines + pg.curves)
        print(f'  page {i}: {pg.width:.0f}x{pg.height:.0f} pt  lines={nl} curves={nc} rects={nr} chars={nch} '
              f'images={ni} (cover {img_cover:.0%})  -> {kind}')
        if lw: print('    stroke widths:', ', '.join(f'{w}:{n}' for w, n in lw.most_common(8)))
    if render is not None:
        im = pdf.pages[page].to_image(resolution=dpi).original
        im.save(render); print(f'  rendered page {page} at {dpi} dpi -> {render} ({im.width}x{im.height}); '
                               f'pixel = pt * {dpi / 72:.4f}')

def probe_image(path):
    from PIL import Image
    import numpy as np
    im = Image.open(path)
    g = np.asarray(im.convert('L'))
    dark = (g < 150).mean()
    gray_levels = len(np.unique(g))
    print(f'IMAGE: {os.path.basename(path)}  {im.width}x{im.height}  mode={im.mode}  dpi={im.info.get("dpi")}')
    print(f'  ink fraction {dark:.1%}, {gray_levels} gray levels '
          f'({"anti-aliased render" if gray_levels > 20 else "bilevel scan/line art"})')
    print('  next: find two independent dimensions per axis for calibration (calibrate.py)')

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('file'); ap.add_argument('--render'); ap.add_argument('--page', type=int, default=0)
    ap.add_argument('--dpi', type=int, default=100)
    a = ap.parse_args()
    if a.file.lower().endswith('.pdf'):
        probe_pdf(a.file, a.render, a.page, a.dpi)
    else:
        probe_image(a.file)

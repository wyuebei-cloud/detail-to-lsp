"""emit_lsp.py - turn a Detail into a single self-contained .lsp file.

Layout of the generated file:
  1. header comment (title, source, units, layers, provenance summary)
  2. the fixed runtime (lsp_runtime.lsp, verbatim)
  3. (defun dtl:data-<CMD> () '( ...records... ))   <- the only per-detail content
  4. (defun c:<CMD> () (dtl:run "<CMD>" (dtl:data-<CMD>)) (princ))

Numbers that DXF expects as reals are always written with a decimal point.
Non-ASCII characters in strings become AutoCAD \\U+XXXX escapes, so the file
stays pure ASCII.
"""
import os, datetime, math

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, 'lsp_runtime.lsp')

def lstr(s):
    out = []
    for ch in s:
        o = ord(ch)
        if ch == '\\':
            out.append('\\\\')
        elif ch == '"':
            out.append('\\"')
        elif o > 126 or o < 32:
            out.append('\\\\U+%04X' % o)
        else:
            out.append(ch)
    return '"' + ''.join(out) + '"'

def lreal(v):
    v = float(v)
    if not math.isfinite(v):
        raise ValueError('non-finite number in model')
    if abs(v) < 5e-9:
        return '0.0'
    s = ('%.6f' % v).rstrip('0')
    if s.endswith('.'):
        s += '0'
    return s

def lval(v, real=True):
    if v is None:
        return 'nil'
    if isinstance(v, bool):
        return 'T' if v else 'nil'
    if isinstance(v, str):
        return lstr(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return lreal(v)
    if isinstance(v, (list, tuple)):
        return '(' + ' '.join(lval(x) for x in v) + ')'
    raise TypeError(f'cannot emit {v!r}')

def pt(p):
    return '(%s %s)' % (lreal(p[0]), lreal(p[1]))

def rec_to_lisp(r):
    k = r[0]
    if k == 'LAYER':
        return '("LAYER" %s %d %d %s)' % (lstr(r[1]), r[2], r[3], lstr(r[4]))
    if k == 'STYLE':
        return '("STYLE" %s %s)' % (lstr(r[1]), lstr(r[2]))
    if k == 'DIMSTYLE':
        pairs = ' '.join('(%s . %s)' % (lstr(n), lval(v)) for n, v in r[2])
        return '("DIMSTYLE" %s (%s))' % (lstr(r[1]), pairs)
    if k == 'LINE':
        return '("LINE" %s %s %s)' % (lstr(r[1]), pt(r[2]), pt(r[3]))
    if k == 'PL':
        vs = ' '.join('(%s %s %s)' % (lreal(x), lreal(y), lreal(b)) for x, y, b in r[3])
        w = r[4] if len(r) > 4 else None
        return '("PL" %s %d (%s)%s)' % (lstr(r[1]), r[2], vs, (' ' + lreal(w)) if w else '')
    if k == 'CIRCLE':
        return '("CIRCLE" %s %s %s)' % (lstr(r[1]), pt(r[2]), lreal(r[3]))
    if k == 'ARC':
        return '("ARC" %s %s %s %s %s)' % (lstr(r[1]), pt(r[2]), lreal(r[3]), lreal(r[4]), lreal(r[5]))
    if k == 'TEXT':
        return '("TEXT" %s %s %s %s %s %s %s)' % (lstr(r[1]), lstr(r[2]), pt(r[3]), lreal(r[4]),
                                                 lreal(r[5]), lstr(r[6]), lstr(r[7]))
    if k == 'LEADER':
        return '("LEADER" %s %s %d %d (%s))' % (lstr(r[1]), lstr(r[2]), r[3], r[4], ' '.join(pt(p) for p in r[5]))
    if k == 'DIM':
        return '("DIM" %s %s %s %s %s %s %s %s %s)' % (
            lstr(r[1]), lstr(r[2]), lstr(r[3]), pt(r[4]), pt(r[5]), pt(r[6]), lreal(r[7]),
            lstr(r[8]) if r[8] else 'nil', lreal(r[9]) if r[9] is not None else 'nil')
    if k == 'SOLID':
        return '("SOLID" %s %s %s %s %s)' % (lstr(r[1]), pt(r[2]), pt(r[3]), pt(r[4]), pt(r[5]))
    raise ValueError('unknown record ' + k)

def header(d):
    now = datetime.date.today().isoformat()
    src = ''
    if d.calib:
        src = os.path.basename(d.calib.get('image') or d.calib.get('pdf') or '')
    L = [';;; ' + '=' * 74,
         f';;; {d.command}.lsp - {d.title}',
         f';;; Generated {now} by detail-to-lsp from {src or "source drawing"}.',
         ';;; Units: inches, model space 1:1. Insertion point = model origin (see report).',
         f';;; Annotation scale factor {d.scale:g} (text and dimension sizes are fixed for it;',
         ';;; regenerate from model.py to change it).',
         ';;; Layers:']
    for n, (c, lw, lt) in d.layers.items():
        L.append(f';;;   {n:<20} color {c:<3} lw {lw/100:.2f}  {lt}')
    assumed = [p for p in d.prov if p['src'] == 'assumed']
    if assumed:
        L.append(';;; Assumed values (confirm against the source):')
        for p in assumed:
            L.append(f";;;   {p['name']} = {p['value']}  {p['note']}"[:120])
    L.append(f';;; Command: {d.command}')
    L.append(';;; ' + '=' * 74)
    return '\n'.join(L)

def build_lsp(d):
    runtime = open(RUNTIME, encoding='ascii').read()
    recs = d.records()
    data = '\n    '.join(rec_to_lisp(r) for r in recs)
    cmd = d.command
    body = [header(d), '', runtime.rstrip(), '',
            ';;; ---------------------------------------------------------------------------',
            f';;; Detail data: {len(recs)} records',
            f'(defun dtl:data-{cmd} ()',
            "  '(",
            '    ' + data,
            '  )',
            ')', '',
            f'(defun c:{cmd} ()',
            f'  (dtl:run {lstr(cmd)} (dtl:data-{cmd}))',
            '  (princ)',
            ')', '',
            f'(princ "\\n{cmd} loaded. Type {cmd} to draw: {lstr(d.title)[1:-1]}")',
            '(princ)', '']
    txt = '\n'.join(body)
    txt.encode('ascii')          # guarantee pure ASCII
    return txt

def write_lsp(d, path):
    open(path, 'w', encoding='ascii', newline='\r\n').write(build_lsp(d))
    return path

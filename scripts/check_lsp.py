#!/usr/bin/env python3
"""check_lsp.py - delivery gate for .lsp files.

  python check_lsp.py file.lsp                 # paren balance + lint
  python check_lsp.py file.lsp --depth         # also print per-line depth report
  python check_lsp.py file.lsp --run C:CMD     # also execute in lisp_sim and validate entities

Exit code 0 only when: BALANCED, no lint errors, and (with --run) no simulator errors.
"""
import sys, re, os, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SHADOW = {'ANGLE', 'DISTANCE', 'LENGTH', 'LIST', 'MIN', 'MAX', 'REM', 'TYPE', 'LAST', 'ATOM', 'MEMBER',
          'ASSOC', 'APPEND', 'REVERSE', 'NTH', 'CAR', 'CDR', 'CONS', 'EVAL', 'APPLY', 'MAPCAR', 'FLOAT',
          'FIX', 'ABS', 'SQRT', 'SIN', 'COS', 'ATAN', 'POLAR', 'INTERS', 'STRCAT', 'SUBST', 'COMMAND',
          'ENTGET', 'ENTMAKE', 'GETVAR', 'SETVAR', 'READ', 'LOAD', 'OPEN', 'CLOSE', 'EXP', 'LOG', 'EXPT'}
PROTECTED = {'T', 'PI', 'NIL'}

def scan(src):
    """Return (ok, problems, depth_by_line, toplevel[(line, head)])."""
    depth, ins, i, line, n = 0, False, 0, 1, len(src)
    probs, top, depth_at = [], [], {}
    str_start = None
    while i < n:
        c = src[i]
        if c == '\n':
            depth_at[line] = depth; line += 1; i += 1; continue
        if ins:
            if c == '\\': i += 2; continue
            if c == '"': ins = False
            i += 1; continue
        if c == ';':
            if src.startswith(';|', i):
                j = src.find('|;', i + 2)
                if j < 0: probs.append(f'line {line}: unterminated ;| block comment'); break
                line += src.count('\n', i, j); i = j + 2; continue
            while i < n and src[i] != '\n': i += 1
            continue
        if c == '"': ins = True; str_start = line
        elif c == '(':
            if depth == 0:
                m = re.match(r'\(\s*([^\s()]+)\s*([^\s()]*)', src[i:i + 120])
                top.append((line, (m.group(1) + ' ' + m.group(2)).strip() if m else '?'))
            depth += 1
        elif c == ')':
            depth -= 1
            if depth < 0:
                probs.append(f"line {line}: extra ')'"); depth = 0
        i += 1
    depth_at[line] = depth
    if ins: probs.append(f'unterminated string starting line {str_start}')
    if depth: probs.append(f'{depth} unclosed "(" at end of file')
    return not probs, probs, depth_at, top

def lint(src, top):
    errs, warns = [], []
    for ln, s in enumerate(src.splitlines(), 1):
        if any(ord(ch) > 126 for ch in s):
            warns.append(f'line {ln}: non-ASCII character (AutoCAD may misread the file encoding)')
    names = {}
    for line, head in top:
        parts = head.split()
        if parts and parts[0].lower() == 'defun' and len(parts) > 1:
            nm = parts[1].upper()
            if nm in names: errs.append(f'line {line}: function {nm} defined twice (also line {names[nm]})')
            names[nm] = line
        elif parts and parts[0].lower() not in ('defun', 'vl-load-com', 'princ', 'setq', 'if', 'progn'):
            warns.append(f'line {line}: top-level form ({parts[0]} ...) runs at load time')
    for m in re.finditer(r'\(defun\s+([^\s()]+)\s*\(([^)]*)\)', src):
        fn = m.group(1).upper(); params = m.group(2).upper().split()
        for p in params:
            if p == '/': continue
            if p in PROTECTED: errs.append(f'{fn}: protected symbol {p} used as argument/local')
            elif p in SHADOW: warns.append(f'{fn}: local {p} shadows a built-in function')
        if fn.startswith('C:') and params and params[0] != '/':
            errs.append(f'{fn}: command function must not take arguments')
    for m in re.finditer(r'\(setq\s+(t|pi)\s', src, re.I):
        errs.append(f'setq of protected symbol {m.group(1)}')
    return errs, warns

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('lsp'); ap.add_argument('--depth', action='store_true')
    ap.add_argument('--run', metavar='C:CMD'); ap.add_argument('--json')
    a = ap.parse_args()
    src = open(a.lsp, encoding='utf-8', errors='replace').read().replace('\r\n', '\n')
    ok, probs, depth_at, top = scan(src)
    print('PAREN GATE:', 'BALANCED' if ok else 'UNBALANCED')
    for p in probs: print('  ' + p)
    if a.depth or not ok:
        lines = src.splitlines()
        print('\nper-line depth (depth at END of line):')
        for i, s in enumerate(lines, 1):
            print(f'{i:5d} {depth_at.get(i, 0):3d} | {s[:100]}')
    print(f'\ntop-level forms: {len(top)}')
    for line, head in top:
        print(f'  line {line:5d}: ({head} ...')
    errs, warns = lint(src, top)
    print(f'\nLINT: {len(errs)} error(s), {len(warns)} warning(s)')
    for e in errs: print('  ERROR ' + e)
    for w in warns[:40]: print('  warn  ' + w)
    rc = 0 if ok and not errs else 1
    if a.run and ok:
        import lisp_sim, json
        it = lisp_sim.simulate(src, a.run, is_src=True)
        print('\nSIMULATION (' + a.run + '):')
        print(lisp_sim.summary(it))
        # Files built on the detail-to-lsp runtime report how many records they drew and
        # how many they could not. A record the runtime could not draw is a defect in the
        # emitted data, so for those files the gate requires the count to end at 0.
        # Hand-written files have no such report and are judged by errors alone.
        # Runtime warnings (a linetype that would not load, a leader drawn as a polyline)
        # stay non-fatal.
        gate_errs = []
        if it.lookup(lisp_sim.Sym('DTL:RUN')) is not None:
            spoken = ' '.join(str(x) for x in it.out if isinstance(x, str))
            m = re.search(r'(\d+) records OK,\s+(\d+) failed', spoken)
            if not m:
                gate_errs.append('runtime did not report a record count - the command did not complete')
            elif int(m.group(2)):
                first = next((str(x).strip() for x in it.out if isinstance(x, str) and 'Record failed' in x), '')
                gate_errs.append(f'{m.group(2)} record(s) failed at runtime, gate requires 0. {first}'.strip())
        for e in gate_errs:
            print('  GATE  ' + e)
        it.acad.errors.extend(gate_errs)
        if a.json:
            json.dump({'entities': lisp_sim.entities_plain(it), 'tables': {k: list(v) for k, v in it.acad.tables.items()},
                       'errors': it.acad.errors, 'warnings': it.acad.warnings}, open(a.json, 'w'), indent=1)
        if it.acad.errors: rc = 1
    print('\nRESULT:', 'PASS' if rc == 0 else 'FAIL')
    sys.exit(rc)

if __name__ == '__main__':
    # A pipe on Windows uses the ANSI code page (cp1252); drawing text can contain
    # characters it cannot encode (private-use symbol glyphs, U+2248). Escape them
    # instead of crashing, so the tools behave the same on every platform.
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, 'reconfigure'):
            _s.reconfigure(errors='backslashreplace')
    main()

#!/usr/bin/env python3
"""Regression tests: rebuild both reference details and check the gates.

  python tests/run_tests.py

For each case: model.py -> .lsp -> check_lsp (paren + lint + simulation) ->
overlay coverage -> thresholds. Exit code 0 when every case passes.
"""
import os, sys, subprocess, re

HERE = os.path.dirname(os.path.abspath(__file__))
S = os.path.join(HERE, '..', 'scripts')
CASES = [
    # name, lsp, command, overlay extra args, max unclaimed %, max spurious % (outside text zones)
    ('gutter_pan', 'out/UB-CBGP.lsp', 'C:UB-CBGP', ['--ignore=158,-70,200,-50', '--ignore=-5,-70,10,-60'], 8.0, 2.0),
    ('traffic_barrier', 'out/UB-TBSEC.lsp', 'C:UB-TBSEC', ['--roi=-60,-36,50,58'], 8.0, 4.0),
]

def run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr

ok_all = True
for name, lsp, cmd, extra, max_u, max_s in CASES:
    cwd = os.path.join(HERE, name)
    print(f'== {name}')
    rc, out = run([sys.executable, 'model.py'], cwd)
    if rc: print(out); ok_all = False; continue
    rc, out = run([sys.executable, os.path.join(S, 'check_lsp.py'), lsp, '--run', cmd], cwd)
    gate = 'PASS' if rc == 0 else 'FAIL'
    print(f'   gate (parens/lint/simulation): {gate}')
    if rc: print(out[-2500:]); ok_all = False
    rep = open(os.path.join(cwd, lsp.replace('.lsp', '.report.md'))).read()
    mm = int(re.search(r'mismatches: (\d+)', rep).group(1)) if 'mismatches' in rep else 0
    print(f'   dimension text mismatches: {mm}')
    if mm: ok_all = False
    rc, out = run([sys.executable, os.path.join(S, 'overlay.py'), lsp, '--out', 'out/check'] + extra, cwd)
    if rc: print(out[-2500:]); ok_all = False; continue
    m = re.search(r'OUTSIDE TEXT ZONES.*?unclaimed by model :\s+([\d.]+) %.*?no source ink  :\s+([\d.]+) %', out, re.S)
    u, s = float(m.group(1)), float(m.group(2))
    good = u <= max_u and s <= max_s
    print(f'   coverage outside text zones: unclaimed {u:.2f}% (max {max_u}), spurious {s:.2f}% (max {max_s}) '
          f'-> {"OK" if good else "FAIL"}')
    ok_all &= good
print('\nALL PASS' if ok_all else '\nSOME TESTS FAILED')
sys.exit(0 if ok_all else 1)

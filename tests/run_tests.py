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
    # The gate must report a record count, and every record must have been drawn.
    mrec = re.search(r'(\d+) records OK,\s+(\d+) failed', out)
    if not mrec:
        print('   records: NOT REPORTED in gate output -> FAIL')
        ok_all = False
    else:
        print(f'   records drawn: {mrec.group(1)} OK, {mrec.group(2)} failed')
        if int(mrec.group(2)):
            ok_all = False
    rep = open(os.path.join(cwd, lsp.replace('.lsp', '.report.md')), encoding='utf-8').read()
    # "mismatches: N" missing means the dimension check never ran - absence is not a pass.
    if 'mismatches' not in rep:
        print('   dimension text mismatches: report has no dimension check -> FAIL')
        ok_all = False
    else:
        mm = int(re.search(r'mismatches: (\d+)', rep).group(1))
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
# ---------------------------------------------------------------- hatch smoke test
# Neither reference case uses HATCH, so build a tiny detail with an island, a bulge
# boundary and SOLID fill, and require the gate to pass with every hatch evaluated and
# its temporary boundaries erased.
print('== hatch (AddHatch / loops / Evaluate)')
sys.path.insert(0, S)
import tempfile, lisp_sim
from detail_model import Detail
hd = Detail('hatch smoke', 'UB-HATCHT', scale=4)
hd.layer('DTL-HATCH-A', 1, 9)
hd.rect(0, 0, 10, 5)
hd.hatch([[(0, 0), (10, 0), (10, 5), (0, 5)], [(4, 1), (6, 1, 1.0), (6, 3), (4, 3)]], 'ANSI31', 2, 30, 'DTL-HATCH-A')
hd.hatch([(11, 0), (13, 0), (13, 2)], 'SOLID')
with tempfile.TemporaryDirectory() as td:
    hl = hd.emit(os.path.join(td, 'UB-HATCHT.lsp'))
    rc, out = run([sys.executable, os.path.join(S, 'check_lsp.py'), hl, '--run', 'C:UB-HATCHT'], td)
    it = lisp_sim.simulate(hl, 'C:UB-HATCHT')
types = [r['type'] for r in it.acad.ents]
hats = [r for r in it.acad.ents if r['type'] == 'HATCH']
good = (rc == 0 and len(hats) == 2 and types.count('LWPOLYLINE') == 1
        and [len(h['loops']) for h in hats] == [2, 1] and all(h.get('evaluated') for h in hats))
print(f'   gate {"PASS" if rc == 0 else "FAIL"}, hatches {len(hats)}, boundaries left {types.count("LWPOLYLINE") - 1}'
      f' -> {"OK" if good else "FAIL"}')
if not good: print(out[-2500:])
ok_all &= good

# ---------------------------------------------------------------- intake CLI smoke test
# The reference cases above never print source text, so they cannot catch an intake tool
# that crashes on output. Run every CLI once with the child's stdout forced to cp1252 -
# the encoding a Windows pipe uses - so a character it cannot encode fails here on any OS.
print('== intake CLI smoke (stdout encoding cp1252)')
GP, TB = os.path.join(HERE, 'gutter_pan'), os.path.join(HERE, 'traffic_barrier')
SMOKE = [
    ('probe pdf', [os.path.join(S, 'probe.py'), os.path.join(TB, 'source.pdf')]),
    ('probe image', [os.path.join(S, 'probe.py'), os.path.join(GP, 'source.png')]),
    ('pdf_extract', [os.path.join(S, 'pdf_extract.py'), os.path.join(TB, 'source.pdf'),
                     '--bbox', '697,409,1016,700', '--arcs']),
    ('raster_measure', [os.path.join(S, 'raster_measure.py'), 'lines', os.path.join(GP, 'source.png'),
                        '770', '545', '1150', '595']),
    ('calibrate', [os.path.join(S, 'calibrate.py'), '1243=156.25', '483=60.727', '274=34.5', '143=18',
                   '--axis', 'x,x,y,y']),
]
env = dict(os.environ, PYTHONIOENCODING='cp1252')
for label, args in SMOKE:
    r = subprocess.run([sys.executable] + args, cwd=HERE, capture_output=True, env=env)
    good = r.returncode == 0
    print(f'   {label:<15} {"OK" if good else "FAIL"}')
    if not good:
        print(r.stderr.decode('cp1252', 'replace')[-1500:])
        ok_all = False

print('\nALL PASS' if ok_all else '\nSOME TESTS FAILED')
sys.exit(0 if ok_all else 1)

"""Differential harness.

Two kinds of checks:
  * BEHAVIOUR  - every public result must be byte-identical between upstream
                 and patched.  Any difference here is a bug in the patch.
  * STRUCTURE  - counters that prove the optimisation is still present
                 (behaviour alone cannot see an optimisation being deleted).

Both trees are run through the same probe; module resolution is asserted first
so a stray site-packages copy of pydub can never be the thing under test.
"""
import json
import os
import subprocess
import sys
import time

PY = os.environ.get('PYDUB_AUDIT_PYTHON', sys.executable)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HERE = os.environ.get('PYDUB_AUDIT_CORPUS') or os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get('PYDUB_AUDIT_ROOT') or os.path.dirname(HERE)
UP = os.environ.get('PYDUB_AUDIT_UPSTREAM') or os.path.join(ROOT, 'upstream')
PAT = os.environ.get('PYDUB_AUDIT_PATCHED') or os.path.join(ROOT, 'patched')

GUARD = ('import os, sys, pydub; '
         'exp = os.path.normcase(os.path.abspath(sys.argv[1])); '
         'got = os.path.normcase(os.path.abspath(pydub.__file__)); '
         'sys.exit(0 if got.startswith(exp) else ("WRONG: " + got))')

# Structural expectations measured on the patched tree.  The upstream value is
# printed alongside so every number in the report is reproducible.
STRUCTURE = {
    'silence_segments_built': {'max': 2,
                               'why': 'detect_silence must not build one AudioSegment per window'},
    'cdr_ratio_to_db_calls': {'max': 20000,
                              'why': 'compress_dynamic_range memoises ratio_to_db per distinct rms'},
    'cdr_peak_alloc_mb': {'max': 40,
                          'why': 'compressor must flush blocks instead of keeping one bytes per frame'},
    'reader_is_fast': {'equals': True,
                       'why': 'the sliding RMS reader must be available for this segment'},
    'reader_parity': {'self_check': True,
                      'why': 'sliding reader must equal get_sample_slice().rms on every probed index'},
}


def run(tree, script):
    env = dict(os.environ)
    env['PYTHONPATH'] = tree
    env['PYTHONHASHSEED'] = '0'
    g = subprocess.run([PY, '-c', GUARD, os.path.join(tree, 'pydub')],
                       capture_output=True, env=env, cwd=HERE)
    if g.returncode:
        raise SystemExit('module resolution failed for %s: %s'
                         % (tree, g.stdout.decode('utf-8', 'replace')))
    t0 = time.perf_counter()
    r = subprocess.run([PY, os.path.join(SCRIPT_DIR, script)], capture_output=True, env=env, cwd=HERE)
    dt = time.perf_counter() - t0
    if r.returncode:
        raise SystemExit('%s %s failed:\n%s' % (tree, script,
                                                r.stderr.decode('utf-8', 'replace')[-2500:]))
    return json.loads(r.stdout.decode('utf-8').strip()), dt


def main():
    up, t_up = run(UP, 'probe.py')
    pat, t_pat = run(PAT, 'probe.py')

    behaviour = [k for k in up if k not in STRUCTURE]
    diffs = [k for k in behaviour if up.get(k) != pat.get(k)]

    print('behaviour checks: %d, mismatches: %d' % (len(behaviour), len(diffs)))
    for k in diffs:
        print('  DIFF %s\n    upstream: %s\n    patched : %s'
              % (k, str(up.get(k))[:300], str(pat.get(k))[:300]))

    print('')
    print('structure checks:')
    struct_ok = True
    for key in sorted(STRUCTURE):
        rule = STRUCTURE[key]
        got = pat.get(key)
        if rule.get('self_check'):
            # Each row is [index, reader_value, reference_value]; the reader
            # must match the documented reference on every probed index.
            ok = (isinstance(got, list) and bool(got)
                  and all(row[1] == row[2] for row in got))
        elif 'max' in rule:
            ok = isinstance(got, (int, float)) and got <= rule['max']
        else:
            ok = got == rule['equals']
        struct_ok = struct_ok and ok
        shown = ('%d rows, %d mismatched'
                 % (len(got), sum(1 for r in got if r[1] != r[2]))
                 if rule.get('self_check') and isinstance(got, list) else got)
        print('  %-26s upstream=%-8s patched=%-22s %s  (%s)'
              % (key, up.get(key), shown, 'OK' if ok else 'FAIL', rule['why']))

    print('')
    print('wall clock for the whole probe: upstream %.1fs, patched %.1fs' % (t_up, t_pat))

    ok = (not diffs) and struct_ok
    print('')
    print('ALL CHECKS PASSED' if ok else 'CHECKS FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())

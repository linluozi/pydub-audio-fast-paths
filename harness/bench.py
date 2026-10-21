"""
Interleaved benchmark: upstream vs patched, one fresh process per (arm, case).

Design notes
  * Both arms run in the SAME round, alternating, so machine drift hits both.
  * Per-round ratio is what gets reported; the absolute seconds are noise-prone.
  * Each cell is its own process: no allocator warm-up carry-over between arms.
  * Peak RSS is read from the Windows working-set counter, which (unlike
    tracemalloc) sees bytes that never touch the Python heap.
"""
import json
import os
import statistics
import subprocess
import sys

PY = os.environ.get('PYDUB_AUDIT_PYTHON', sys.executable)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HERE = os.environ.get('PYDUB_AUDIT_CORPUS') or os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get('PYDUB_AUDIT_ROOT') or os.path.dirname(HERE)
UP = os.environ.get('PYDUB_AUDIT_UPSTREAM') or os.path.join(ROOT, 'upstream')
PAT = os.environ.get('PYDUB_AUDIT_PATCHED') or os.path.join(ROOT, 'patched')
OUT = os.environ.get('PYDUB_AUDIT_OUT', 'results.json')

GUARD = ('import os, sys, pydub; '
         'exp = os.path.normcase(os.path.abspath(sys.argv[1])); '
         'got = os.path.normcase(os.path.abspath(pydub.__file__)); '
         'sys.exit(0 if got.startswith(exp) else ("WRONG: " + got))')


def run_cell(tree, case, repeats):
    env = dict(os.environ)
    env['PYTHONPATH'] = tree
    env['PYTHONHASHSEED'] = '0'
    g = subprocess.run([PY, '-c', GUARD, os.path.join(tree, 'pydub')],
                       capture_output=True, env=env, cwd=HERE)
    if g.returncode:
        raise SystemExit('module guard failed: ' + g.stdout.decode('utf-8', 'replace'))
    r = subprocess.run([PY, os.path.join(SCRIPT_DIR, 'cell.py'), case, str(repeats)],
                       capture_output=True, env=env, cwd=HERE)
    if r.returncode:
        raise SystemExit('%s/%s failed:\n%s' % (tree, case, r.stderr.decode('utf-8', 'replace')[-2000:]))
    return json.loads(r.stdout.decode('utf-8').strip())


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    cases = json.load(open(os.path.join(SCRIPT_DIR, 'cases.json'), encoding='utf-8'))
    results = {}
    for case in cases:
        name = case['name']
        print('== %s ==' % name, flush=True)
        up_t, pat_t, up_m, pat_m, ratios = [], [], [], [], []
        for rnd in range(rounds):
            a = run_cell(UP, name, case['repeats'])
            b = run_cell(PAT, name, case['repeats'])
            up_t.append(a['seconds'])
            pat_t.append(b['seconds'])
            up_m.append(a['peak_rss_mb'])
            pat_m.append(b['peak_rss_mb'])
            ratios.append(a['seconds'] / b['seconds'])
            print('  round %d  up=%.4fs pat=%.4fs  x%.2f  (up %.0fMB / pat %.0fMB)'
                  % (rnd + 1, a['seconds'], b['seconds'], ratios[-1],
                     a['peak_rss_mb'], b['peak_rss_mb']), flush=True)
        results[name] = {
            'description': case['description'],
            'workload': case['workload'],
            'upstream_seconds_median': statistics.median(up_t),
            'patched_seconds_median': statistics.median(pat_t),
            'speedup_ratio_median': statistics.median(ratios),
            'speedup_ratio_iqr': [sorted(ratios)[len(ratios) // 4],
                                  sorted(ratios)[(3 * len(ratios)) // 4]],
            'upstream_peak_rss_mb': statistics.median(up_m),
            'patched_peak_rss_mb': statistics.median(pat_m),
            'rounds': rounds,
            'raw': {'up': up_t, 'pat': pat_t, 'ratios': ratios,
                    'up_rss': up_m, 'pat_rss': pat_m},
        }
        print('  -> median speedup x%.2f, RSS %.0f -> %.0f MB'
              % (results[name]['speedup_ratio_median'],
                 results[name]['upstream_peak_rss_mb'],
                 results[name]['patched_peak_rss_mb']), flush=True)
    with open(os.path.join(SCRIPT_DIR, OUT), 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(results, fh, indent=2, sort_keys=True)
    print('\nwrote %s' % OUT)


if __name__ == '__main__':
    main()

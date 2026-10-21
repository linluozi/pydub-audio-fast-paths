#!/usr/bin/env python
"""
End-to-end verification for the pydub fast-path patch.

Self-contained: locates the package root by marker files (so it does not care
where the ZIP was unpacked), generates its own audio fixtures, applies the
patch to a scratch copy of upstream/, then runs

  1. patch fidelity      - the patched tree must equal upstream + patch, byte for byte
  2. differential probe  - 77 behaviour checks must be byte-identical
  3. structural checks   - the optimisation must still be present (counters)
  4. upstream test suite - failure set must be unchanged vs unpatched
  5. regression tests    - tests/test_fast_paths.py must pass on patched,
                           and the structural ones must FAIL on upstream

Usage:
    python verify.py            # full run
    python verify.py --quick    # skip the benchmark

Requirements: Python 3.8+ with audioop (3.12 or older; on 3.13 install
audioop-lts).  ffmpeg/ffprobe on PATH is needed only for step 4.
"""
from __future__ import print_function

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def find_root(start):
    """Walk up until we see the marker layout, so unpack location is irrelevant."""
    cur = start
    for _ in range(6):
        if (os.path.isdir(os.path.join(cur, 'upstream', 'pydub'))
                and os.path.isfile(os.path.join(cur, 'patch', 'pydub-fast-paths.patch'))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    raise SystemExit('could not locate the package root (expected upstream/ and patch/) from %s' % start)


ROOT = find_root(HERE)
PY = sys.executable
FAILURES = []
SKIPPED = []


def step(title):
    print('')
    print('=' * 72)
    print(title)
    print('=' * 72)


def run(cmd, cwd=None, env=None, timeout=1800):
    proc = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.decode('utf-8', 'replace')


def check(cond, message):
    print(('  PASS  ' if cond else '  FAIL  ') + message)
    if not cond:
        FAILURES.append(message)
    return cond


def tree_digest(path):
    import hashlib
    h = hashlib.sha256()
    for base, dirs, files in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d != '__pycache__')
        for name in sorted(files):
            if name.endswith('.pyc'):
                continue
            full = os.path.join(base, name)
            rel = os.path.relpath(full, path).replace('\\', '/')
            h.update(rel.encode('utf-8'))
            with open(full, 'rb') as fh:
                h.update(fh.read())
    return h.hexdigest()


def main():
    quick = '--quick' in sys.argv
    work = tempfile.mkdtemp(prefix='pydub-verify-')
    print('root  : %s' % ROOT)
    print('python: %s' % PY)
    print('scratch: %s' % work)

    # ---------------------------------------------------------- step 0: setup
    step('0. build upstream / patched trees from the shipped sources')
    up = os.path.join(work, 'upstream')
    pat = os.path.join(work, 'patched')
    shutil.copytree(os.path.join(ROOT, 'upstream', 'pydub'), os.path.join(up, 'pydub'))
    shutil.copytree(os.path.join(ROOT, 'upstream', 'pydub'), os.path.join(pat, 'pydub'))

    patch_file = os.path.join(ROOT, 'patch', 'pydub-fast-paths.patch')
    rc, out = run(['patch', '--binary', '-p1', '-i', patch_file], cwd=pat)
    print(out.strip())
    if not check(rc == 0, 'patch applies cleanly with -p1'):
        return finish()

    shipped = os.path.join(ROOT, 'patched', 'pydub')
    if os.path.isdir(shipped):
        same = tree_digest(os.path.join(pat, 'pydub')) == tree_digest(shipped)
        check(same, 'patched tree is byte-identical to the shipped reference tree')
    else:
        print('  note: no patched/ reference tree shipped, skipping cross-check')

    # -------------------------------------------------- step 1: audio fixtures
    step('1. generate audio fixtures')
    corpus = os.path.join(work, 'corpus')
    os.makedirs(corpus)
    gen = os.path.join(ROOT, 'harness', 'gen_all.py')
    rc, out = run([PY, gen, corpus])
    print(out.strip()[-2000:])
    if not check(rc == 0, 'fixtures generated'):
        return finish()

    # ------------------------------------------------------- step 2: diffrun
    step('2. differential probe (behaviour + structure)')
    env = dict(os.environ)
    env['PYDUB_AUDIT_ROOT'] = work
    env['PYDUB_AUDIT_CORPUS'] = corpus
    env['PYDUB_AUDIT_UPSTREAM'] = up
    env['PYDUB_AUDIT_PATCHED'] = pat
    rc, out = run([PY, os.path.join(ROOT, 'harness', 'diffrun.py')], cwd=corpus, env=env)
    print(out.strip())
    check(rc == 0 and 'ALL CHECKS PASSED' in out, 'differential probe passes')

    # --------------------------------------------------- step 3: upstream tests
    step('3. upstream test suite (failure set must be unchanged)')
    # The 192 kHz / 64-bit fixtures are 46 MB and are not committed; fetch them
    # on demand. If the network is unavailable the stage is reported as skipped
    # rather than silently passing.
    fetch = os.path.join(ROOT, 'harness', 'fetch_upstream_data.py')
    rc, out = run([PY, fetch, '--check'])
    if rc != 0:
        print('  fixtures missing, fetching from upstream@%s' % '103e339d')
        rc2, out2 = run([PY, fetch])
        print('  ' + out2.strip().replace('\n', '\n  '))
        rc = rc2
    if rc != 0:
        print('  SKIPPED: upstream fixtures unavailable (no network?)')
        print('  this stage is NOT verified in this run')
        SKIPPED.append('upstream test suite')
    else:
        suite = os.path.join(work, 'suite')
        for name, tree in (('base', up), ('pat', pat)):
            dest = os.path.join(suite, name)
            os.makedirs(dest)
            shutil.copytree(os.path.join(ROOT, 'upstream', 'test'), os.path.join(dest, 'test'))
            shutil.copytree(os.path.join(tree, 'pydub'), os.path.join(dest, 'pydub'))
        results = {}
        for name in ('base', 'pat'):
            rc, out = run([PY, '-m', 'pytest', 'test/test.py', '-q'], cwd=os.path.join(suite, name))
            failed = sorted(line.split(' - ')[0] for line in out.splitlines() if line.startswith('FAILED'))
            results[name] = failed
            summary = [line for line in out.splitlines() if 'passed' in line or 'failed' in line]
            print('  %s: %s' % (name, summary[-1] if summary else 'no summary'))
            if not summary:
                print(out[-1500:])
        check(results['base'] == results['pat'],
              'failure sets identical (%d on each side)' % len(results['base']))
        if results['base']:
            print('  pre-existing failures: %s'
                  % ', '.join(f.split('::')[-1] for f in results['base']))

    # --------------------------------------------------- step 4: new tests
    step('4. regression tests (must pass on patched, structural ones must fail on upstream)')
    newtests = os.path.join(ROOT, 'tests', 'test_fast_paths.py')
    for name, tree in (('patched', pat), ('upstream', up)):
        dest = os.path.join(work, 't_' + name)
        os.makedirs(dest)
        shutil.copytree(os.path.join(ROOT, 'tests'), os.path.join(dest, 'tests'))
        shutil.copytree(os.path.join(tree, 'pydub'), os.path.join(dest, 'pydub'))
        rc, out = run([PY, '-m', 'pytest', 'tests/test_fast_paths.py', '-q'], cwd=dest)
        tail = [l for l in out.splitlines() if 'passed' in l or 'failed' in l]
        print('  %-9s %s' % (name + ':', tail[-1] if tail else out[-400:]))
        if name == 'patched':
            check(rc == 0, 'all regression tests pass on the patched tree')
        else:
            # The equivalence tests are supposed to pass on upstream (they are
            # differential); the structural ones must not.
            structural = [l for l in out.splitlines() if l.startswith('FAILED')
                          and ('does_not_build_segments' in l or 'memoises' in l
                               or 'flushes_in_blocks' in l or 'frame_reader' in l)]
            check(len(structural) >= 3,
                  'structural tests go red on upstream (%d of them)' % len(structural))

    # ------------------------------------------------------- step 5: benchmark
    if not quick:
        step('5. benchmark (interleaved, 5 rounds)')
        env = dict(os.environ)
        env['PYDUB_AUDIT_ROOT'] = work
        env['PYDUB_AUDIT_CORPUS'] = corpus
        env['PYDUB_AUDIT_UPSTREAM'] = up
        env['PYDUB_AUDIT_PATCHED'] = pat
        rc, out = run([PY, os.path.join(ROOT, 'harness', 'bench.py'), '5'], cwd=corpus, env=env)
        print(out.strip()[-3000:])
        check(rc == 0, 'benchmark completed')

    return finish()


def finish():
    print('')
    print('=' * 72)
    if FAILURES:
        print('FAILED (%d):' % len(FAILURES))
        for f in FAILURES:
            print('  - %s' % f)
        if SKIPPED:
            print('also skipped: %s' % ', '.join(SKIPPED))
        return 1
    if SKIPPED:
        print('ALL RUN CHECKS PASSED, but these stages were skipped: %s'
              % ', '.join(SKIPPED))
        return 0
    print('ALL CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())

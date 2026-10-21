"""Mutation harness: mutate the patched tree, expect a differential probe to go red.

Each mutant runs in its own process with a hard timeout, because some mutants
turn an O(n) path back into O(n^2) (which is exactly the defect being fixed)
and would otherwise hang the whole sweep.
"""
import subprocess
import os
import shutil
import sys

PY = os.environ.get('PYDUB_AUDIT_PYTHON', sys.executable)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HERE = os.environ.get('PYDUB_AUDIT_CORPUS') or os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get('PYDUB_AUDIT_ROOT') or os.path.dirname(HERE)
SRC = os.path.join(os.environ.get('PYDUB_AUDIT_PATCHED') or os.path.join(ROOT, 'patched'), 'pydub')
UP = os.environ.get('PYDUB_AUDIT_UPSTREAM') or os.path.join(ROOT, 'upstream')

GUARD = ('import os, sys, pydub; '
         'exp = os.path.normcase(os.path.abspath(sys.argv[1])); '
         'got = os.path.normcase(os.path.abspath(pydub.__file__)); '
         'sys.exit(0 if got.startswith(exp) else ("WRONG: " + got))')

TIMEOUT = 150


def run(tree, script):
    env = dict(os.environ)
    env['PYTHONPATH'] = tree
    env['PYTHONHASHSEED'] = '0'
    g = subprocess.run([PY, '-c', GUARD, os.path.join(tree, 'pydub')],
                       capture_output=True, env=env, cwd=HERE)
    if g.returncode:
        return 99, '', 'module guard: ' + g.stdout.decode('utf-8', 'replace')
    try:
        r = subprocess.run([PY, os.path.join(SCRIPT_DIR, script)], capture_output=True, env=env, cwd=HERE,
                           timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return 98, '', 'timeout'
    return (r.returncode, r.stdout.decode('utf-8', 'replace').strip(),
            r.stderr.decode('utf-8', 'replace'))


base = {}
for script in ('probe.py', 'probe_small.py'):
    rc, out, err = run(UP, script)
    assert rc == 0, '%s on upstream failed: %s' % (script, err[-1500:])
    base[script] = out

NL = '\n'
MUTS = [
    ('M1', 'silence.py',
     "return int(math.sqrt(total / count))",
     "return int(math.sqrt(total / count)) + 1",
     'rms rounded up by 1', 'probe.py'),
    ('M2', 'silence.py',
     "total -= _sum_squares(view[state['lo']:lo])",
     "total -= 0",
     'frame reader keeps leaving samples', 'probe.py'),
    ('M3', 'silence.py',
     "total -= _sum_squares(view[last_lo:lo])",
     "total -= 0",
     'silence reader keeps leaving samples', 'probe.py'),
    ('M4', 'silence.py',
     "total += _sum_squares(view[last_hi:hi])",
     "total += 0",
     'silence reader ignores entering samples', 'probe.py'),
    ('M5', 'silence.py',
     "if total > _EXACT_SUM_LIMIT:",
     "if False:",
     'no wide-sum audioop fallback', 'probe.py'),
    ('M6', 'silence.py',
     "if previous[0] is not None and previous[0][0] <= lo and previous[0][1] <= hi:",
     "if False:",
     'always recompute whole window', 'probe_small.py'),
    ('M7', 'silence.py',
     "frames_per_ms = audio_segment.frame_rate / 1000.0",
     "frames_per_ms = 1000.0 / audio_segment.frame_rate",
     'ms->frame conversion wrong', 'probe.py'),
    ('M8', 'silence.py',
     "exact = sample_width < 4",
     "exact = sample_width < 3",
     '32-bit routed through exact path', 'probe.py'),
    ('M9', 'silence.py',
     "        if end < 0:" + NL + "            end = 0",
     "        if end < 0:" + NL + "            end = 1",
     'frame reader end clamp', 'probe.py'),
    ('M10', 'silence.py',
     "if chunk_size <= 0:",
     "if chunk_size <= -1:",
     'chunk_size guard relaxed', 'probe.py'),
    ('M11', 'audio_segment.py',
     "out[0::4] = high.translate(_24BIT_SIGN_PAD)",
     "out[0::4] = high",
     '24-bit sign pad dropped', 'probe.py'),
    ('M12', 'audio_segment.py',
     "out[1::4] = low",
     "out[1::4] = mid",
     '24-bit byte order swapped', 'probe.py'),
    ('M13', 'audio_segment.py',
     "chunk = raw[frame_bounds(start + i):frame_bounds(start + i + 1)]",
     "chunk = raw[frame_bounds(start + i):frame_bounds(start + i) + 1]",
     'fade chunk 1 byte', 'probe.py'),
    ('M14', 'audio_segment.py',
     "before_fade = raw[:frame_bounds(start)]",
     "before_fade = raw[:frame_bounds(start) + 1]",
     'fade prefix off by one', 'probe.py'),
    ('M15', 'audio_segment.py',
     "                sample = raw[start_i:start_i + frame_width]",
     "                sample = raw[start_i:start_i + 1]",
     'short fade frame truncated', 'probe.py'),
    ('M16', 'effects.py',
     "out_data[channel_i::n_channels] = array.array(",
     "out_data[0::n_channels] = array.array(",
     'all channels written to ch0', 'probe.py'),
    ('M17', 'effects.py',
     "            attenuation_cache[rms_now] = max_attenuation",
     "            pass",
     'cdr cache never populated (perf only)', 'probe_small.py'),
    ('M18', 'effects.py',
     "        frame = raw[start:start + frame_width]",
     "        frame = raw[start:start + 1]",
     'cdr frame truncated', 'probe.py'),
    ('M19', 'effects.py',
     "            attenuation = min(attenuation, max_attenuation)",
     "            attenuation = attenuation",
     'cdr clamp removed', 'probe.py'),
    ('M20', 'effects.py',
     "            attenuation = max(attenuation, 0)",
     "            attenuation = attenuation",
     'cdr floor removed', 'probe.py'),
    ('M21', 'audio_segment.py',
     "after_fade = raw[min(frame_bounds(end), segment_end):segment_end]",
     "after_fade = raw[frame_bounds(end):]",
     'fade tail not clamped to rounded length', 'probe.py'),
    ('M22', 'audio_segment.py',
     "segment_end = frame_bounds(len(self))",
     "segment_end = len(raw)",
     'tail clamp removed', 'probe.py'),
    ('M23', 'silence.py',
     "        elif start > limit:" + NL + "            start = limit",
     "        elif start > limit:" + NL + "            start = limit - 1",
     'frame reader start clamp', 'probe.py'),
    ('M25', 'effects.py',
     "        if block_bytes >= block_limit:",
     "        if block_bytes >= 1:",
     'cdr flushes every frame (one bytes per frame)', 'probe_small.py'),
    ('M26', 'effects.py',
     "            attenuation_cache[rms_now] = max_attenuation",
     "            attenuation_cache.clear()",
     'cdr cache cleared every frame', 'probe_small.py'),
    ('M24', 'silence.py',
     "        elif end > limit:" + NL + "            end = limit",
     "        elif end > limit:" + NL + "            end = limit + 1",
     'frame reader end overrun', 'probe.py'),
]

survived = []
for name, fname, old, new, desc, script in MUTS:
    work = os.path.join(ROOT, '_mut', name)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    dst = os.path.join(work, 'pydub')
    shutil.copytree(SRC, dst)
    p = os.path.join(dst, fname)
    with open(p, encoding='utf-8') as fh:
        text = fh.read()
    if old not in text:
        print('%-4s %-24s %s' % (name, 'SKIP pattern-missing', desc))
        survived.append((name, 'pattern-missing'))
        continue
    with open(p, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text.replace(old, new, 1))
    rc, out, err = run(work, script)
    if rc == 0 and out == base[script] and script == 'probe_small.py':
        # A perf-only mutant can still be caught by the structural counters,
        # so fall through to the full probe before calling it a survivor.
        rc2, out2, err2 = run(work, 'probe.py')
        if rc2 == 0 and out2 != base['probe.py']:
            rc, out, err = rc2, out2, err2
    if rc == 99:
        verdict = 'KILLED (import guard)'
    elif rc == 98:
        verdict = 'KILLED (timeout)'
    elif rc != 0:
        verdict = 'KILLED (crash)'
    elif out != base[script]:
        verdict = 'KILLED (output differs)'
    else:
        verdict = 'SURVIVED'
        survived.append((name, desc))
    print('%-4s %-24s %s  [%s]' % (name, verdict, desc, script))
    sys.stdout.flush()

print('')
print('survived: %s' % (survived,))

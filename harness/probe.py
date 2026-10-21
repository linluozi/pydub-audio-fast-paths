import sys, hashlib, json, math
from pydub import AudioSegment
from pydub.silence import detect_silence, detect_nonsilent, split_on_silence, detect_leading_silence
from pydub.effects import compress_dynamic_range, apply_mono_filter_to_each_channel, normalize

out = {}
def h(b): return hashlib.sha256(b).hexdigest()[:16]

# 1. general workload on two lengths
for s in (10, 30):
    seg = AudioSegment.from_wav(f'audio_{s}s.wav')
    out[f'sil_{s}_1000'] = detect_silence(seg, 1000, -30, 1)
    out[f'sil_{s}_500_5'] = detect_silence(seg, 500, -25, 5)
    out[f'sil_{s}_333_7'] = detect_silence(seg, 333, -18, 7)
    out[f'non_{s}'] = detect_nonsilent(seg, 1000, -30, 1)
    out[f'split_{s}'] = [h(x.raw_data) for x in split_on_silence(seg, 1000, -30, 100, 1)]
    out[f'lead_{s}'] = detect_leading_silence(seg)
    out[f'fadein_{s}'] = h(seg.fade_in(len(seg)).raw_data)
    out[f'fadeout_{s}'] = h(seg.fade_out(1500).raw_data)
    out[f'fade_mid_{s}'] = h(seg.fade(to_gain=-10, from_gain=-3, start=1000, duration=2000).raw_data)
    out[f'fade_short_{s}'] = h(seg.fade(to_gain=-6, from_gain=0, start=2000, duration=50).raw_data)
    out[f'fade_neg_{s}'] = h(seg.fade(to_gain=-6, from_gain=-2, start=-3000, duration=1000).raw_data)
    out[f'cdr_{s}'] = h(compress_dynamic_range(seg, -20.0, 4.0, 5.0, 50.0).raw_data)
    out[f'amf_{s}'] = h(apply_mono_filter_to_each_channel(seg, lambda x: x.apply_gain(-3)).raw_data)

# 2. threshold-boundary audio: every window rms within +-6 of the -30 dBFS cut
seg = AudioSegment.from_wav('audio_thresh.wav')
for thresh in (-30, -29, -31, -28.5, -30.5):
    out[f'thr_{thresh}'] = detect_silence(seg, 1000, thresh, 1)
out['thr_500'] = detect_silence(seg, 500, -30, 1)
out['thr_2000'] = detect_silence(seg, 2000, -30, 1)
out['thr_non'] = detect_nonsilent(seg, 1000, -30, 1)

# 3. wide-sum audio: window sums exceed 2**53, forcing the audioop fallback.
#    At 190 s the C double accumulation still rounds to 32767; past ~191 s it
#    drifts to 32766, so a threshold of 32766.5 separates the two.
huge = AudioSegment.from_wav('audio_huge.wav')
huge_thresh = 20 * math.log10(32766.5 / huge.max_possible_amplitude)
for msl in (190000, 191000, 195000, 199000):
    out[f'huge_{msl}'] = detect_silence(huge, msl, huge_thresh, 5000)
out['huge_rms'] = [huge[0:n].rms for n in (190000, 191000, 195000)]

# 3b. smaller wide-sum file (window sums stay under 2**53)
wide = AudioSegment.from_wav('audio_wide.wav')
out['wide_sil'] = detect_silence(wide, 1000, -1, 1)
out['wide_rms'] = [wide[i:i+1000].rms for i in (0, 500, 1000, 5000)]
out['wide_len'] = len(wide)

# 4. compressor with an audio that actually exercises attack and release
ramp = AudioSegment.from_wav('audio_ramp.wav')
for th, ra in ((-20.0, 4.0), (-30.0, 8.0), (-10.0, 2.0)):
    out[f'cdr_ramp_{th}_{ra}'] = h(compress_dynamic_range(ramp, th, ra, 5.0, 50.0).raw_data)
    out[f'cdr_ramp_a_{th}_{ra}'] = h(compress_dynamic_range(ramp, th, ra, 50.0, 200.0).raw_data)
out['cdr_ramp_short'] = h(compress_dynamic_range(ramp, -20.0, 4.0, 0.5, 0.5).raw_data)
# release shorter than one frame drives the envelope negative before the
# floor clamps it, so these cases observe the `max(attenuation, 0)` guard.
for rel in (0.001, 0.01, 0.02, 0.1):
    out[f'cdr_rel_{rel}'] = h(compress_dynamic_range(ramp, -20.0, 4.0, 5.0, rel).raw_data)
for atk in (0.001, 0.02, 0.5):
    out[f'cdr_atk_{atk}'] = h(compress_dynamic_range(ramp, -20.0, 4.0, atk, 50.0).raw_data)
out['cdr_ratio1'] = h(compress_dynamic_range(ramp, -20.0, 1.0001, 5.0, 50.0).raw_data)

# 5. 24 bit inputs
for p in ('audio_24bit.wav', 'audio_24bit_big.wav'):
    seg = AudioSegment.from_wav(p)
    out[f'24_{p}'] = [h(seg.raw_data), len(seg.raw_data), seg.sample_width]
    out[f'24_sil_{p}'] = detect_silence(seg, 1000, -30, 1)[:5]
    out[f'24_fade_{p}'] = h(seg.fade_in(min(2000, len(seg))).raw_data)

# 5b. 32-bit segment: exercises the `sample_width < 4` branch of the reader
#     (a 1 s window of 32-bit samples already exceeds 2**53, so every window
#     must go through audioop rather than the exact-int path).
wide32 = AudioSegment.from_wav('audio_32bit.wav')
out['sw32'] = [wide32.sample_width, len(wide32.raw_data)]
out['sw32_rms'] = [wide32[i:i+1000].rms for i in (0, 1, 250, 500, 999)]
out['sw32_sil'] = detect_silence(wide32, 1000, -6, 1)
out['sw32_sil2'] = detect_silence(wide32, 1000, -3, 1)
out['sw32_fade'] = h(wide32.fade_in(len(wide32)).raw_data)
out['sw32_cdr'] = h(compress_dynamic_range(wide32, -20.0, 4.0, 5.0, 50.0).raw_data)

# 6. 8 bit and mono paths
mono8 = AudioSegment.from_wav('audio_8bit_mono.wav')
out['m8_sil'] = detect_silence(mono8, 800, -30, 1)
out['m8_fade'] = h(mono8.fade_in(len(mono8)).raw_data)
out['m8_cdr'] = h(compress_dynamic_range(mono8, -20.0, 4.0, 5.0, 50.0).raw_data)

# 7. edge cases
empty = AudioSegment.empty()
out['empty_sil'] = detect_silence(empty)
short = AudioSegment.from_wav('audio_short.wav')
out['short_sil'] = detect_silence(short, 1000, -30, 1)
out['short_lead'] = detect_leading_silence(short)
try:
    detect_leading_silence(short, chunk_size=0)
    out['lead_zero'] = 'no-raise'
except Exception as e:
    out['lead_zero'] = type(e).__name__

# 8. Structural assertions (behaviour-only probes cannot see an optimisation
#    being deleted, so count what the optimised code actually does).
import pydub.silence as _sil
import pydub.effects as _eff

# 8a. The sliding frame reader must agree with get_sample_slice() even for the
#     out-of-range indices the clamp branches exist for.  Guarded so the same
#     probe also runs against upstream (which has no such helper).
ref16 = AudioSegment.from_wav('audio_10s.wav')
if hasattr(_sil, '_make_frame_rms_reader'):
    reader = _sil._make_frame_rms_reader(ref16, 220)
    out['reader_parity'] = [[i, reader(i), ref16.get_sample_slice(i - 220, i).rms]
                            for i in (-5, -1, 0, 1, 500, 440999, 441000, 441001)]
    out['reader_is_fast'] = reader is not None
else:
    out['reader_parity'] = 'absent'
    out['reader_is_fast'] = False

# 8b. The compressor memoises the dB conversion: ratio_to_db should be called
#     once per *distinct* window rms, not once per frame.
calls = [0]
real_ratio_to_db = _eff.ratio_to_db
def counting(r, *a, **kw):
    calls[0] += 1
    return real_ratio_to_db(r, *a, **kw)
_eff.ratio_to_db = counting
try:
    compress_dynamic_range(ref16, -20.0, 4.0, 5.0, 50.0)
finally:
    _eff.ratio_to_db = real_ratio_to_db
out['cdr_ratio_to_db_calls'] = calls[0]

# 8c. detect_silence must not build one AudioSegment per window.
made = [0]
real_init = AudioSegment.__init__
def counting_init(self, *a, **kw):
    made[0] += 1
    return real_init(self, *a, **kw)
AudioSegment.__init__ = counting_init
try:
    detect_silence(ref16, 1000, -30, 1)
finally:
    AudioSegment.__init__ = real_init
out['silence_segments_built'] = made[0]

# 8d. The compressor must not hold one bytes object per frame.  bytes.join is a
#     builtin and cannot be patched, so measure the peak allocation instead:
#     one entry per frame costs ~170 MB for 10 s of stereo audio.
import tracemalloc
tracemalloc.start()
try:
    compress_dynamic_range(ref16, -20.0, 4.0, 5.0, 50.0)
    _cur, _peak = tracemalloc.get_traced_memory()
finally:
    tracemalloc.stop()
out['cdr_peak_alloc_mb'] = round(_peak / 1048576.0, 2)
out['cdr_frames'] = int(ref16.frame_count())

print(json.dumps(out, sort_keys=True))


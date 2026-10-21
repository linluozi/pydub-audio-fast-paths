"""Small differential probe: same coverage, short inputs.

Used for mutations that are expected to be slow (they turn an O(n) path back
into O(n^2)); the point is to compare *outputs*, not to time them.
"""
import hashlib
import json

from pydub import AudioSegment
from pydub.silence import (detect_silence, detect_nonsilent, split_on_silence,
                           detect_leading_silence)
from pydub.effects import (compress_dynamic_range,
                           apply_mono_filter_to_each_channel)


def h(b):
    return hashlib.sha256(b).hexdigest()[:16]


out = {}

seg = AudioSegment.from_wav('audio_10s.wav')
out['sil'] = detect_silence(seg, 1000, -30, 1)
out['sil_seek'] = detect_silence(seg, 500, -25, 5)
out['non'] = detect_nonsilent(seg, 1000, -30, 1)
out['split'] = [h(x.raw_data) for x in split_on_silence(seg, 1000, -30, 100, 1)]
out['lead'] = detect_leading_silence(seg)
out['fadein'] = h(seg.fade_in(len(seg)).raw_data)
out['fade_short'] = h(seg.fade(to_gain=-6, from_gain=0, start=2000, duration=50).raw_data)
out['amf'] = h(apply_mono_filter_to_each_channel(seg, lambda x: x.apply_gain(-3)).raw_data)

thr = AudioSegment.from_wav('audio_thresh.wav')
out['thr'] = detect_silence(thr, 1000, -30, 1)
out['thr2'] = detect_silence(thr, 1000, -29.5, 1)

ramp = AudioSegment.from_wav('audio_ramp.wav')
out['cdr'] = h(compress_dynamic_range(ramp, -20.0, 4.0, 5.0, 50.0).raw_data)
out['cdr2'] = h(compress_dynamic_range(ramp, -30.0, 8.0, 50.0, 200.0).raw_data)

s24 = AudioSegment.from_wav('audio_24bit_big.wav')
out['24'] = [h(s24.raw_data), len(s24.raw_data)]

m8 = AudioSegment.from_wav('audio_8bit_mono.wav')
out['m8'] = detect_silence(m8, 800, -30, 1)

print(json.dumps(out, sort_keys=True))

"""Regression tests for the fast paths added in patch/pydub-fast-paths.patch.

Two kinds of assertions, because they catch different failures:

  * equivalence - the optimised path must produce byte-identical output to the
    documented reference implementation (get_sample_slice().rms, self[i]._data,
    detect_silence's own slicing loop).  A behavioural regression shows up here.
  * structure   - counters proving the optimisation is still present.  Without
    these, deleting the fast path keeps every equivalence test green.

Run with:  python -m pytest tests/test_fast_paths.py -q
"""
import hashlib
import math
import os
import struct
import sys
import wave

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pydub'))

from pydub import AudioSegment
from pydub import effects, silence
from pydub.effects import (apply_mono_filter_to_each_channel,
                           compress_dynamic_range)
from pydub.silence import (detect_leading_silence, detect_nonsilent,
                           detect_silence, split_on_silence)

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')


def write_wav(path, frames, channels=2, sample_width=2, rate=44100):
    with wave.open(path, 'wb') as fh:
        fh.setnchannels(channels)
        fh.setsampwidth(sample_width)
        fh.setframerate(rate)
        fh.writeframes(frames)


def tone(seconds, rate=44100, amp=12000, freq=220, channels=2, sample_width=2):
    code = {1: '<b', 2: '<h', 4: '<i'}[sample_width]
    frames = bytearray()
    for i in range(int(seconds * rate)):
        value = int(amp * math.sin(2 * math.pi * freq * i / rate))
        for _ in range(channels):
            frames += struct.pack(code, value)
    return bytes(frames)


@pytest.fixture(scope='module')
def clip(tmp_path_factory):
    """Speech-like clip: tone bursts separated by digital silence."""
    path = tmp_path_factory.mktemp('fast') / 'clip.wav'
    frames = bytearray()
    for block in range(4):
        frames += tone(0.4, amp=9000)
        frames += b'\x00' * (int(0.6 * 44100) * 4)
    write_wav(str(path), bytes(frames))
    return str(path)


def reference_silence_starts(seg, min_silence_len, thresh_db, seek_step):
    """The slicing loop from the pre-patch detect_silence, verbatim."""
    from pydub.utils import db_to_float
    thresh = db_to_float(thresh_db) * seg.max_possible_amplitude
    last = len(seg) - min_silence_len
    starts = list(range(0, last + 1, seek_step))
    if last % seek_step:
        starts.append(last)
    return [i for i in starts if seg[i:i + min_silence_len].rms <= thresh]


# ---------------------------------------------------------------- equivalence

@pytest.mark.parametrize('seek', [1, 3, 7])
@pytest.mark.parametrize('thresh', [-30, -26, -20])
def test_detect_silence_matches_reference_loop(clip, seek, thresh):
    seg = AudioSegment.from_wav(clip)
    fast = detect_silence(seg, 500, thresh, seek)
    starts = reference_silence_starts(seg, 500, thresh, seek)
    expected = []
    if starts:
        prev = starts[0]
        begin = prev
        for cur in starts[1:]:
            if not (cur == prev + seek) and cur > prev + 500:
                expected.append([begin, prev + 500])
                begin = cur
            prev = cur
        expected.append([begin, prev + 500])
    assert fast == expected


def test_detect_silence_threshold_boundary(clip):
    """Windows whose rms sits within one unit of the threshold."""
    seg = AudioSegment.from_wav(clip)
    from pydub.utils import db_to_float
    target = 6000.0
    thresh_db = 20 * math.log10(target / seg.max_possible_amplitude)
    for msl in (300, 500, 700):
        assert detect_silence(seg, msl, thresh_db, 1) == \
            _recombine(reference_silence_starts(seg, msl, thresh_db, 1), 1, msl)


def _recombine(starts, seek, msl):
    out = []
    if not starts:
        return out
    prev = starts[0]
    begin = prev
    for cur in starts[1:]:
        if not (cur == prev + seek) and cur > prev + msl:
            out.append([begin, prev + msl])
            begin = cur
        prev = cur
    out.append([begin, prev + msl])
    return out


def test_nonsilent_is_the_complement_of_silence(clip):
    seg = AudioSegment.from_wav(clip)
    silent = detect_silence(seg, 400, -40, 1)
    nonsilent = detect_nonsilent(seg, 400, -40, 1)
    # detect_nonsilent drops the leading [0, 0] gap, so the two lists are
    # offset by one; rebuild the complement the way the library documents it.
    rebuilt = []
    prev_end = 0
    for start_i, end_i in silent:
        rebuilt.append([prev_end, start_i])
        prev_end = end_i
    if silent[-1][1] != len(seg):
        rebuilt.append([prev_end, len(seg)])
    if rebuilt and rebuilt[0] == [0, 0]:
        rebuilt.pop(0)
    assert nonsilent == rebuilt
    pieces = split_on_silence(seg, 400, -40, 50, 1)
    assert len(pieces) == len(rebuilt)
    assert sum(len(p) for p in pieces) <= len(seg)


@pytest.mark.parametrize('width,amp', [(1, 90), (2, 9000), (4, 150000000)])
def test_detect_silence_every_sample_width(tmp_path, width, amp):
    path = str(tmp_path / ('w%d.wav' % width))
    write_wav(path, tone(1.2, amp=amp, channels=1, sample_width=width), channels=1,
              sample_width=width)
    seg = AudioSegment.from_wav(path)
    assert detect_silence(seg, 300, -6, 1) == \
        _recombine(reference_silence_starts(seg, 300, -6, 1), 1, 300)


def test_frame_reader_matches_get_sample_slice(clip):
    seg = AudioSegment.from_wav(clip)
    reader = silence._make_frame_rms_reader(seg, 220)
    assert reader is not None
    for i in (0, 1, 100, 220, 5000, int(seg.frame_count()) - 1, int(seg.frame_count())):
        assert reader(i) == seg.get_sample_slice(i - 220, i).rms


def test_fade_matches_per_segment_reference(clip):
    """Byte-for-byte against the pre-patch body: self[i]._data per millisecond.

    Note `self[i]` is a *whole millisecond* slice (frame_width * frame_rate/1000
    bytes), which is what the old code multiplied -- not a single frame.  The
    reference has to reproduce that exactly, including the clamp to len(self)
    that __getitem__ applies to the trailing slice.
    """
    seg = AudioSegment.from_wav(clip)
    from pydub.utils import db_to_float
    import audioop
    sw = seg.sample_width
    duration = 300
    from_power = db_to_float(-120)
    to_power = db_to_float(-3)
    step = (to_power - from_power) / duration
    expect = [seg[:0]._data]
    for i in range(duration):
        expect.append(audioop.mul(seg[i]._data, sw, from_power + step * i))
    tail = seg[duration:]._data
    if to_power != 1.0:
        tail = audioop.mul(tail, sw, to_power)
    expect.append(tail)
    got = seg.fade(to_gain=-3, from_gain=-120, start=0, duration=duration)
    assert got.raw_data == b''.join(expect)


def test_fade_short_path_matches_reference(clip):
    """The sub-100 ms branch walks samples, not milliseconds."""
    seg = AudioSegment.from_wav(clip)
    from pydub.utils import db_to_float
    import audioop
    sw = seg.sample_width
    duration = 50
    start = 200
    from_power = db_to_float(0)
    to_power = db_to_float(-6)
    start_frame = seg.frame_count(ms=start)
    end_frame = seg.frame_count(ms=start + duration)
    frames = end_frame - start_frame
    step = (to_power - from_power) / frames
    expect = [seg[:start]._data]
    for i in range(int(frames)):
        expect.append(audioop.mul(seg.get_frame(int(start_frame + i)), sw,
                                  from_power + step * i))
    tail = seg[start + duration:]._data
    if to_power != 1.0:
        tail = audioop.mul(tail, sw, to_power)
    expect.append(tail)
    got = seg.fade(to_gain=-6, from_gain=0, start=start, duration=duration)
    assert got.raw_data == b''.join(expect)


def test_fade_tail_respects_rounded_length(tmp_path):
    """A segment can hold sub-millisecond trailing bytes; fade must drop them."""
    path = str(tmp_path / 'odd.wav')
    write_wav(path, tone(0.5, rate=8000, channels=1), channels=1, rate=8000)
    seg = AudioSegment.from_wav(path)
    out = seg.fade_in(len(seg))
    assert len(out.raw_data) == len(seg[:len(seg)].raw_data)


def test_compress_dynamic_range_matches_upstream_formula(clip):
    """Independent re-implementation of the documented envelope, frame by frame."""
    from pydub.utils import db_to_float, ratio_to_db
    import audioop
    seg = AudioSegment.from_wav(clip)
    threshold, ratio, attack, release = -20.0, 4.0, 5.0, 50.0
    thresh_rms = seg.max_possible_amplitude * db_to_float(threshold)
    look = int(seg.frame_count(ms=attack))
    att_f = seg.frame_count(ms=attack)
    rel_f = seg.frame_count(ms=release)
    attenuation = 0.0
    out = []
    for i in range(int(seg.frame_count())):
        rms = seg.get_sample_slice(i - look, i).rms
        db = 0.0 if rms == 0 else max(ratio_to_db(rms / thresh_rms), 0)
        max_att = (1 - 1.0 / ratio) * db
        if rms > thresh_rms and attenuation <= max_att:
            attenuation = min(attenuation + max_att / att_f, max_att)
        else:
            attenuation = max(attenuation - max_att / rel_f, 0)
        frame = seg.get_frame(i)
        if attenuation != 0.0:
            frame = audioop.mul(frame, seg.sample_width, db_to_float(-attenuation))
        out.append(frame)
    got = compress_dynamic_range(seg, threshold, ratio, attack, release)
    assert got.raw_data == b''.join(out)


@pytest.mark.parametrize('release', [0.001, 0.02, 0.5, 50.0])
def test_compress_release_sweep(clip, release):
    """Sub-frame releases drive the envelope negative; the floor must clamp it."""
    seg = AudioSegment.from_wav(clip)
    out = compress_dynamic_range(seg, -20.0, 4.0, 5.0, release)
    assert len(out.raw_data) == len(seg.raw_data)
    assert out.max <= seg.max


def test_24bit_expansion_is_sign_extended(tmp_path):
    """Every byte pattern: the pad byte must be 0x00 or 0xFF, never anything else."""
    frames = bytearray()
    for b0 in range(0, 256, 17):
        for b1 in range(0, 256, 51):
            for b2 in (0x00, 0x7F, 0x80, 0xFF):
                frames += bytes((b0, b1, b2))
    path = str(tmp_path / 'p24.wav')
    write_wav(path, bytes(frames), channels=1, sample_width=3, rate=8000)
    seg = AudioSegment.from_wav(path)
    assert seg.sample_width == 4
    raw = seg.raw_data
    assert len(raw) == 4 * (len(frames) // 3)
    for idx in range(len(raw) // 4):
        pad, b0, b1, b2 = raw[idx * 4:idx * 4 + 4]
        assert pad == (0xFF if b2 >= 0x80 else 0x00)
        assert (b0, b1, b2) == tuple(frames[idx * 3:idx * 3 + 3])


def test_apply_mono_filter_interleaves_channels(tmp_path):
    """Left and right must not be swapped or duplicated."""
    frames = bytearray()
    for i in range(2000):
        frames += struct.pack('<hh', 1000, -1000)
    path = str(tmp_path / 'st.wav')
    write_wav(path, bytes(frames), channels=2)
    seg = AudioSegment.from_wav(path)
    gain = -6
    out = apply_mono_filter_to_each_channel(seg, lambda s: s.apply_gain(gain))
    # audioop rounds half away from zero; int() truncates, so take the value
    # from the library itself rather than recomputing it.
    import audioop
    expected_left = struct.unpack('<h', audioop.mul(struct.pack('<h', 1000), 2,
                                                    10 ** (gain / 20.0)))[0]
    expected_right = struct.unpack('<h', audioop.mul(struct.pack('<h', -1000), 2,
                                                     10 ** (gain / 20.0)))[0]
    for i in range(2000):
        left, right = struct.unpack('<hh', out.raw_data[i * 4:i * 4 + 4])
        assert left == expected_left, 'frame %d left=%d' % (i, left)
        assert right == expected_right, 'frame %d right=%d' % (i, right)
    assert expected_left > 0 > expected_right


def test_detect_leading_silence_rejects_zero_chunk(clip):
    """A stripped assert would spin forever under python -O; the guard must raise."""
    seg = AudioSegment.from_wav(clip)
    with pytest.raises(AssertionError):
        detect_leading_silence(seg, chunk_size=0)


# ------------------------------------------------------------------ structure

def test_detect_silence_does_not_build_segments(clip):
    built = [0]
    real = AudioSegment.__init__

    def counting(self, *a, **kw):
        built[0] += 1
        return real(self, *a, **kw)

    AudioSegment.__init__ = counting
    try:
        seg = AudioSegment.from_wav(clip)
        detect_silence(seg, 500, -30, 1)
    finally:
        AudioSegment.__init__ = real
    assert built[0] <= 2, 'one AudioSegment per window means the fast path is gone'


def test_compress_memoises_db_conversion(clip):
    calls = [0]
    real = effects.ratio_to_db

    def counting(r, *a, **kw):
        calls[0] += 1
        return real(r, *a, **kw)

    effects.ratio_to_db = counting
    try:
        seg = AudioSegment.from_wav(clip)
        frames = int(seg.frame_count())
        compress_dynamic_range(seg, -20.0, 4.0, 5.0, 50.0)
    finally:
        effects.ratio_to_db = real
    assert calls[0] < frames / 4, 'per-frame dB conversion means the memo is gone'


def test_compress_flushes_in_blocks(clip):
    """Peak allocation must not scale with the frame count.

    The clip is ~4 s of audio; one bytes object per frame would cost tens of
    megabytes of allocator overhead for a few hundred kilobytes of samples.
    """
    import tracemalloc
    seg = AudioSegment.from_wav(clip)
    frames = int(seg.frame_count())
    tracemalloc.start()
    try:
        compress_dynamic_range(seg, -20.0, 4.0, 5.0, 50.0)
        _cur, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # Blocks are flushed at 1 MiB; anything close to `frames` bytes per entry
    # blows well past this bound.
    assert peak < 12 * 1024 * 1024, \
        'peak %.1f MB over %d frames suggests one bytes object per frame' % (peak / 1e6, frames)

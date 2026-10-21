"""
Various functions for finding/manipulating silence in AudioSegments
"""
import itertools
import math
from operator import mul

from .utils import db_to_float, audioop

# Sample codes usable with memoryview.cast(), keyed by sample width in bytes.
_SAMPLE_CODES = {1: 'b', 2: 'h', 4: 'i'}

# Sums of squares are accumulated as Python ints and only turned into a float
# for the final square root.  For 8 and 16 bit samples every window sum stays
# below 2**53, so the int -> float conversion is lossless and the result is
# bit-identical to audioop.rms (which accumulates in a C double).  32 bit
# samples can exceed that range, so they keep calling audioop.rms directly.
_EXACT_SUM_LIMIT = 2 ** 53

_MISSING = object()


def _sum_squares(samples):
    """Sum of squares of a flat sample sequence, as an exact Python int."""
    return sum(map(mul, samples, samples))


def _make_rms_reader(audio_segment):
    """
    Build a callable ``read(start_ms, end_ms)`` returning exactly what
    ``audio_segment[start_ms:end_ms].rms`` returns, but without allocating an
    AudioSegment (and its frame-width bookkeeping) for every window.

    Consecutive windows reuse the running sum of squares, so the whole scan
    costs one pass over the samples instead of one pass per window.

    Returns None if this segment cannot be handled by the fast path; callers
    must then fall back to the slicing API.
    """
    if not hasattr(memoryview(b''), 'cast'):  # Python 2.7 has no cast()
        return None

    sample_width = audio_segment.sample_width
    code = _SAMPLE_CODES.get(sample_width)
    if code is None:
        return None

    frame_width = audio_segment.frame_width
    data = audio_segment._data
    if frame_width <= 0 or len(data) % frame_width:
        return None

    total_frames = len(data) // frame_width
    samples_per_frame = audio_segment.channels
    if samples_per_frame <= 0:
        return None
    try:
        view = memoryview(data).cast(code)
    except (TypeError, ValueError):
        return None
    total_samples = len(view)
    # AudioSegment._parse_position() computes int(ms * (frame_rate / 1000.0));
    # the parenthesisation matters for float rounding, keep it identical.
    frames_per_ms = audio_segment.frame_rate / 1000.0
    exact = sample_width < 4
    previous = [None, 0]  # [last (lo, hi) sample range, running sum]

    def read(start_ms, end_ms):
        start_frame = int(start_ms * frames_per_ms)
        end_frame = int(end_ms * frames_per_ms)
        if start_frame < 0 or end_frame < start_frame or end_frame > total_frames:
            return _MISSING
        lo = start_frame * samples_per_frame
        hi = end_frame * samples_per_frame
        if hi > total_samples:
            return _MISSING
        if not exact:
            # Let audioop do the accumulation so the result stays bit-exact
            # for wide samples; we still save the per-window AudioSegment.
            return audioop.rms(view[lo:hi], sample_width)

        if previous[0] is not None and previous[0][0] <= lo and previous[0][1] <= hi:
            last_lo, last_hi = previous[0]
            total = previous[1]
            total += _sum_squares(view[last_hi:hi])
            total -= _sum_squares(view[last_lo:lo])
        else:
            total = _sum_squares(view[lo:hi])
        previous[0] = (lo, hi)
        previous[1] = total

        count = hi - lo
        if not count:
            return 0
        if total > _EXACT_SUM_LIMIT:
            # Windows made of many full-scale samples can leave the
            # exactly-representable float range.  The running sum stays exact
            # (it is a Python int), only the division would round, so defer to
            # audioop for this one window instead of restarting the scan.
            return audioop.rms(view[lo:hi], sample_width)
        return int(math.sqrt(total / count))

    return read


def _make_frame_rms_reader(audio_segment, look_frames):
    """
    Build a callable ``read(frame_i)`` returning exactly what
    ``audio_segment.get_sample_slice(frame_i - look_frames, frame_i).rms``
    returns, without allocating one AudioSegment per frame.

    Used by the dynamic range compressor, which asks for the RMS of a sliding
    window once per sample frame (44100 windows per second of audio).

    Returns None when the segment cannot be handled by the fast path.
    """
    if not hasattr(memoryview(b''), 'cast'):  # Python 2.7 has no cast()
        return None

    sample_width = audio_segment.sample_width
    code = _SAMPLE_CODES.get(sample_width)
    if code is None:
        return None

    frame_width = audio_segment.frame_width
    data = audio_segment._data
    samples_per_frame = audio_segment.channels
    if frame_width <= 0 or samples_per_frame <= 0 or len(data) % frame_width:
        return None

    total_frames = len(data) // frame_width
    try:
        view = memoryview(data).cast(code)
    except (TypeError, ValueError):
        return None
    total_samples = len(view)
    exact = sample_width < 4
    # get_sample_slice() clamps both bounds to int(frame_count()).
    limit = int(audio_segment.frame_count())
    if limit > total_frames:
        limit = total_frames
    state = {'lo': None, 'hi': None, 'total': 0}

    def read(frame_i):
        start = frame_i - look_frames
        if start < 0:
            start = 0
        elif start > limit:
            start = limit
        end = frame_i
        if end < 0:
            end = 0
        elif end > limit:
            end = limit
        lo = start * samples_per_frame
        hi = end * samples_per_frame
        if lo > hi or hi > total_samples:
            return _MISSING

        if not exact:
            return audioop.rms(view[lo:hi], sample_width)

        if state['lo'] is not None and state['lo'] <= lo and state['hi'] <= hi:
            total = state['total']
            total += _sum_squares(view[state['hi']:hi])
            total -= _sum_squares(view[state['lo']:lo])
        else:
            total = _sum_squares(view[lo:hi])
        state['lo'] = lo
        state['hi'] = hi
        state['total'] = total

        count = hi - lo
        if not count:
            return 0
        if total > _EXACT_SUM_LIMIT:
            return audioop.rms(view[lo:hi], sample_width)
        return int(math.sqrt(total / count))

    return read


def detect_silence(audio_segment, min_silence_len=1000, silence_thresh=-16, seek_step=1):
    """
    Returns a list of all silent sections [start, end] in milliseconds of audio_segment.
    Inverse of detect_nonsilent()

    audio_segment - the segment to find silence in
    min_silence_len - the minimum length for any silent section
    silence_thresh - the upper bound for how quiet is silent in dFBS
    seek_step - step size for interating over the segment in ms
    """
    seg_len = len(audio_segment)

    # you can't have a silent portion of a sound that is longer than the sound
    if seg_len < min_silence_len:
        return []

    # convert silence threshold to a float value (so we can compare it to rms)
    silence_thresh = db_to_float(silence_thresh) * audio_segment.max_possible_amplitude

    # find silence and add start and end indicies to the to_cut list
    silence_starts = []

    # check successive (1 sec by default) chunk of sound for silence
    # try a chunk at every "seek step" (or every chunk for a seek step == 1)
    last_slice_start = seg_len - min_silence_len
    slice_starts = range(0, last_slice_start + 1, seek_step)

    # guarantee last_slice_start is included in the range
    # to make sure the last portion of the audio is searched
    if last_slice_start % seek_step:
        slice_starts = itertools.chain(slice_starts, [last_slice_start])

    read_rms = _make_rms_reader(audio_segment)
    for i in slice_starts:
        window_rms = _MISSING
        if read_rms is not None:
            window_rms = read_rms(i, i + min_silence_len)
        if window_rms is _MISSING:
            # Unusual layout (or a window the fast path refuses): use the
            # public slicing API so behaviour stays exactly as documented.
            window_rms = audio_segment[i:i + min_silence_len].rms
        if window_rms <= silence_thresh:
            silence_starts.append(i)

    # short circuit when there is no silence
    if not silence_starts:
        return []

    # combine the silence we detected into ranges (start ms - end ms)
    silent_ranges = []

    prev_i = silence_starts.pop(0)
    current_range_start = prev_i

    for silence_start_i in silence_starts:
        continuous = (silence_start_i == prev_i + seek_step)

        # sometimes two small blips are enough for one particular slice to be
        # non-silent, despite the silence all running together. Just combine
        # the two overlapping silent ranges.
        silence_has_gap = silence_start_i > (prev_i + min_silence_len)

        if not continuous and silence_has_gap:
            silent_ranges.append([current_range_start,
                                  prev_i + min_silence_len])
            current_range_start = silence_start_i
        prev_i = silence_start_i

    silent_ranges.append([current_range_start,
                          prev_i + min_silence_len])

    return silent_ranges


def detect_nonsilent(audio_segment, min_silence_len=1000, silence_thresh=-16, seek_step=1):
    """
    Returns a list of all nonsilent sections [start, end] in milliseconds of audio_segment.
    Inverse of detect_silent()

    audio_segment - the segment to find silence in
    min_silence_len - the minimum length for any silent section
    silence_thresh - the upper bound for how quiet is silent in dFBS
    seek_step - step size for interating over the segment in ms
    """
    silent_ranges = detect_silence(audio_segment, min_silence_len, silence_thresh, seek_step)
    len_seg = len(audio_segment)

    # if there is no silence, the whole thing is nonsilent
    if not silent_ranges:
        return [[0, len_seg]]

    # short circuit when the whole audio segment is silent
    if silent_ranges[0][0] == 0 and silent_ranges[0][1] == len_seg:
        return []

    prev_end_i = 0
    nonsilent_ranges = []
    for start_i, end_i in silent_ranges:
        nonsilent_ranges.append([prev_end_i, start_i])
        prev_end_i = end_i

    if end_i != len_seg:
        nonsilent_ranges.append([prev_end_i, len_seg])

    if nonsilent_ranges[0] == [0, 0]:
        nonsilent_ranges.pop(0)

    return nonsilent_ranges


def split_on_silence(audio_segment, min_silence_len=1000, silence_thresh=-16, keep_silence=100,
                     seek_step=1):
    """
    Returns list of audio segments from splitting audio_segment on silent sections

    audio_segment - original pydub.AudioSegment() object

    min_silence_len - (in ms) minimum length of a silence to be used for
        a split. default: 1000ms

    silence_thresh - (in dBFS) anything quieter than this will be
        considered silence. default: -16dBFS

    keep_silence - (in ms or True/False) leave some silence at the beginning
        and end of the chunks. Keeps the sound from sounding like it
        is abruptly cut off.
        When the length of the silence is less than the keep_silence duration
        it is split evenly between the preceding and following non-silent
        segments.
        If True is specified, all the silence is kept, if False none is kept.
        default: 100ms

    seek_step - step size for interating over the segment in ms
    """

    # from the itertools documentation
    def pairwise(iterable):
        "s -> (s0,s1), (s1,s2), (s2, s3), ..."
        a, b = itertools.tee(iterable)
        next(b, None)
        return zip(a, b)

    if isinstance(keep_silence, bool):
        keep_silence = len(audio_segment) if keep_silence else 0

    output_ranges = [
        [ start - keep_silence, end + keep_silence ]
        for (start,end)
            in detect_nonsilent(audio_segment, min_silence_len, silence_thresh, seek_step)
    ]

    for range_i, range_ii in pairwise(output_ranges):
        last_end = range_i[1]
        next_start = range_ii[0]
        if next_start < last_end:
            range_i[1] = (last_end+next_start)//2
            range_ii[0] = range_i[1]

    return [
        audio_segment[ max(start,0) : min(end,len(audio_segment)) ]
        for start,end in output_ranges
    ]


def detect_leading_silence(sound, silence_threshold=-50.0, chunk_size=10):
    """
    Returns the millisecond/index that the leading silence ends.

    audio_segment - the segment to find silence in
    silence_threshold - the upper bound for how quiet is silent in dFBS
    chunk_size - chunk size for interating over the segment in ms
    """
    if chunk_size <= 0:
        # Same exception type as the ``assert`` this replaces, but it also
        # survives ``python -O`` (where asserts are stripped and the loop
        # below would spin forever).
        raise AssertionError("chunk_size must be a positive number of milliseconds")
    trim_ms = 0 # ms
    while sound[trim_ms:trim_ms+chunk_size].dBFS < silence_threshold and trim_ms < len(sound):
        trim_ms += chunk_size

    # if there is no end it should return the length of the segment
    return min(trim_ms, len(sound))

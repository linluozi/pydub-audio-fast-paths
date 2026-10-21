# NOTICE

This repository is a modified copy of **pydub 0.25.1**
(<https://github.com/jiaaro/pydub>), MIT licensed. `LICENSE` is byte-identical to
upstream (1074 bytes, LF).

Upstream commit used as the base: `103e339d` (`master`).

## Modified files

| file | change |
|---|---|
| `pydub/silence.py` | added `_make_rms_reader` / `_make_frame_rms_reader` (sliding sum-of-squares with a 2^53 `audioop` fallback); `detect_silence` uses them; `detect_leading_silence` raises `AssertionError` explicitly instead of relying on a bare `assert` |
| `pydub/audio_segment.py` | added `_expand_24bit` (vectorised 24→32 bit widening); `fade` slices the raw buffer instead of constructing one `AudioSegment` per millisecond |
| `pydub/effects.py` | `apply_mono_filter_to_each_channel` uses strided slice assignment; `compress_dynamic_range` uses the sliding RMS reader, memoises the dB conversion, and accumulates into a flushing `bytearray` |

Nothing else in `pydub/` differs from upstream. The behaviour of every public
function is unchanged; `harness/probe.py` compares 77 results against unpatched
upstream and requires byte equality.

## Added files

Everything outside `pydub/` is new:

* `patch/`, `upstream/`, `patched/`, `harness/`, `tests/`, `assets/`,
  `evidence/`, `verify.py`, `README.md`, `NOTICE.md`

`upstream/` contains the unmodified pydub 0.25.1 source and its original test
suite, kept so the patch can be re-derived and re-verified offline.

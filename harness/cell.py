"""One benchmark cell: run one case `repeats` times, report best time and peak RSS."""
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import time


class _PMC(ctypes.Structure):
    _fields_ = [('cb', wt.DWORD), ('PageFaultCount', wt.DWORD),
                ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]


def _bind():
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(_PMC), wt.DWORD]
    psapi.GetProcessMemoryInfo.restype = wt.BOOL
    k32.GetCurrentProcess.restype = wt.HANDLE
    return k32, psapi


def peak_rss_mb():
    k32, psapi = _bind()
    p = _PMC()
    p.cb = ctypes.sizeof(_PMC)
    if not psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(p), p.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return p.PeakWorkingSetSize / 1048576.0


CASES = {
    'silence_60s': lambda: _silence('audio_60s.wav'),
    'silence_30s': lambda: _silence('audio_30s.wav'),
    'silence_10s': lambda: _silence('audio_10s.wav'),
    'cdr_30s': lambda: _cdr('audio_30s.wav'),
    'cdr_10s': lambda: _cdr('audio_10s.wav'),
    'fade_60s': lambda: _fade('audio_60s.wav'),
    'fade_30s': lambda: _fade('audio_30s.wav'),
    'load24_7mb': lambda: _load24('audio_24bit_big.wav'),
    'load24_2mb': lambda: _load24('audio_24bit.wav'),
    'amf_30s': lambda: _amf('audio_30s.wav'),
}


def _silence(path):
    from pydub import AudioSegment
    from pydub.silence import detect_silence
    seg = AudioSegment.from_wav(path)
    return detect_silence(seg, min_silence_len=1000, silence_thresh=-30, seek_step=1)


def _cdr(path):
    from pydub import AudioSegment
    from pydub.effects import compress_dynamic_range
    seg = AudioSegment.from_wav(path)
    return compress_dynamic_range(seg, threshold=-20.0, ratio=4.0, attack=5.0, release=50.0)


def _fade(path):
    from pydub import AudioSegment
    seg = AudioSegment.from_wav(path)
    return seg.fade_in(len(seg))


def _load24(path):
    from pydub import AudioSegment
    return AudioSegment.from_wav(path)


def _amf(path):
    from pydub import AudioSegment
    from pydub.effects import apply_mono_filter_to_each_channel
    seg = AudioSegment.from_wav(path)
    return apply_mono_filter_to_each_channel(seg, lambda s: s.apply_gain(-3))


def main():
    case = sys.argv[1]
    repeats = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    fn = CASES[case]
    best = None
    baseline = None
    for i in range(repeats):
        t0 = time.perf_counter()
        fn()
        dt = time.perf_counter() - t0
        if best is None or dt < best:
            best = dt
    print(json.dumps({'case': case, 'seconds': best, 'peak_rss_mb': peak_rss_mb(),
                      'repeats': repeats}))


if __name__ == '__main__':
    main()

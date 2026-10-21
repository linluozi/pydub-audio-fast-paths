"""One benchmark cell: load once, time only the function under test.

Two lessons are baked in here:

  * The timing window must not include AudioSegment.from_wav().  Loading a
    10 MB wav dominates the cost of the operation being measured, and the
    second process of a round hits the OS file cache, which alone produces a
    fake "speedup" of several x between two identical copies of the code.
  * Peak RSS is read from the OS, not tracemalloc, because most of the
    allocation happens outside the Python heap (bytes objects live in the raw
    allocator).  Windows uses the working-set counter, POSIX uses ru_maxrss.
"""
import json
import os
import sys
import time


def peak_rss_mb():
    """Peak resident set size of this process, in MB."""
    if os.name == 'nt':
        import ctypes
        import ctypes.wintypes as wt

        class _PMC(ctypes.Structure):
            _fields_ = [('cb', wt.DWORD), ('PageFaultCount', wt.DWORD),
                        ('PeakWorkingSetSize', ctypes.c_size_t),
                        ('WorkingSetSize', ctypes.c_size_t),
                        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                        ('PagefileUsage', ctypes.c_size_t),
                        ('PeakPagefileUsage', ctypes.c_size_t)]

        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(_PMC), wt.DWORD]
        psapi.GetProcessMemoryInfo.restype = wt.BOOL
        k32.GetCurrentProcess.restype = wt.HANDLE
        info = _PMC()
        info.cb = ctypes.sizeof(_PMC)
        if not psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(info), info.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return info.PeakWorkingSetSize / 1048576.0

    import resource
    # Linux reports ru_maxrss in kilobytes, macOS in bytes.
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == 'darwin':
        return raw / 1048576.0
    return raw / 1024.0


def _prepared(path):
    from pydub import AudioSegment
    return AudioSegment.from_wav(path)


def bench_silence(path):
    from pydub.silence import detect_silence
    seg = _prepared(path)
    return lambda: detect_silence(seg, min_silence_len=1000, silence_thresh=-30, seek_step=1)


def bench_cdr(path):
    from pydub.effects import compress_dynamic_range
    seg = _prepared(path)
    return lambda: compress_dynamic_range(seg, threshold=-20.0, ratio=4.0, attack=5.0, release=50.0)


def bench_fade(path):
    seg = _prepared(path)
    return lambda: seg.fade_in(len(seg))


def bench_amf(path):
    from pydub.effects import apply_mono_filter_to_each_channel
    seg = _prepared(path)
    return lambda: apply_mono_filter_to_each_channel(seg, lambda s: s.apply_gain(-3))


def bench_load24(path):
    """Loading IS the workload here, so it stays inside the timing window."""
    from pydub import AudioSegment
    AudioSegment.from_wav(path)          # prime the file cache once
    return lambda: AudioSegment.from_wav(path)


CASES = {
    'silence_10s': lambda: bench_silence('audio_10s.wav'),
    'silence_30s': lambda: bench_silence('audio_30s.wav'),
    'silence_60s': lambda: bench_silence('audio_60s.wav'),
    'fade_30s': lambda: bench_fade('audio_30s.wav'),
    'fade_60s': lambda: bench_fade('audio_60s.wav'),
    'cdr_10s': lambda: bench_cdr('audio_10s.wav'),
    'cdr_30s': lambda: bench_cdr('audio_30s.wav'),
    'amf_30s': lambda: bench_amf('audio_30s.wav'),
    'load24_2mb': lambda: bench_load24('audio_24bit.wav'),
    'load24_7mb': lambda: bench_load24('audio_24bit_big.wav'),
}


def main():
    case = sys.argv[1]
    repeats = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    fn = CASES[case]()
    best = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        dt = time.perf_counter() - t0
        if best is None or dt < best:
            best = dt
    print(json.dumps({'case': case, 'seconds': best, 'peak_rss_mb': peak_rss_mb(),
                      'repeats': repeats}))


if __name__ == '__main__':
    main()

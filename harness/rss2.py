import ctypes, ctypes.wintypes as wt

class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)
psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
psapi.GetProcessMemoryInfo.restype = wt.BOOL
k32.GetCurrentProcess.restype = wt.HANDLE

def peak_rss_mb():
    p = PMC(); p.cb = ctypes.sizeof(PMC)
    if not psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(p), p.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return p.PeakWorkingSetSize / 1048576.0

if __name__ == '__main__':
    a = peak_rss_mb()
    blob = bytearray(200*1024*1024)
    for i in range(0, len(blob), 4096): blob[i] = 1
    b = peak_rss_mb()
    print(f'before={a:.1f}MB after={b:.1f}MB delta={b-a:.1f}MB (expect ~200)')

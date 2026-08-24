import ctypes
import os
import shutil
import sys
import time
from ctypes import wintypes
from pathlib import Path

GB = 1 << 30
# Name
FILE_NAME = "name"
# Free space
RESERVE_BYTES = 1 * GB

GENERIC_WRITE = 0x40000000
CREATE_ALWAYS = 2
FILE_ATTRIBUTE_NORMAL = 0x80
FILE_BEGIN = 0
INVALID_HANDLE = wintypes.HANDLE(-1).value
TOKEN_QUERY = 0x0008
TOKEN_ADJUST_PRIVILEGES = 0x0020
SE_PRIVILEGE_ENABLED = 0x00000002

class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", ctypes.c_long)]

class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]

def human(n: int) -> str:
    return f"{n / GB:.2f} GB"

def enable_privilege(name: str) -> bool:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    adv.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(LUID)]
    adv.AdjustTokenPrivileges.argtypes = [
        wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(TOKEN_PRIVILEGES),
        wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID,
    ]

    token = wintypes.HANDLE()
    if not adv.OpenProcessToken(k32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token)):
        return False
    try:
        luid = LUID()
        if not adv.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
            return False
        tp = TOKEN_PRIVILEGES(1, (LUID_AND_ATTRIBUTES * 1)(LUID_AND_ATTRIBUTES(luid, SE_PRIVILEGE_ENABLED)))
        ctypes.set_last_error(0)
        if not adv.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None):
            return False
        return ctypes.get_last_error() == 0
    finally:
        k32.CloseHandle(token)

def alloc_nt(path: Path, size: int) -> bool:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    k32.SetFilePointerEx.argtypes = [
        wintypes.HANDLE, ctypes.c_longlong, ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD
    ]
    k32.SetEndOfFile.argtypes = [wintypes.HANDLE]
    k32.SetFileValidData.argtypes = [wintypes.HANDLE, ctypes.c_longlong]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    h = k32.CreateFileW(str(path), GENERIC_WRITE, 0, None, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, None)
    if h == INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not k32.SetFilePointerEx(h, size, None, FILE_BEGIN):
            raise ctypes.WinError(ctypes.get_last_error())
        if not k32.SetEndOfFile(h):
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(k32.SetFileValidData(h, size))
    finally:
        k32.CloseHandle(h)

def alloc_posix(path: Path, size: int) -> bool:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        if hasattr(os, "posix_fallocate"):
            os.posix_fallocate(fd, 0, size)
        else:
            os.ftruncate(fd, size)
        return True
    finally:
        os.close(fd)

def main() -> int:
    # Target file
    target = Path.home() / "Desktop" / FILE_NAME
    target.parent.mkdir(parents=True, exist_ok=True)

    free = shutil.disk_usage(target.parent).free
    total = max(0, free - RESERVE_BYTES)

    print(f"Free:   {human(free)}")
    print(f"Target: {human(total)}")
    print(f"Output: {target}")
    if total == 0:
        return 0

    if os.name == "nt":
        privileged = enable_privilege("SeManageVolumePrivilege")
        t0 = time.monotonic()
        valid = alloc_nt(target, total)
        dt = time.monotonic() - t0
        print(f"Mode:   {'valid-data' if valid else 'eof-only'} (privilege: {'on' if privileged else 'off'})")
    else:
        t0 = time.monotonic()
        alloc_posix(target, total)
        dt = time.monotonic() - t0

    print(f"Done:   {human(target.stat().st_size)} in {dt:.2f}s")
    print(f"Free:   {human(shutil.disk_usage(target.parent).free)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())

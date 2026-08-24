# Fast Large File Allocation

> Create a file with a very large logical size in a fraction of the time normally required to write the same amount of data.

This project demonstrates how operating-system and filesystem APIs can be used to create a large file without explicitly writing every byte of that file from Python.

For example, creating a 50 GB file does **not** necessarily mean writing 50 GB of zero bytes to the storage device.

The key idea is:

```text
Traditional file creation
Python → generate data → write data → disk

Fast allocation
Python → filesystem metadata/allocation operation → file
```

---

## How Can a Huge File Be Created So Quickly?

A normal approach might look like this:

```python
with open("test.bin", "wb") as f:
    f.write(b"\x00" * (10 * 1024**3))
```

This approach actually attempts to process approximately 10 GiB of data.

The larger the file becomes, the more work the system has to perform:

```text
10 GiB
   ↓
Generate bytes
   ↓
Transfer data
   ↓
Filesystem I/O
   ↓
Storage device
```

The code in this project takes a different approach.

Instead of producing billions of bytes, it asks the filesystem to make the file's logical size very large.

For example:

```text
test.bin
Logical size: 50 GiB
```

The operation that creates this logical size can be dramatically cheaper than physically writing 50 GiB of data.

That is why the program can sometimes report a result such as:

```text
Done: 49.00 GB in 0.84s
```

This should **not** be interpreted as the storage device physically writing 49 GB in 0.84 seconds.

---

# Core Concept

The most important distinction is:

```text
Logical File Size
        ≠
Amount of Data Physically Written
```

A filesystem maintains metadata describing a file, including its size.

The program can modify that metadata without first generating a buffer containing the entire file.

Conceptually:

```text
Before

test.bin
size = 0


After

test.bin
size = 50 GiB
```

The transition between those states can be much faster than:

```text
0 GiB
 ↓
1 GiB
 ↓
2 GiB
 ↓
...
 ↓
50 GiB
```

of actual byte writes.

---

# Windows Implementation

On Windows, the important APIs are:

```python
CreateFileW()
SetFilePointerEx()
SetEndOfFile()
SetFileValidData()
```

The relevant section is:

```python
h = k32.CreateFileW(
    str(path),
    GENERIC_WRITE,
    0,
    None,
    CREATE_ALWAYS,
    FILE_ATTRIBUTE_NORMAL,
    None
)

k32.SetFilePointerEx(h, size, None, FILE_BEGIN)
k32.SetEndOfFile(h)
k32.SetFileValidData(h, size)
```

Each operation has a different responsibility.

---

## 1. `CreateFileW()`

```python
h = k32.CreateFileW(...)
```

This creates or opens the target file and returns a Windows file handle.

The program requests write access:

```python
GENERIC_WRITE = 0x40000000
```

and uses:

```python
CREATE_ALWAYS = 2
```

which means an existing file with the same name is replaced.

---

## 2. `SetFilePointerEx()`

```python
k32.SetFilePointerEx(
    h,
    size,
    None,
    FILE_BEGIN
)
```

This does not write `size` bytes.

It moves the file pointer to the requested offset.

For example:

```text
0 GB                                      50 GB
│-------------------------------------------│
                                            ▲
                                            │
                                       file pointer
```

The program therefore reaches the target offset without transferring 50 GB of data through a normal write operation.

---

## 3. `SetEndOfFile()`

```python
k32.SetEndOfFile(h)
```

This makes the current file-pointer position the end of the file.

After:

```python
SetFilePointerEx(...)
SetEndOfFile(...)
```

Windows can report:

```text
File: test.bin
Size: 50 GB
```

without the Python program having to execute:

```python
write(...)
```

for all 50 GB.

This is one of the main reasons the operation can be extremely fast.

---

# `SetFileValidData()`

The most specialized part of the Windows implementation is:

```python
k32.SetFileValidData(h, size)
```

This API can allow Windows to treat a range of the file as valid data without performing the normal initialization work associated with exposing newly allocated disk regions.

That is useful for performance, but it has security implications.

For this reason, Windows protects the operation with a special privilege:

```text
SeManageVolumePrivilege
```

The program therefore attempts to enable that privilege before calling `SetFileValidData()`.

---

# Why `SeManageVolumePrivilege` Is Needed

The code contains:

```python
enable_privilege("SeManageVolumePrivilege")
```

The function uses Windows security APIs to modify the privileges available to the current process.

The flow is:

```text
Current Process
      │
      ▼
OpenProcessToken()
      │
      ▼
LookupPrivilegeValueW()
      │
      ▼
Build TOKEN_PRIVILEGES
      │
      ▼
AdjustTokenPrivileges()
      │
      ▼
SeManageVolumePrivilege enabled
```

The relevant APIs are provided by:

```text
kernel32.dll
advapi32.dll
```

Python accesses those Windows APIs through `ctypes`.

---

# Why Does the Code Use `ctypes`?

Python does not expose every Windows API as a normal Python function.

`ctypes` allows Python to call functions exported by Windows DLLs directly.

For example:

```python
k32 = ctypes.WinDLL(
    "kernel32",
    use_last_error=True
)
```

and:

```python
adv = ctypes.WinDLL(
    "advapi32",
    use_last_error=True
)
```

The code then declares the expected function signatures:

```python
k32.SetEndOfFile.argtypes = [
    wintypes.HANDLE
]
```

This tells `ctypes` what type of argument Windows expects.

---

# Windows Structures

Some Windows APIs expect C structures rather than simple integers.

The code recreates these structures using:

```python
ctypes.Structure
```

For example:

```python
class LUID(ctypes.Structure):
    _fields_ = [
        ("LowPart", wintypes.DWORD),
        ("HighPart", ctypes.c_long)
    ]
```

and:

```python
class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Luid", LUID),
        ("Attributes", wintypes.DWORD)
    ]
```

and finally:

```python
class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [
        ("PrivilegeCount", wintypes.DWORD),
        ("Privileges", LUID_AND_ATTRIBUTES * 1)
    ]
```

These structures reproduce the memory layout expected by the Windows API.

---

# The `alloc_nt()` Function

The main Windows allocation routine is:

```python
def alloc_nt(path: Path, size: int) -> bool:
```

Its sequence is:

```text
CreateFileW
    ↓
SetFilePointerEx
    ↓
SetEndOfFile
    ↓
SetFileValidData
    ↓
CloseHandle
```

In simplified form:

```python
CreateFileW(...)
SetFilePointerEx(...)
SetEndOfFile(...)
SetFileValidData(...)
```

The function returns `True` when `SetFileValidData()` succeeds.

If it fails, the program can still have a file with the requested logical size because `SetEndOfFile()` may already have succeeded.

That is why the program distinguishes between:

```text
valid-data
```

and:

```text
eof-only
```

---

# POSIX / Linux Implementation

The program also contains a separate implementation for non-Windows systems:

```python
def alloc_posix(path: Path, size: int) -> bool:
```

It opens the file:

```python
fd = os.open(
    path,
    os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
    0o644
)
```

Then it prefers:

```python
os.posix_fallocate(fd, 0, size)
```

when available.

`posix_fallocate()` requests allocation of the specified file space.

If unavailable, the program falls back to:

```python
os.ftruncate(fd, size)
```

The exact physical behavior depends on the operating system and filesystem.

---

# Calculating the Target Size

The program defines:

```python
GB = 1 << 30
```

which equals:

```text
1,073,741,824 bytes
```

This is technically 1 GiB rather than 1 decimal GB, but the variable name `GB` is used for convenience.

The program reserves approximately 1 GiB:

```python
RESERVE_BYTES = 1 * GB
```

Then checks the available space:

```python
free = shutil.disk_usage(target.parent).free
```

and calculates:

```python
total = max(
    0,
    free - RESERVE_BYTES
)
```

For example:

```text
Available:
50 GiB

Reserved:
1 GiB

Target:
49 GiB
```

The purpose is to avoid consuming the entire free space of the volume.

---

# Measuring Performance

The program measures allocation time with:

```python
t0 = time.monotonic()
```

and:

```python
dt = time.monotonic() - t0
```

`monotonic()` is appropriate for elapsed-time measurements because it is not affected by normal changes to the system clock.

The output may look like:

```text
Free:   100.00 GB
Target: 99.00 GB
Output: C:\Users\User\Desktop\test.bin
Mode:   valid-data (privilege: on)
Done:   99.00 GB in 0.72s
Free:   99.00 GB
```

The important point is that:

```text
99 GB / 0.72 seconds
```

is **not** necessarily the physical write throughput of the disk.

It represents the execution time of the allocation-related operations being measured.

---

# Why It Can Be Much Faster Than `write()`

Compare the two approaches.

## Traditional writing

```text
Python
  ↓
Generate bytes
  ↓
Memory
  ↓
Filesystem
  ↓
Storage
```

For a 100 GB file, approximately 100 GB of data must be processed.

## Allocation-based approach

```text
Python
  ↓
Filesystem API
  ↓
Metadata / allocation operation
  ↓
File
```

The amount of data transferred by the application can therefore be dramatically smaller.

This is the fundamental reason for the speed difference.

---

# The Most Important Performance Detail

The program is not discovering a way to make hardware physically write 100 GB instantaneously.

Instead, it is avoiding unnecessary data transfer.

Think of the difference as:

```text
METHOD A

"Here are 100 GB of bytes.
Please write all of them."
```

versus:

```text
METHOD B

"Make this file's logical size 100 GB."
```

Those are fundamentally different operations.

---

# Logical Size vs Physical Allocation

Filesystem terminology can be confusing because several concepts are involved.

A file may have:

```text
Logical size
```

and:

```text
Allocated physical blocks
```

These values and their semantics depend on the filesystem and allocation method.

Therefore:

```text
Large file size
```

does not automatically mean:

```text
The program just wrote the same amount of user data.
```

This distinction is essential when interpreting benchmarks.

---

# Complete Execution Flow

```text
main()
 │
 ├── Locate Desktop
 │
 ├── Check filesystem free space
 │
 ├── Reserve 1 GiB
 │
 ├── Calculate target size
 │
 ├── Windows?
 │      │
 │      ├── Enable SeManageVolumePrivilege
 │      ├── CreateFileW
 │      ├── SetFilePointerEx
 │      ├── SetEndOfFile
 │      └── SetFileValidData
 │
 └── POSIX?
        │
        ├── open()
        └── posix_fallocate()
             or ftruncate()
```

---

# Why the Result Can Look "Impossible"

Suppose the program reports:

```text
Done: 80.00 GB in 0.50s
```

It may look like:

```text
80 GB ÷ 0.5 s = 160 GB/s
```

But that calculation would only be meaningful if the program had actually written 80 GB of user data.

That is not what this benchmark measures.

A better interpretation is:

```text
The filesystem completed the requested
file-size/allocation operation in 0.50 seconds.
```

The benchmark should therefore be described as:

> Fast logical file allocation

rather than:

> 160 GB/s disk write speed

---

# Security Considerations

`SetFileValidData()` deserves particular attention.

The API can avoid certain filesystem initialization operations, which is one reason it can be fast. However, this behavior has security implications because newly exposed file regions must not inadvertently reveal stale information from previous disk usage.

That is why Windows restricts the operation through a privileged security mechanism.

This code should therefore be treated as a filesystem/API experiment, not as a generic file-copy or benchmarking technique.

Do not use it on a disk containing important data unless you understand the storage and filesystem semantics.

---

# Important Caveats

Performance is highly environment-dependent.

Results can change depending on:

```text
NTFS / ReFS / ext4 / XFS / Btrfs
SSD / HDD
Filesystem configuration
Storage controller
Virtual machine
Cloud storage
Disk encryption
System permissions
Available free space
```

The code should therefore never claim:

```text
"Any 100 GB file can always be created in exactly 1 second."
```

A more accurate claim is:

```text
Large logical files can sometimes be created extremely quickly
because the program avoids writing the entire file contents.
```

---

# Key Takeaways

The core technique can be summarized in three lines:

```text
Do not generate N GB of data.

Ask the filesystem for a file with size N GB.

Let the operating system handle the allocation semantics.
```

Or more precisely:

```text
File Size
    ≠
Amount of User Data Written
```

and:

```text
Fast Allocation
    ≠
Fast Physical Storage Throughput
```

That distinction explains why a file that appears to be tens or hundreds of gigabytes can be created in a very short amount of time.

---

# Disclaimer

This project demonstrates filesystem allocation behavior.

It does not provide a method for bypassing physical storage limits, creating real storage capacity, or achieving impossible disk-write speeds.

Reported performance represents the completion time of the selected filesystem operations, not necessarily the physical throughput of the underlying storage device.

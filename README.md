# Fast Large File Allocation

โปรแกรมนี้สาธิตวิธีสร้างไฟล์ขนาดใหญ่มากอย่างรวดเร็วโดยไม่จำเป็นต้องเขียนข้อมูลจริงลงดิสก์ทีละ byte

ตัวอย่างเช่น โปรแกรมสามารถสร้างไฟล์ขนาดหลาย GB ได้ภายในเวลาสั้นมาก เพราะขั้นตอนหลักไม่ได้ทำงานเหมือนการเขียนไฟล์ปกติ เช่น

```python
file.write(b"\x00" * 1024 * 1024 * 1024)
```

วิธีดังกล่าวต้องส่งข้อมูลจำนวนมหาศาลไปยัง filesystem และ storage จริง จึงใช้เวลาและ I/O สูง

โค้ดนี้ใช้แนวคิดที่ต่างออกไป คือ “กำหนดขนาดพื้นที่ของไฟล์” ผ่าน API ระดับ operating system แทนการเขียนข้อมูลทั้งหมดลงไป

---

## หลักการสำคัญ

สมมุติต้องการสร้างไฟล์ขนาด 100 GB

เราไม่จำเป็นต้องสร้าง buffer ขนาด 100 GB แล้วเขียนลงดิสก์

สิ่งที่สามารถทำได้คือ

1. สร้างไฟล์ว่าง
2. เลื่อนตำแหน่ง file pointer ไปยังตำแหน่งที่ต้องการ
3. ใช้ `SetEndOfFile()` เพื่อกำหนด logical size ของไฟล์
4. บน Windows ใช้ `SetFileValidData()` เพื่อบอกระบบว่า extent ของไฟล์สามารถถือว่าเป็น valid data ได้ โดยไม่ต้องเขียน zero ทุก byte

ดังนั้นเวลาที่ใช้จึงอาจใกล้เคียงกับเวลาที่ใช้จัดการ metadata มากกว่าการเขียนข้อมูลจำนวนหลายสิบ GB หรือหลายร้อย GB จริง ๆ

---

# ทำไมไฟล์ถึงใหญ่ได้ภายในเวลาประมาณ 1 วินาที?

จุดสำคัญอยู่ตรงนี้:

```python
k32.SetFilePointerEx(h, size, None, FILE_BEGIN)
k32.SetEndOfFile(h)
```

`SetFilePointerEx()` ไม่ได้เขียนข้อมูล

มันเพียงเปลี่ยนตำแหน่งของ file pointer ไปยัง offset ที่กำหนด

ตัวอย่างเช่น:

```text
0 ---------------------------- 1 GB
                              ^
                         file pointer
```

จากนั้น:

```python
SetEndOfFile()
```

จะทำให้ filesystem มองว่า EOF อยู่ที่ตำแหน่งนั้น

ผลลัพธ์คือไฟล์มี logical size เป็น 1 GB โดยไม่จำเป็นต้องส่งข้อมูล 1 GB ผ่าน `write()` แบบปกติ

แนวคิดนี้คล้ายกับการบอก filesystem ว่า

```text
"ไฟล์นี้มีขนาด 1 GB"
```

แทนที่จะบอกว่า

```text
"นี่คือข้อมูล 1 GB ที่ต้องเขียน"
```

ดังนั้นคำสั่งจึงไม่จำเป็นต้องใช้เวลาเท่ากับการเขียนข้อมูลจริงทั้งหมด

---

# Windows: `SetEndOfFile()` กับ `SetFileValidData()`

โค้ด Windows ใช้ API จาก `kernel32.dll`

```python
k32.SetFilePointerEx(...)
k32.SetEndOfFile(...)
k32.SetFileValidData(...)
```

## 1. SetFilePointerEx

```python
k32.SetFilePointerEx(h, size, None, FILE_BEGIN)
```

ฟังก์ชันนี้ย้าย file pointer ไปยัง offset ที่ต้องการ

ถ้า:

```python
size = 10 * GB
```

pointer จะถูกเลื่อนไปที่ประมาณ 10 GB

ยังไม่มีการเขียนข้อมูล 10 GB

---

## 2. SetEndOfFile

```python
k32.SetEndOfFile(h)
```

คำสั่งนี้กำหนด EOF ตามตำแหน่ง file pointer ปัจจุบัน

ดังนั้นหลังจาก:

```python
SetFilePointerEx(...)
SetEndOfFile(...)
```

ระบบสามารถเห็นไฟล์เป็น:

```text
test.bin
Size: 10 GB
```

แม้ว่าจะยังไม่ได้เขียนข้อมูลที่มีความยาว 10 GB แบบปกติ

---

## 3. SetFileValidData

ส่วนที่สำคัญที่สุดคือ:

```python
k32.SetFileValidData(h, size)
```

ฟังก์ชันนี้เป็น Windows-specific API สำหรับตั้งค่า valid data length ของไฟล์

โดยปกติ Windows อาจต้องรับประกันว่า logical file region ที่ถูกเปิดอ่านจะไม่ส่งข้อมูลเก่าจาก disk กลับมา ดังนั้นการขยายไฟล์บางรูปแบบอาจเกี่ยวข้องกับการ zero-initialize พื้นที่

`SetFileValidData()` สามารถหลีกเลี่ยงงาน zeroing บางส่วนได้ โดยบอกระบบว่า data range นี้ถือเป็น valid แล้ว

นี่เป็นเหตุผลสำคัญที่ทำให้การสร้างไฟล์ขนาดใหญ่สามารถทำได้เร็วมาก

แต่มีข้อแลกเปลี่ยนด้านความปลอดภัย:

ถ้าใช้ API นี้อย่างไม่ถูกต้อง ผู้ใช้หรือโปรแกรมอื่นอาจสามารถเห็นข้อมูลเดิมที่เคยอยู่ใน disk blocks ได้

ดังนั้น Windows จึงจำกัดสิทธิ์สำหรับการใช้งาน API นี้

---

# ทำไมโค้ดต้องเปิด `SeManageVolumePrivilege`?

โค้ดส่วนนี้:

```python
enable_privilege("SeManageVolumePrivilege")
```

ใช้ Windows token privilege เพื่อเปิดสิทธิ์:

```text
SeManageVolumePrivilege
```

Privilege นี้มีความเกี่ยวข้องกับการจัดการ volume และเป็นสิทธิ์ที่ Windows ใช้ควบคุมการทำงานลักษณะ `SetFileValidData()`

โค้ดจึงทำงานประมาณนี้:

```text
Process
   │
   ├── OpenProcessToken()
   │
   ├── LookupPrivilegeValueW()
   │
   └── AdjustTokenPrivileges()
          │
          └── Enable SeManageVolumePrivilege
```

จากนั้นจึงเรียก:

```python
SetFileValidData()
```

หาก privilege ไม่สามารถเปิดได้ โปรแกรมยังสามารถสร้างไฟล์ด้วย `SetEndOfFile()` ได้ แต่จะไม่ได้ใช้ fast path ของ valid-data allocation

จึงมีข้อความ:

```python
Mode: valid-data
```

หรือ

```python
Mode: eof-only
```

---

# อธิบาย `enable_privilege()`

ฟังก์ชัน:

```python
def enable_privilege(name: str) -> bool:
```

มีหน้าที่เปิด Windows privilege ให้กับ process ปัจจุบัน

เริ่มจากโหลด DLL:

```python
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
adv = ctypes.WinDLL("advapi32", use_last_error=True)
```

`kernel32.dll` ให้ API ที่เกี่ยวข้องกับ file และ process

`advapi32.dll` ให้ API ที่เกี่ยวข้องกับ security token และ privilege

จากนั้น:

```python
adv.OpenProcessToken(...)
```

ใช้เปิด access token ของ process ปัจจุบัน

ต่อมา:

```python
adv.LookupPrivilegeValueW(...)
```

ค้นหา LUID ของ privilege เช่น:

```text
SeManageVolumePrivilege
```

แล้วสร้าง:

```python
TOKEN_PRIVILEGES
```

พร้อม:

```python
SE_PRIVILEGE_ENABLED
```

สุดท้าย:

```python
adv.AdjustTokenPrivileges(...)
```

ใช้เปิด privilege ให้ process

---

# อธิบาย `ctypes.Structure`

Python ไม่มี native binding สำหรับ Windows API ทุกตัว จึงใช้ `ctypes` เพื่อเรียก C API โดยตรง

ตัวอย่าง:

```python
class LUID(ctypes.Structure):
    _fields_ = [
        ("LowPart", wintypes.DWORD),
        ("HighPart", ctypes.c_long)
    ]
```

โครงสร้างนี้จำลอง C structure ของ Windows

เช่นเดียวกับ:

```python
class LUID_AND_ATTRIBUTES(ctypes.Structure):
```

และ:

```python
class TOKEN_PRIVILEGES(ctypes.Structure):
```

เมื่อสร้าง structure เหล่านี้ Python สามารถส่ง memory layout ที่ Windows API ต้องการได้โดยตรง

---

# ฟังก์ชัน `alloc_nt()`

ฟังก์ชันนี้เป็นส่วนหลักของ Windows:

```python
def alloc_nt(path: Path, size: int) -> bool:
```

เริ่มจากประกาศ Windows API:

```python
CreateFileW
SetFilePointerEx
SetEndOfFile
SetFileValidData
CloseHandle
```

จากนั้นสร้างไฟล์:

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
```

ตรงนี้คือการเปิดหรือสร้างไฟล์

`CREATE_ALWAYS` หมายถึง ถ้ามีไฟล์เดิมอยู่จะสร้างใหม่โดยแทนที่ไฟล์เดิม

จากนั้น:

```python
k32.SetFilePointerEx(h, size, None, FILE_BEGIN)
```

เลื่อน pointer ไปตำแหน่ง `size`

ต่อด้วย:

```python
k32.SetEndOfFile(h)
```

กำหนดขนาด logical ของไฟล์

แล้วลอง:

```python
k32.SetFileValidData(h, size)
```

หากสำเร็จจะ return:

```python
True
```

---

# ทำไมไม่ใช้ `write()`?

วิธีทั่วไป:

```python
with open("test.bin", "wb") as f:
    f.write(b"\0" * size)
```

มีต้นทุนโดยตรงตามปริมาณข้อมูล

ถ้า:

```text
size = 1 GB
```

ต้องส่งข้อมูลประมาณ 1 GB

ถ้า:

```text
size = 100 GB
```

ต้องส่งข้อมูลประมาณ 100 GB

และยังขึ้นกับ:

* ความเร็ว SSD/HDD
* filesystem
* system cache
* CPU
* memory bandwidth
* storage controller
* I/O queue

ดังนั้นเวลาจะเพิ่มขึ้นตามปริมาณข้อมูลที่ต้องเขียนจริง

---

# Logical Size vs Physical Storage

นี่คือประเด็นสำคัญที่สุดของโปรแกรม

“ไฟล์มีขนาด 100 GB” ไม่ได้แปลว่า “ต้องใช้เวลาเขียนข้อมูล 100 GB”

filesystem สามารถจัดการ metadata ของไฟล์แยกจาก actual data blocks ได้

จึงต้องแยกคำว่า:

```text
Logical File Size
```

ออกจาก

```text
Physical Disk Allocation
```

Logical size คือสิ่งที่ระบบรายงานว่าไฟล์มีขนาดเท่าไร

Physical allocation คือจำนวน block ที่ถูกจัดสรรจริงบน storage

สำหรับวิธีการ allocation บางชนิด ทั้งสองค่านี้สามารถมีพฤติกรรมต่างกันได้

ดังนั้นการเห็น:

```text
test.bin = 100 GB
```

ไม่ได้หมายความว่าโปรแกรมเพิ่งเขียน zero 100 GB ลง disk

---

# Linux / POSIX

โค้ดมีอีก branch:

```python
if os.name == "nt":
    ...
else:
    ...
```

Linux และ Unix-like systems ใช้:

```python
os.posix_fallocate(fd, 0, size)
```

เมื่อมี API นี้

```python
os.posix_fallocate(fd, 0, size)
```

จะขอ filesystem ให้จัดสรรพื้นที่สำหรับไฟล์ตามขนาดที่กำหนด

หาก Python ไม่มี `posix_fallocate()` จะ fallback ไป:

```python
os.ftruncate(fd, size)
```

ซึ่งจะเปลี่ยนขนาดของไฟล์โดยตรง

อย่างไรก็ตาม semantics และ physical allocation ของแต่ละ filesystem อาจแตกต่างกัน ดังนั้น “สร้างไฟล์ได้เร็ว” ไม่ควรถูกตีความว่า storage ถูกจองและเขียนด้วยวิธีเดียวกันในทุกระบบ

---

# การคำนวณขนาด

โค้ดกำหนด:

```python
GB = 1 << 30
```

เท่ากับ:

```text
1,073,741,824 bytes
```

ซึ่งเป็น binary GiB แต่โค้ดเรียกมันว่า GB เพื่อความสะดวก

จากนั้น:

```python
RESERVE_BYTES = 1 * GB
```

หมายความว่าโปรแกรมจะเหลือพื้นที่ว่างอย่างน้อยประมาณ 1 GiB

การหาพื้นที่ว่าง:

```python
free = shutil.disk_usage(target.parent).free
```

แล้ว:

```python
total = max(0, free - RESERVE_BYTES)
```

สมมุติว่าพื้นที่ว่างคือ:

```text
50 GB
```

โปรแกรมจะพยายามสร้างไฟล์ประมาณ:

```text
49 GB
```

เพื่อไม่ให้ใช้พื้นที่ว่างทั้งหมดของ volume

---

# การวัดเวลา

โปรแกรมใช้:

```python
t0 = time.monotonic()
```

ก่อน allocation

และ:

```python
dt = time.monotonic() - t0
```

หลัง allocation

`time.monotonic()` เหมาะกับการวัด elapsed time เพราะไม่ขึ้นกับการเปลี่ยนแปลงของ system clock

จึงสามารถแสดงผลได้ เช่น:

```text
Done: 49.00 GB in 0.84s
```

ตัวเลขนี้ไม่ได้หมายความว่าโปรแกรมเขียนข้อมูลจริงด้วยความเร็ว:

```text
49 GB / 0.84s
```

เพราะสิ่งที่วัดคือ “เวลาของ operation ที่เรียก” ไม่ใช่ throughput ของการเขียนข้อมูลจริง 49 GB

---

# ทำไมเวลาอาจต่างกันในแต่ละเครื่อง?

ความเร็วขึ้นอยู่กับ filesystem และ storage implementation

ตัวอย่างเช่น:

```text
NTFS
ReFS
ext4
XFS
Btrfs
```

อาจมี behavior ต่างกัน

รวมถึง:

```text
SSD / HDD
Filesystem cache
Disk encryption
Virtual machine
Cloud storage
System permissions
Privilege
```

ดังนั้นไม่ควรสัญญาว่าจะได้ “1 วินาทีเสมอ”

คำอธิบายที่ถูกต้องกว่าคือ:

> Large logical file sizes can be created very quickly because the program avoids writing the entire file contents and instead relies on filesystem metadata/allocation mechanisms provided by the operating system.

---

# โครงสร้างการทำงานทั้งหมด

```text
main()
  │
  ├── ตรวจสอบ Desktop
  │
  ├── ตรวจสอบ disk usage
  │
  ├── คำนวณ target size
  │
  ├── Windows?
  │      │
  │      ├── Enable SeManageVolumePrivilege
  │      │
  │      ├── CreateFileW
  │      ├── SetFilePointerEx
  │      ├── SetEndOfFile
  │      └── SetFileValidData
  │
  └── POSIX?
         │
         ├── os.open()
         └── posix_fallocate()/ftruncate()
```

ดังนั้นแก่นของเทคนิคคือ:

```text
Do not write N GB of data.
Tell the filesystem that the file should have size N GB.
```

---

# ตัวอย่างแนวคิด

วิธีทั่วไป:

```python
data = b"\0" * (10 * GB)
file.write(data)
```

แนวคิดนี้คือ:

```text
RAM
 │
 │ 10 GB of data
 ▼
Filesystem
 │
 ▼
Disk
```

จึงต้องมีการส่งข้อมูลจำนวนมหาศาล

แต่ allocation approach เป็นลักษณะ:

```text
Python
 │
 │ file metadata operation
 ▼
Filesystem
 │
 └── logical size = 10 GB
```

จึงสามารถเร็วกว่ามาก

---

# ข้อควรระวัง

โปรแกรมนี้ควรใช้เพื่อการทดลองและศึกษาการทำงานของ filesystem เท่านั้น

โดยเฉพาะ:

```python
SetFileValidData()
```

ไม่ควรถูกมองว่าเป็นเพียง “วิธีสร้างไฟล์ใหญ่เร็วขึ้น” เพราะมันเกี่ยวข้องกับ security semantics ของ filesystem และ privilege ของ Windows

นอกจากนี้ การสร้างไฟล์ขนาดใหญ่มากอาจทำให้:

* disk space ลดลงอย่างรวดเร็ว
* โปรแกรมอื่นเขียนไฟล์ไม่ได้
* filesystem มี fragmentation
* ระบบเกิด I/O pressure
* เครื่อง virtual machine หรือ cloud disk ทำงานผิดไปจากที่คาดหวัง

ควรทดสอบบนพื้นที่ที่ไม่ได้เก็บข้อมูลสำคัญ

---

# สรุป

โค้ดนี้ไม่ได้มีความสามารถในการ “เขียนข้อมูลจำนวนหลาย GB ภายใน 1 วินาที” แบบมหัศจรรย์

สิ่งที่เกิดขึ้นคือมันลดงานจาก:

```text
สร้างข้อมูลจำนวนมหาศาล
+
ส่งข้อมูลผ่าน I/O
+
เขียนทุก block
```

เหลือประมาณ:

```text
สร้างไฟล์
+
เปลี่ยนตำแหน่ง EOF
+
จัดการ filesystem metadata/allocation
```

ดังนั้น operation จึงสามารถเสร็จได้เร็วมากเมื่อเทียบกับการเขียนข้อมูลจริง

ประเด็นที่ควรจำคือ:

```text
File Size != Amount of Data Physically Written
```

และ:

```text
Fast allocation != Fast real-world storage throughput
```

นี่เป็นเหตุผลทางเทคนิคว่าทำไมโปรแกรมจึงสามารถสร้างไฟล์ที่แสดงขนาดใหญ่มากได้ในเวลาเพียงประมาณหนึ่งวินาทีในบางสภาพแวดล้อม

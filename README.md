```
# Disk Space Filler

สคริปต์ Python สำหรับสร้างไฟล์ขนาดใหญ่เพื่อจองพื้นที่ว่างบนดิสก์จนเกือบเต็ม โดยเว้นพื้นที่สำรองไว้ตามที่กำหนด จุดเด่นคือบน Windows/NTFS จะจองพื้นที่ได้ในเวลาไม่ถึงวินาที แทนที่จะต้องเขียนข้อมูลจริงหลายสิบนาที

## การตั้งค่า

| ค่าคงที่ | ความหมาย | ค่าเริ่มต้น |
|---|---|---|
| `FILE_NAME` | ชื่อไฟล์ปลายทาง | `test.bin` |
| `RESERVE_BYTES` | พื้นที่ว่างที่จะกันไว้ไม่ให้ถูกจอง | `1 GB` |

ไฟล์จะถูกสร้างที่ `~/Desktop/<FILE_NAME>`

## ขั้นตอนการทำงาน

1. **หาปลายทางและสร้างโฟลเดอร์**
   ใช้ `Path.home() / "Desktop" / FILE_NAME` และเรียก `mkdir(parents=True, exist_ok=True)` กันกรณีไม่มีโฟลเดอร์

2. **คำนวณขนาดเป้าหมาย**
   อ่านพื้นที่ว่างด้วย `shutil.disk_usage()` แล้วคำนวณ `target = max(0, free - RESERVE_BYTES)` ถ้าเหลือ 0 จะจบการทำงานทันที

3. **ขอสิทธิ์ระบบ (เฉพาะ Windows)**
   `enable_privilege("SeManageVolumePrivilege")` เปิด privilege ผ่าน `OpenProcessToken` → `LookupPrivilegeValueW` → `AdjustTokenPrivileges`
   สิทธิ์นี้จำเป็นสำหรับขั้นตอนที่ 4 หากไม่ได้รันแบบ administrator จะขอไม่สำเร็จและสคริปต์จะตกไปใช้โหมดช้ากว่าโดยอัตโนมัติ

4. **จองพื้นที่**

   **Windows (`alloc_nt`)**
   - `CreateFileW` เปิด handle แบบ `CREATE_ALWAYS`
   - `SetFilePointerEx` เลื่อนตัวชี้ไฟล์ไปยังตำแหน่งขนาดเป้าหมาย
   - `SetEndOfFile` กำหนด EOF ทำให้ NTFS จองคลัสเตอร์ทันที พื้นที่ว่างลดลงทันทีโดยยังไม่มีการเขียนข้อมูลจริง
   - `SetFileValidData` ดัน Valid Data Length ให้เท่ากับขนาดไฟล์ ข้ามขั้นตอน zero-fill ของระบบทั้งหมด คืนค่าสำเร็จ = โหมด `valid-data`, ล้มเหลว = โหมด `eof-only`

   **Linux / macOS (`alloc_posix`)**
   - ใช้ `os.posix_fallocate()` จองบล็อกจริงบน ext4/XFS/Btrfs
   - หากระบบไม่รองรับ จะถอยไปใช้ `os.ftruncate()`

5. **รายงานผล**
   พิมพ์โหมดที่ใช้, ขนาดไฟล์จริงจาก `stat().st_size`, เวลาที่ใช้ และพื้นที่ว่างคงเหลือหลังทำงาน

## โหมดการทำงานบน Windows

| โหมด | เงื่อนไข | ความเร็ว | เนื้อหาไฟล์ |
|---|---|---|---|
| `valid-data` | ได้ `SeManageVolumePrivilege` | < 1 วินาที | ข้อมูลเดิมที่ค้างอยู่บนดิสก์ |
| `eof-only` | ไม่ได้สิทธิ์ | ช้า ระบบ zero-fill ให้ | ศูนย์ทั้งหมด |

## วิธีใช้

```

py [main.py](http://main.py)

```

เปิด Command Prompt แบบ **Run as administrator** เพื่อให้ได้โหมด `valid-data`

## ตัวอย่างผลลัพธ์

```

Free:   214.36 GB

Target: 213.36 GB

Output: C:UsersuserDesktoptest.bin

Mode:   valid-data (privilege: on)

Done:   213.36 GB in 0.03s

Free:   1.00 GB

```

## ข้อควรทราบ

- โหมด `valid-data` ทำให้ไฟล์เข้าถึงข้อมูลที่ยังไม่ถูกลบออกจากดิสก์ได้ ควรใช้เฉพาะเครื่องของตนเอง
- ระบบไฟล์ exFAT/FAT32 และไดรฟ์เครือข่ายไม่รองรับการจองแบบทันที จะใช้เวลานานกว่ามาก
- FAT32 จำกัดขนาดไฟล์เดียวไม่เกิน 4 GB
- โฟลเดอร์ที่ซิงก์กับ OneDrive อาจถูกอัปโหลดไฟล์ขึ้นคลาวด์ ควรเปลี่ยนปลายทางเป็นพาธนอกโฟลเดอร์ซิงก์
- ลบไฟล์เพื่อคืนพื้นที่: `del "%USERPROFILE%\Desktop\test.bin"`

## ความต้องการ

- Python 3.8 ขึ้นไป
- ไม่ต้องติดตั้งไลบรารีเพิ่ม ใช้เฉพาะ standard library (`ctypes`, `os`, `shutil`, `time`, `pathlib`)
```

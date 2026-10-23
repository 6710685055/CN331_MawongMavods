# CN331 Mawong Mavods — US-02 การนัดหมายประชุมและการแจ้งเตือน

## เกี่ยวกับ branch นี้

branch `issue-2-group-meeting-notification` พัฒนา **Use Case 2 (US-02): Group Meeting & Notification** สมาชิกกลุ่มที่เข้าสู่ระบบสามารถสร้างนัดหมายโดยระบุหัวข้อ ลิงก์ประชุม และวันเวลา ดูนัดหมายที่กำลังจะมาถึงในพื้นที่ของกลุ่ม และแก้ไขหรือเลื่อนนัดหมายได้ เมื่อมีการเปลี่ยนแปลง ระบบจะสร้างการแจ้งเตือนภายในแอปให้สมาชิกในกลุ่ม และมีคำสั่งสำหรับส่งการแจ้งเตือนก่อนถึงเวลาประชุม

**User Story:** ในฐานะสมาชิกกลุ่ม ฉันต้องการสร้างและจัดการนัดหมายประชุม เพื่อให้สมาชิกทุกคนทราบว่าจะประชุมเมื่อใดและที่ใด

> **หมายเหตุการเชื่อมต่อ:** branch นี้ยังไม่มีโมเดลกลุ่มทำงานจาก US-01 จึงใช้ Django `Group` ผ่าน adapter ใน `meetings/group_access.py` ชั่วคราว เมื่อนำ US-01 เข้ามารวม อาจต้องปรับ adapter ให้เชื่อมกับโมเดลกลุ่มของโปรเจกต์

## Getting Started (การตั้งค่าโปรเจกต์เริ่มต้น)

### 1. เทคโนโลยีหลัก

| ส่วน | เทคโนโลยี |
|---|---|
| ภาษา | Python 3.10 ขึ้นไป (แนะนำ Python 3.12) |
| Web framework | Django 5.x |
| ฐานข้อมูล | SQLite (`db.sqlite3`) |
| ส่วนติดต่อผู้ใช้ | Django templates ไม่ต้อง build frontend แยกหรือใช้ Node.js |
| การแจ้งเตือน | แอป `notifications` ที่มีอยู่ในโปรเจกต์ |

### 2. สิ่งที่ต้องมีก่อนติดตั้ง (Prerequisites)

- Git
- Python 3.10 ขึ้นไป
- PowerShell บน Windows หรือ Terminal บน macOS/Linux

ตรวจสอบโปรแกรมที่ติดตั้งแล้ว:

~~~powershell
python --version
git --version
~~~

### 3. ขั้นตอนการติดตั้ง (Installation)

Clone branch นี้จาก GitHub:

~~~powershell
git clone --branch issue-2-group-meeting-notification --single-branch https://github.com/6710685055/CN331_MawongMavods.git
cd CN331_MawongMavods
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
~~~

หาก clone repository ไว้แล้ว ให้เปลี่ยนมาใช้ branch นี้:

~~~powershell
git fetch origin
git switch issue-2-group-meeting-notification
~~~

คำสั่งสร้างและเปิดใช้งาน virtual environment บน macOS/Linux:

~~~bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
~~~

หาก PowerShell ไม่อนุญาตให้ activate environment ให้เรียก Python ใน venv โดยตรง:

~~~powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
~~~

### 4. การตั้งค่า Environment Variables

Django อ่านค่าต่อไปนี้จาก environment ของระบบ โดยโปรเจกต์ **ไม่ได้โหลดไฟล์ .env ให้อัตโนมัติ**

| ตัวแปร | ค่าเริ่มต้นสำหรับพัฒนา | จุดประสงค์ |
|---|---|---|
| `DJANGO_SECRET_KEY` | `dev-only-change-me` | กุญแจสำหรับ Django; ตั้งค่าเฉพาะของตนเองเมื่อใช้งานนอกเครื่องพัฒนา |
| `DJANGO_DEBUG` | `1` | เปิดโหมด debug เมื่อกำหนดเป็น `1` |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | รายชื่อ host ที่คั่นด้วย comma |

ตั้งค่าตัวแปรใน PowerShell ก่อนเริ่ม Django ได้ดังนี้:

~~~powershell
$env:DJANGO_SECRET_KEY = "your-private-development-key"
$env:DJANGO_DEBUG = "1"
$env:DJANGO_ALLOWED_HOSTS = "localhost,127.0.0.1"
~~~

บน macOS/Linux ใช้คำสั่ง:

~~~bash
export DJANGO_SECRET_KEY="your-private-development-key"
export DJANGO_DEBUG="1"
export DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1"
~~~

สำหรับการพัฒนาในเครื่อง ระบบเขียนอีเมลยืนยันและรีเซ็ตรหัสผ่านลงใน Terminal ที่รัน `runserver` จึงไม่ต้องใช้บัญชี SMTP เพื่อทดลอง US-02 ห้าม commit รหัสผ่าน app password หรือ credential จริง

### 5. การจัดการฐานข้อมูล (Database Setup)

โปรเจกต์ใช้ SQLite ใช้ migration ที่มีใน repository เพื่อสร้างหรือปรับปรุงฐานข้อมูล `db.sqlite3`:

~~~powershell
python manage.py migrate
python manage.py seed_courses
python manage.py createsuperuser
~~~

คำสั่ง `seed_courses` เพิ่มรายวิชาตัวอย่างและรันซ้ำได้ ส่วน `createsuperuser` ใช้สร้างบัญชีผู้ดูแลระบบสำหรับหน้า `/admin/`

สำหรับทดลอง US-02 ในเครื่อง ให้สร้าง Django **Group** ที่หน้า `/admin/` และเพิ่มบัญชีทดสอบเป็นสมาชิก จากนั้นสมาชิกจึงจะเปิดพื้นที่นัดหมายของกลุ่มได้ วิธีนี้เป็น adapter ชั่วคราวระหว่างรอเชื่อมโมเดลกลุ่มจาก US-01

### 6. คำสั่งรันโปรเจกต์ (Running the Project)

เริ่ม development server:

~~~powershell
python manage.py runserver
~~~

เปิด <http://127.0.0.1:8000/> แล้วเข้าสู่ระบบด้วยบัญชีทดสอบที่ยืนยันอีเมลแล้ว

| หน้า | URL |
|---|---|
| นัดหมายที่กำลังจะมาถึง | <http://127.0.0.1:8000/meetings/> |
| หน้าผู้ดูแลระบบ (จัดการกลุ่มทดสอบ) | <http://127.0.0.1:8000/admin/> |

จากหน้ารวมนัดหมาย ให้เปิดพื้นที่ของกลุ่มเพื่อสร้างนัดหมาย ลิงก์ประชุมต้องเป็น URL ที่ขึ้นต้นด้วย `http://` หรือ `https://` และเวลาประชุมต้องอยู่ในอนาคต เมื่อแก้ไขนัดหมาย ระบบจะสร้างการแจ้งเตือนภายในแอปให้สมาชิกกลุ่ม

### 7. คำสั่งเพิ่มเติม

ตรวจสอบการตั้งค่า Django และรันชุดทดสอบ:

~~~powershell
python manage.py check
python manage.py test
~~~

ตรวจสอบว่ามี model ที่ต้องสร้าง migration หรือไม่:

~~~powershell
python manage.py makemigrations --check --dry-run
~~~

ส่งการแจ้งเตือนสำหรับนัดหมายที่เข้าสู่ช่วงเวลาเตือน:

~~~powershell
python manage.py send_meeting_reminders
~~~

ค่าเริ่มต้นของช่วงเวลาเตือนคือ 15 นาที (`MEETING_REMINDER_MINUTES`) Django ไม่ได้เรียกคำสั่งนี้ให้อัตโนมัติ หากต้องการส่งอัตโนมัติให้ตั้งเวลารันคำสั่งนี้ทุกหนึ่งนาที เช่น ใช้ Windows Task Scheduler ดูรายละเอียดการออกแบบและการตั้งค่าการเตือนได้ที่ [docs/meeting_uc2.md](docs/meeting_uc2.md)

## เกณฑ์การยอมรับ (Acceptance Criteria) → อยู่ที่ไฟล์ใด

| เกณฑ์การยอมรับ | ตำแหน่งที่พัฒนา |
|---|---|
| สมาชิกกลุ่มสร้างนัดหมายได้ | `meetings/views.py`, `meetings/permissions.py`, `meetings/group_access.py`, `templates/meetings/meeting_form.html` |
| ระบุหัวข้อ ลิงก์ วัน และเวลาประชุมได้ | `meetings/forms.py`, `meetings/models.py` |
| แสดงนัดหมายที่กำลังจะมาถึงในพื้นที่กลุ่ม | `meetings/selectors.py`, `templates/meetings/group_meetings.html` |
| แสดงนัดหมายถัดไปไว้บนสุด | `templates/meetings/group_meetings.html` |
| สมาชิกแก้ไขหรือเลื่อนนัดหมายได้ | `meetings/views.py`, `meetings/services.py`, `templates/meetings/meeting_form.html` |
| แจ้งสมาชิกกลุ่มเมื่อมีการเปลี่ยนแปลงนัดหมาย | `meetings/services.py`, `notifications/services.py`, `notifications/models.py` |
| แจ้งเตือนสมาชิกก่อนถึงเวลาประชุม | `meetings/services.py`, `meetings/management/commands/send_meeting_reminders.py`; ตั้งเวลารันคำสั่งทุกหนึ่งนาที |
| ปฏิเสธ URL ที่ไม่ถูกต้องและเวลาประชุมในอดีต | `meetings/forms.py` |

## โครงสร้างไฟล์ของ US-02

~~~text
meetings/                 โมเดล ฟอร์ม views services และ adapter สำหรับเข้าถึงกลุ่ม
meetings/migrations/      migration ของ Meeting
meetings/management/      คำสั่งส่งการแจ้งเตือนก่อนประชุม
templates/meetings/       หน้ารวมนัดหมาย พื้นที่กลุ่ม และฟอร์มนัดหมาย
notifications/            ระบบแจ้งเตือนภายในแอปและชนิดแจ้งเตือนของนัดหมาย
docs/meeting_uc2.md       เอกสารออกแบบและเกณฑ์การยอมรับของ UC2
~~~

## ฟีเจอร์เดิมจาก branch ฐาน

branch นี้ต่อยอดจากงานรายวิชาและเอกสารของทีม โดยมีฟีเจอร์เดิมดังนี้:

- **US-07:** สมัครสมาชิก ยืนยันอีเมล เข้าสู่ระบบ รีเซ็ตรหัสผ่าน และลงทะเบียนรายวิชา อยู่ใน `accounts/` และ `courses/`
- **US-03 / US-04:** อัปโหลดและแชร์เอกสาร ปักหมุด และตรวจสอบเอกสาร อยู่ใน `documents/` ดูรายละเอียดที่ [docs/documents_uc3_uc4.md](docs/documents_uc3_uc4.md)
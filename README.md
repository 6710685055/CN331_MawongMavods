# CN331_MawongMavods — UC3, UC4 & UC7

Django 5 implementation of:
- **UC7 (US-07)**: Registration, Email Verification, Login, Password Reset & Course Enrollment
- **UC3**: Upload & Share Document (การอัปโหลดและแชร์เอกสาร + การปักหมุดโดย TA/Teacher)
- **UC4**: Verify Document (การตรวจสอบและยืนยันเอกสาร + คิวรอตรวจ + ส่งกลับให้แก้ไข + ยกเลิก Verify + แจ้งเตือน)

## Getting Started (การตั้งค่าโปรเจคเริ่มต้น)

### Quick Start

ถ้ามี Python 3.10 ขึ้นไปและ Git อยู่แล้ว คัดลอกชุดคำสั่งของระบบปฏิบัติการตัวเองไปรันได้เลย รายละเอียดแต่ละขั้นอยู่ในหัวข้อถัดไป

**Windows (PowerShell)**

```powershell
git clone https://github.com/6710685055/CN331_MawongMavods.git
cd CN331_MawongMavods
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_courses
python manage.py createsuperuser
python manage.py runserver
```

> ถ้า `Activate.ps1` ขึ้น error เรื่อง execution policy ให้รัน `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` หนึ่งครั้ง แล้ว activate ใหม่

**macOS / Linux (bash / zsh)**

```bash
git clone https://github.com/6710685055/CN331_MawongMavods.git
cd CN331_MawongMavods
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_courses
python manage.py createsuperuser
python manage.py runserver
```

เสร็จแล้วเปิดใช้งานได้ที่:
- เว็บ: <http://127.0.0.1:8000/>
- หน้า Admin: <http://127.0.0.1:8000/admin/>

### 1. เทคโนโลยีหลัก

| ส่วน | เทคโนโลยี |
|---|---|
| ภาษา | Python 3.12 (รองรับ 3.10 ขึ้นไป) |
| Web framework | Django 5.2 (`Django>=5.0,<6.0`) |
| ฐานข้อมูล | SQLite (`db.sqlite3` ที่ root ของโปรเจค) |
| หน้าเว็บ | Django Templates (`templates/`) |
| อีเมล | Gmail SMTP (ตั้งค่าใน `config/settings.py`) |

โปรเจคนี้ **ไม่มี frontend แยก** (ไม่ต้องใช้ Node.js หรือ `npm`) และ **ยังไม่มี Docker**

### 2. สิ่งที่ต้องมีก่อนติดตั้ง (Prerequisites)

- Python 3.10 ขึ้นไป (แนะนำ 3.12)
- Git

```bash
python --version   # macOS / Linux อาจต้องใช้ python3 --version
git --version
```

### 3. ขั้นตอนการติดตั้ง (Installation)

```bash
git clone https://github.com/6710685055/CN331_MawongMavods.git
cd CN331_MawongMavods
```

สร้างและเปิดใช้ Virtual Environment:

```powershell
# Windows (PowerShell)
python -m venv venv
venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

ติดตั้ง dependency:

```bash
pip install -r requirements.txt
```

เมื่อ activate แล้วจะมี `(venv)` นำหน้า prompt คำสั่ง `python manage.py ...` ทุกคำสั่งหลังจากนี้ต้องรันใน venv ที่ root ของโปรเจค

### 4. การตั้งค่า Environment Variables

ตอนพัฒนาในเครื่อง **ไม่ต้องตั้งค่าอะไร** เพราะทุกตัวมีค่าเริ่มต้นสำหรับ dev อยู่แล้ว

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `DJANGO_SECRET_KEY` | `dev-only-change-me` | Secret key ของ Django (ต้องเปลี่ยนเมื่อ deploy จริง) |
| `DJANGO_DEBUG` | `1` | `1` = เปิด debug, ค่าอื่น = ปิด |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Host ที่อนุญาต คั่นด้วย `,` |

โปรเจค **ยังไม่อ่านไฟล์ `.env` อัตโนมัติ** ถ้าต้องการเปลี่ยนค่า ให้ตั้งใน shell ก่อนรันคำสั่ง:

```powershell
# Windows (PowerShell)
$env:DJANGO_SECRET_KEY = "your-secret-key"
$env:DJANGO_DEBUG = "0"
$env:DJANGO_ALLOWED_HOSTS = "localhost,127.0.0.1"
```

```bash
# macOS / Linux
export DJANGO_SECRET_KEY="your-secret-key"
export DJANGO_DEBUG="0"
export DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1"
```

**อีเมล (ยืนยันอีเมลและรีเซ็ตรหัสผ่าน):** ใช้ Gmail SMTP ตามค่าใน `config/settings.py` ดังนั้นตอนสมัครสมาชิก ระบบจะส่งอีเมลจริง
- ถ้าไม่อยากส่งอีเมลจริงตอน dev ให้เปลี่ยน `EMAIL_BACKEND` ในเครื่องตัวเองเป็น `"django.core.mail.backends.console.EmailBackend"` ชั่วคราว อีเมลจะพิมพ์ออกมาใน terminal ที่รัน `runserver` แทน (**อย่า commit การแก้นี้**)
- หรือข้ามการยืนยันอีเมลไปเลย โดยเข้าหน้า Admin แล้วติ๊ก `email_verified` ให้ผู้ใช้คนนั้น

### 5. การจัดการฐานข้อมูล (Database Setup)

ไฟล์ migration ถูก commit ไว้แล้ว ไม่ต้องรัน `makemigrations`

```bash
python manage.py migrate            # สร้างตารางทั้งหมดใน db.sqlite3
python manage.py seed_courses       # เพิ่มรายวิชาตัวอย่าง (CN331, CN240, CN201, CN202, CN310) รันซ้ำได้ไม่เกิดข้อมูลซ้ำ
python manage.py createsuperuser    # สร้างบัญชี Admin: ถามอีเมล, Name, Surname และรหัสผ่าน
```

#### รีเซ็ต Database (เริ่มใหม่จากศูนย์)

> ⚠️ ข้อมูลทั้งหมดจะหาย ทั้งผู้ใช้ การลงทะเบียน เอกสาร และการแจ้งเตือน

1. หยุด `runserver` ก่อน (กด `Ctrl+C`)
2. ลบไฟล์ `db.sqlite3`
3. **ต้องรัน `migrate` และ `seed_courses` อีกรอบ** ระบบจึงจะกลับมามีตารางและรายวิชาให้ใช้งาน
4. สร้าง superuser ใหม่ เพราะบัญชี Admin เดิมหายไปพร้อมฐานข้อมูล

```powershell
# Windows (PowerShell)
Remove-Item db.sqlite3
python manage.py migrate
python manage.py seed_courses
python manage.py createsuperuser
```

```bash
# macOS / Linux
rm db.sqlite3
python manage.py migrate
python manage.py seed_courses
python manage.py createsuperuser
```

ไฟล์เอกสารที่เคยอัปโหลดในโฟลเดอร์ `media/` จะไม่ถูกลบตามไปด้วย ถ้าต้องการล้างด้วย ให้ลบเองด้วย `Remove-Item -Recurse media` (Windows) หรือ `rm -rf media` (macOS / Linux)

### 6. คำสั่งรันโปรเจค (Running the Project)

```bash
python manage.py runserver
```

| หน้า | URL |
|---|---|
| หน้าแรก (redirect ไป "วิชาของฉัน") | <http://127.0.0.1:8000/> |
| สมัครสมาชิก | <http://127.0.0.1:8000/accounts/register/> |
| เข้าสู่ระบบ | <http://127.0.0.1:8000/accounts/login/> |
| การแจ้งเตือน | <http://127.0.0.1:8000/notifications/> |
| **หน้า Admin** | **<http://127.0.0.1:8000/admin/>** |

**หน้า Admin** (<http://127.0.0.1:8000/admin/>) ล็อกอินด้วยอีเมลและรหัสผ่านของ superuser ที่สร้างในขั้นตอนที่ 5 ใช้สำหรับ:
- **อนุมัติบัญชีอาจารย์:** Users → เลือกผู้ใช้ → action "อนุมัติบัญชีอาจารย์ที่เลือก" (อาจารย์ต้องได้รับอนุมัติก่อนจึงจะลงทะเบียนรายวิชาได้)
- **เลื่อน TA ให้มีสิทธิ์ตรวจเอกสาร:** Enrollments → เปลี่ยน role จาก "TA (รออาจารย์อนุมัติ)" เป็น "TA" (หน้าจอให้อาจารย์อนุมัติ TA เป็นงานของ UC16)
- ติ๊ก `email_verified` ให้ผู้ใช้ เมื่อไม่ได้ตั้งค่าอีเมล
- จัดการรายวิชา เอกสาร ประวัติการตรวจ และการแจ้งเตือน

ฝั่ง frontend **ไม่ต้องรันแยก** หน้าเว็บ render ผ่าน Django Templates ใน `runserver` ตัวเดียว

### 7. คำสั่งเพิ่มเติม

**รัน Test**

```bash
python manage.py test                                     # ทั้งโปรเจค
python manage.py test accounts                            # รายแอป: accounts / courses / documents
python manage.py test documents.tests.test_uc3_upload     # เฉพาะ UC3
python manage.py test documents.tests.test_uc4_verify     # เฉพาะ UC4
```

ตอนรัน test ระบบไม่ส่งอีเมลจริงและไม่เขียนไฟล์ลง `media/`

**ตรวจความเรียบร้อยก่อนเปิด PR**

```bash
python manage.py check                              # ต้องไม่มี issue
python manage.py makemigrations --check --dry-run   # ต้องได้ "No changes detected" ถ้าไม่ได้ตั้งใจแก้ model
```

**เอกสารเทคนิค:** การทำงานของ UC3/UC4 อธิบายไว้ใน [`docs/documents_uc3_uc4.md`](docs/documents_uc3_uc4.md)

**Docker:** ยังไม่มีในโปรเจคนี้

## Acceptance Criteria → where it is done

### UC7: Registration, Login & Course Enrollment
| AC | Where |
|---|---|
| Register with any email, choose Student/TA/Teacher | `accounts/forms.py: RegisterForm` |
| Duplicate email not allowed | `RegisterForm.clean_email` (case-insensitive) |
| Verification email; login only after verifying | `accounts/views.py`, `tokens.py`, `EmailLoginForm.confirm_login_allowed` |
| Student usable right after verifying | `User.email_verified` |
| TA has no TA rights until the teacher approves | `Enrollment.Role.TA_PENDING` (promotion = UC16) |
| Teacher is "pending" until Admin approves | `User.teacher_status`, `accounts/admin.py` |
| Search and enroll in courses | `courses/views.py`, `courses/services.py` |
| Reset password by email | `accounts/urls.py` (Django built-in views) |

### UC3: Upload & Share Document
| AC | Where |
|---|---|
| เฉพาะผู้ที่ลงทะเบียนในรายวิชาอัปโหลดได้ และตรวจสิทธิ์ฝั่ง Server | `courses/permissions.py: is_course_member`, `documents/permissions.py: can_access_course_documents`, `documents/services/library.py: upload_document` |
| ผู้ใช้ต้องระบุชื่อ ประเภท ปีการศึกษา/เทอม และแนบไฟล์ก่อนยืนยัน | `documents/forms.py: DocumentUploadForm`, `templates/documents/upload.html` |
| ระบบรับเฉพาะ PDF, DOCX, PPTX, PNG, JPG ขนาดไม่เกิน 50MB พร้อมบอกเหตุผล | `config/settings.py`, `documents/validators.py: validate_document_file` |
| เอกสารที่อัปโหลดสำเร็จแสดงในคลังเอกสาร และผู้ที่ลงทะเบียนในวิชานั้นดาวน์โหลดได้ | `documents/views/library.py: document_library, download_document` |
| ผู้ที่ไม่ได้ลงทะเบียนในวิชาเข้าถึงเอกสารไม่ได้ | `documents/views/library.py` (`403 Forbidden`), `documents/services/library.py` |
| บันทึกผู้อัปโหลด วันเวลา และตั้งคะแนนโหวตเริ่มต้นเป็น 0 | `documents/models.py: Document`, `documents/services/library.py: upload_document` |
| ชีทสรุปและแนวข้อสอบเริ่มต้นด้วยสถานะ "รอตรวจ" ส่วนการบ้านไม่มีสถานะ Verify | `Document.initial_verify_status_for_type`, `Document.VERIFIABLE_DOC_TYPES` |
| การอัปโหลดการบ้านต้องยืนยันก่อนว่าเป็นงานที่หมดกำหนดส่งแล้ว | `DocumentUploadForm.clean`, `documents/services/library.py: upload_document` |
| การอัปโหลดที่ล้มเหลวต้องไม่ทิ้งรายการค้างในคลังเอกสาร | `documents/services/library.py: upload_document` (`transaction.atomic` + file cleanup) |
| TA หรือ Teacher ของรายวิชาปักหมุดและเลิกปักหมุดเอกสารได้ และแสดงบนสุด | `documents/permissions.py: can_pin_document`, `documents/services/library.py: toggle_document_pin, list_course_documents` |
| ผู้ที่ไม่ใช่ TA หรือ Teacher ของวิชานั้นปักหมุดไม่ได้ | `documents/permissions.py: can_pin_document`, `documents/services/library.py: toggle_document_pin` |

### UC4: Verify Document
| AC | Where |
|---|---|
| เฉพาะ TA ที่ได้รับอนุมัติและ Teacher ผู้สอนของวิชานั้นเข้าถึงคิว "เอกสารรอตรวจ" และปุ่ม Verify ได้ (ตรวจฝั่ง Server) | `documents/permissions.py: can_access_review_queue, can_verify_document`, `documents/services/review.py` |
| คิวแสดงเฉพาะชีทสรุปและแนวข้อสอบสถานะ "รอตรวจ" เรียงจากเก่าสุด | `documents/services/review.py: get_verification_queue` |
| เมื่อกด Verify เอกสารแสดงป้าย "Verified by TA" หรือ "Verified by Teacher" พร้อมชื่อผู้ตรวจและวันที่ | `documents/models.py: Document.verified_badge_label`, `documents/services/review.py: verify_document` |
| การ Verify ผูกกับเวอร์ชันไฟล์ เมื่อเจ้าของแก้ไฟล์ ป้ายถูกยกเลิกและกลับเข้าคิว | `documents/models.py: Document.has_active_verified_badge`, `documents/services/versioning.py: replace_document_file` |
| การส่งกลับให้แก้ไขต้องมีความคิดเห็น และสถานะเปลี่ยนเป็น "ต้องแก้ไข" | `documents/forms.py: RequestRevisionForm`, `documents/services/review.py: request_document_revision` |
| ความคิดเห็นของผู้ตรวจ และสถานะ "รอตรวจ" / "ต้องแก้ไข" เห็นเฉพาะเจ้าของเอกสาร TA และ Teacher ของวิชา ผู้ใช้อื่นเห็นเฉพาะป้าย Verified | `documents/permissions.py: can_view_review_details`, `templates/documents/library.html`, `templates/documents/detail.html` |
| เจ้าของได้รับแจ้งเตือนทุกครั้งที่เอกสารถูก Verify ส่งกลับให้แก้ไข หรือยกเลิก Verify | `notifications/services.py: send_notification`, `documents/services/review.py` |
| ผู้ตรวจยกเลิก Verify ได้ โดยต้องระบุเหตุผล | `documents/forms.py: RevokeVerifyForm`, `documents/services/review.py: revoke_document_verification` |
| ผู้ตรวจต้อง Verify เอกสารที่ตนเองอัปโหลดไม่ได้ | `documents/permissions.py: can_verify_document`, `documents/services/review.py: get_verification_queue, verify_document` |
| ป้ายที่ให้ไว้คงอยู่แม้ผู้ตรวจถูกถอนสิทธิ์ TA ภายหลัง | `Document.verified_by_name`, `Document.verified_by_role` (Snapshot fields) |
| เอกสารประเภทการบ้านต้อง Verify ไม่ได้ | `Document.is_verifiable`, `documents/services/review.py` |

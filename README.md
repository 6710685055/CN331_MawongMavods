# CN331 MawongMavods

เว็บแอปสำหรับค้นหารายวิชาและลงทะเบียนเรียน พัฒนาด้วย Django ส่วนบัญชีผู้ใช้รองรับสมัครสมาชิก เข้าสู่ระบบ ยืนยันอีเมล และขอเปลี่ยนรหัสผ่าน

เอกสารนี้อธิบายโครงสร้างและเส้นทางการทำงานของโค้ด โดยเน้นส่วน **Login / Register** เพื่อให้สมาชิกในทีมรับช่วงพัฒนาต่อได้

## สแต็กและแนวทางของโปรเจกต์

- Python 3.10 ขึ้นไป และ Django 5.x
- SQLite เป็นฐานข้อมูลสำหรับพัฒนา
- Django Templates แสดง HTML ฝั่งเซิร์ฟเวอร์ ไม่มี React/Vue หรือ build step ของ frontend
- CSS ปัจจุบันเขียนรวมไว้ใน `templates/base.html`
- `accounts` รับผิดชอบผู้ใช้และ authentication ส่วน `courses` รับผิดชอบรายวิชาและการลงทะเบียน
- ภาษาและ timezone ตั้งเป็นไทยและ `Asia/Bangkok`

## เริ่มโปรเจกต์ในเครื่อง

```bash
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                 # Windows: copy .env.example .env
```

เปิด `.env` แล้วกำหนด `DJANGO_SECRET_KEY`, `EMAIL_HOST_USER` และ `EMAIL_HOST_PASSWORD` หากจะทดสอบส่งอีเมลจริง สำหรับ Gmail ให้ใช้ App Password และเก็บ `.env` ไว้ในเครื่อง ห้าม commit ไฟล์นี้

```bash
python manage.py migrate
python manage.py seed_courses
python manage.py createsuperuser
python manage.py runserver
```

เปิดเว็บที่ `http://127.0.0.1:8000/` คำสั่ง `seed_courses` เพิ่มวิชาตัวอย่างโดยไม่สร้างซ้ำ ส่วน `createsuperuser` ใช้อีเมลเป็นชื่อบัญชีผู้ดูแลระบบ การเปลี่ยน model ต้องสร้าง migration ด้วย `python manage.py makemigrations` แล้วนำไปใช้ด้วย `python manage.py migrate`

## ภาพรวมโครงสร้าง

```text
.
├── manage.py                         # จุดเริ่มคำสั่ง Django
├── requirements.txt                  # dependencies Python
├── .env.example                      # ตัวอย่างตัวแปรแวดล้อม (ไม่มี secret จริง)
├── config/
│   ├── settings.py                   # apps, database, templates, email, auth redirects
│   ├── urls.py                       # route ระดับโปรเจกต์
│   └── wsgi.py                       # entry point สำหรับ WSGI deployment
├── accounts/
│   ├── models.py                     # custom User, role, สถานะยืนยัน/อนุมัติ
│   ├── forms.py                      # RegisterForm, EmailLoginForm, form ส่งลิงก์ยืนยันซ้ำ
│   ├── views.py                      # register, login, verify email และ resend
│   ├── urls.py                       # route ของบัญชีและ Django password reset views
│   ├── emails.py                     # สร้างและส่งอีเมลยืนยัน
│   ├── tokens.py                     # สร้าง/ตรวจ token ยืนยันอีเมลแบบมีอายุ
│   ├── admin.py                      # จัดการผู้ใช้และอนุมัติบัญชีอาจารย์
│   ├── tests.py                      # tests ของบัญชีและ authentication
│   └── migrations/                   # schema ของ User ในฐานข้อมูล
├── courses/
│   ├── models.py                     # Course และ Enrollment
│   ├── views.py                      # ค้นหาวิชา ลงทะเบียน และดูวิชาของฉัน
│   ├── services.py                   # กฎสิทธิ์และการลงทะเบียน
│   ├── urls.py                       # route ของรายวิชา
│   ├── admin.py                      # จัดการข้อมูลผ่าน Django admin
│   ├── tests.py                      # tests ของรายวิชาและ enrollment
│   ├── migrations/                   # schema ของ Course/Enrollment
│   └── management/commands/
│       └── seed_courses.py           # เพิ่มข้อมูลรายวิชาตัวอย่าง
└── templates/
    ├── base.html                     # layout, navigation, messages และ CSS กลาง
    ├── partials/form.html            # วาด field, help text และ validation errors
    ├── accounts/                     # หน้า register/login/verify/password reset
    └── courses/                      # หน้าค้นหารายวิชาและรายวิชาของฉัน
```

## วิธีไล่โค้ด Login / Register

โดยทั่วไปให้ไล่ตามเส้นทางนี้:

1. **URL** ใน `accounts/urls.py` เชื่อม path กับ view หรือ Django generic view
2. **View** ใน `accounts/views.py` รับ request และเลือกว่าจะบันทึกข้อมูล ส่งอีเมล หรือ render template
3. **Form** ใน `accounts/forms.py` ตรวจข้อมูลและจัดการ validation
4. **Model** ใน `accounts/models.py` นิยามข้อมูลผู้ใช้และบันทึกลงฐานข้อมูล
5. **Template** ใน `templates/accounts/` แสดงหน้า โดยรับข้อมูลจาก view และแสดง field ผ่าน `templates/partials/form.html`

ชื่อ URL ใช้ namespace `accounts:` เช่น `{% url 'accounts:register' %}` อย่า hard-code path ใน template หากเรียก URL name ได้ เพราะเปลี่ยน path ทีหลังได้โดยแก้จุดเดียว

### สมัครสมาชิก (Register)

เส้นทาง: `GET/POST /accounts/register/` → `accounts.views.register` → `RegisterForm` → `User`

- `GET` แสดง `templates/accounts/register.html`
- template extend `base.html` และ include `partials/form.html` เพื่อวาด field/error ที่ Django form สร้างให้
- `POST` ส่งข้อมูลเข้า `RegisterForm` ซึ่งตรวจชื่อ นามสกุล อีเมล บทบาท และรหัสผ่าน
- อีเมลถูก trim/lowercase และปฏิเสธอีเมลซ้ำแบบไม่สนตัวพิมพ์เล็ก/ใหญ่
- รหัสผ่านสองช่องต้องตรงกันและผ่าน `AUTH_PASSWORD_VALIDATORS` จาก `config/settings.py`
- บทบาทที่สมัครเองเลือกได้ `student`, `ta`, `teacher` เท่านั้น ไม่มี `admin` ใน choices
- `RegisterForm.save()` เข้ารหัสรหัสผ่านด้วย `set_password()` ห้ามบันทึกรหัสผ่านดิบ
- บัญชีใหม่เริ่ม `email_verified=False`; บัญชี `teacher` เริ่ม `teacher_status=pending`
- เมื่อสร้างบัญชีแล้ว view ส่งอีเมลยืนยัน เก็บอีเมลที่รอการยืนยันไว้ใน session แล้วพาไป `/accounts/register/check-email/`

### ยืนยันอีเมล

เส้นทาง: ลิงก์ในอีเมล → `GET /accounts/verify/<token>/` → `verify_email`

- `accounts/emails.py` สร้าง absolute URL และใช้ `accounts/tokens.py` สร้าง token ที่ลงลายเซ็นด้วย Django signing
- token บรรจุ user id และอีเมล มีอายุ `EMAIL_VERIFY_MAX_AGE` ซึ่งตั้งไว้ 24 ชั่วโมงใน `config/settings.py`
- view ตรวจ token และจับคู่ทั้ง id กับอีเมลก่อนตั้ง `email_verified=True`
- token ผิดหรือหมดอายุแสดง `verify_failed.html` ด้วย HTTP 400; token ถูกต้องพาไปหน้า login
- กดส่งลิงก์ใหม่ได้ที่ `/accounts/verify/resend/` ระบบแสดงข้อความเดียวกันไม่ว่าอีเมลมีอยู่จริงหรือไม่ เพื่อไม่เปิดเผยรายชื่อผู้สมัคร

### เข้าสู่ระบบ (Login)

เส้นทาง: `GET/POST /accounts/login/` → `LoginPage` → `EmailLoginForm`

- `LoginPage` เป็น Django `LoginView` ที่กำหนด template และ form ของโปรเจกต์
- Django ใช้ช่องชื่อ `username` ภายใน `AuthenticationForm` แต่หน้าเว็บแสดง label ว่า “อีเมล”; `EmailLoginForm.clean_username()` trim/lowercase ก่อนตรวจบัญชี
- `confirm_login_allowed()` ปฏิเสธบัญชีที่ยังไม่ยืนยันอีเมล
- เมื่อสำเร็จ Django จัดการ auth session และ redirect ไป `LOGIN_REDIRECT_URL` (`courses:my`) หรือ URL ใน `next` หากมี
- `templates/accounts/login.html` มีลิงก์ไปสมัครสมาชิก ลืมรหัสผ่าน และส่งอีเมลยืนยันซ้ำ
- ออกจากระบบเป็น POST ที่ `/accounts/logout/` พร้อม CSRF token

### ลืมรหัสผ่าน

เส้นทาง `/accounts/password-reset/` และหน้าถัด ๆ ไปถูกประกอบด้วย Django auth views ใน `accounts/urls.py`; template และข้อความอีเมลอยู่ใน `templates/accounts/`. ใช้กลไกของ Django แทนการเขียน flow reset token เอง

## Route หลัก

| URL | URL name | หน้าที่ |
|---|---|---|
| `/` | — | redirect ไป `courses:my` |
| `/accounts/register/` | `accounts:register` | สมัครสมาชิก |
| `/accounts/register/check-email/` | `accounts:check_email` | แจ้งให้ตรวจกล่องอีเมล |
| `/accounts/verify/<token>/` | `accounts:verify_email` | ยืนยันอีเมล |
| `/accounts/verify/resend/` | `accounts:resend_verification` | ส่งลิงก์ยืนยันซ้ำ |
| `/accounts/login/` | `accounts:login` | เข้าสู่ระบบด้วยอีเมล |
| `/accounts/logout/` | `accounts:logout` | ออกจากระบบ (POST) |
| `/accounts/password-reset/…` | `accounts:password_reset…` | ขอเปลี่ยน/ตั้งรหัสผ่านใหม่ |
| `/courses/` | `courses:list` | ค้นหารายวิชา (ต้อง login) |
| `/courses/mine/` | `courses:my` | ดูรายวิชาที่ลงทะเบียน (ต้อง login) |
| `/admin/` | — | Django admin |

## ข้อมูลผู้ใช้และบทบาท

`accounts.User` สืบทอดจาก `AbstractUser` แต่เอา `username` ออกและใช้อีเมลเป็น `USERNAME_FIELD` อีเมลต้องไม่ซ้ำกัน บทบาทของบัญชี (`User.Role`) ได้แก่ Student, TA, Teacher และ Admin ส่วน `teacher_status` ใช้สถานะ `pending`, `approved`, `rejected` สำหรับบัญชีอาจารย์ การสมัครเป็นอาจารย์ไม่ได้ทำให้มีสิทธิ์สอนทันที: ผู้ดูแลอนุมัติได้ที่ `/admin/` → Users → เลือกรายการ → action อนุมัติ/ปฏิเสธ

บทบาทบัญชีไม่ใช่บทบาทในรายวิชา: `courses.Enrollment.Role` ระบุสิทธิ์ของผู้ใช้ต่อวิชาหนึ่ง ๆ และการตัดสินใจอนุญาต enroll อยู่ใน `courses/services.py` ไม่ควรย้ายกฎนี้ไปไว้ใน template

## ถ้าจะพัฒนาหน้าต่อ

- **แก้หน้าตา login/register:** แก้ `templates/accounts/login.html` หรือ `register.html`; ทั้งสองหน้าใช้ `base.html` และ partial ฟอร์มร่วมกัน
- **เพิ่ม/เปลี่ยนช่องหรือ validation:** แก้ `RegisterForm` หรือ `EmailLoginForm` ใน `accounts/forms.py` ก่อน ส่วน template จะวน render fields โดยอัตโนมัติ
- **เปลี่ยนสิ่งที่เกิดหลัง submit:** แก้ view ที่เกี่ยวข้องใน `accounts/views.py`
- **เพิ่ม URL:** เพิ่มใน `accounts/urls.py` และตั้งชื่อ route จากนั้นอ้างด้วย `{% url 'accounts:ชื่อ' %}`
- **เปลี่ยนข้อมูลผู้ใช้:** แก้ `accounts/models.py` และสร้าง migration; เพราะเป็น custom user model อย่าเปลี่ยน `AUTH_USER_MODEL` หลังมีฐานข้อมูลที่ใช้งานแล้วโดยไม่วางแผน migration
- **แก้ข้อความ/หน้าตา email:** เนื้อหา verification อยู่ใน `templates/accounts/verify_email.txt`; การประกอบ/ส่งเมลอยู่ `accounts/emails.py`
- **แก้ CSS หรือ navigation ร่วม:** แก้ `templates/base.html` ซึ่งเป็น layout กลาง

## อีเมลและค่าตั้งต้น

`config/settings.py` โหลด `.env` ด้วย `python-dotenv`; SMTP ใช้ Gmail ที่ `smtp.gmail.com:587` ผ่าน TLS ตัวแปรหลักอยู่ใน `.env.example`: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` ค่า email verification หมดอายุใน 24 ชั่วโมง หากไม่มี SMTP credentials การส่งอีเมลจริงจะทำงานไม่ได้

## ข้อควรรู้สำหรับทีม

- Migration ปัจจุบันอยู่ใน `accounts/migrations/` และ `courses/migrations/`; commit migration ใหม่พร้อมการเปลี่ยน model
- `.env`, ฐานข้อมูล SQLite, backup และ virtual environment เป็นไฟล์เฉพาะเครื่องตาม `.gitignore` ไม่ควรส่งขึ้น Git
- Test ของ account อยู่ `accounts/tests.py`; test ของ course อยู่ `courses/tests.py`
- คำสั่งรัน test เมื่อทีมต้องการตรวจการเปลี่ยนแปลง: `python manage.py test`

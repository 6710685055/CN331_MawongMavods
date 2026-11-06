# เอกสารเทคนิค: UC10 Upvote/Downvote/Report Document

- **ขอบเขต:** แอป `documents` (ส่วน UC10) และ `notifications` (ประเภท `doc_hidden`)
- **อัปเดตล่าสุด:** 2026-11-02 (branch `us10-pp`)
- **ต่อยอดโดย:** UC14 (`docs/documents_uc14.md`) ซึ่งเป็นคิวตรวจ Report และการตัดสิน ส่วนการลบเอกสารโดยเจ้าของ (UC12) ยังไม่ได้ทำ

---

## 1. หลักการออกแบบ

### Separation of Concerns
แต่ละ layer มีหน้าที่เดียว และแยกไฟล์ตาม use case แบบเดียวกับ UC3/UC4

| Layer | ไฟล์ | หน้าที่ |
|---|---|---|
| models | `documents/models/feedback.py` | `DocumentVote`, `DocumentReport`, choices และ constraint |
| selectors | `documents/selectors/feedback.py` | query อ่านอย่างเดียว เช่น นับผู้ Report, ดึงโหวตของผู้ใช้, รายชื่อ staff ของวิชา |
| permissions | `documents/permissions.py` | `can_view_document`, `can_vote_or_report`, `can_see_hidden_documents` (คืน True/False) |
| services | `documents/services/feedback.py` | กติกาทั้งหมด, transaction, raise `DocumentPermissionError` / `DocumentServiceError` |
| notifiers | `documents/services/notifiers.py` | ประกอบข้อความแจ้งเตือนแล้วเรียก `send_notification` |
| constants | `documents/constants/feedback.py` | ข้อความภาษาไทยทุกข้อความของ UC10 |
| views | `documents/views/feedback.py` | แปลง HTTP ↔ service แล้วตอบ JSON / redirect / 403 |
| templates | `templates/documents/partials/{vote_widget,report_panel,hidden_banner}.html` | แสดงผล และใช้ซ้ำได้หลายหน้า |
| static | `documents/static/documents/js/vote.js`, `css/feedback.css` | AJAX โหวต และ toggle ช่องรายละเอียด |

`models.py` เดิมถูกแยกเป็น package `documents/models/` (`document.py`, `review.py`, `feedback.py`) โดย `__init__.py` re-export ไว้
`from documents.models import Document` จึงใช้ได้เหมือนเดิม และ migration `0001` ยังอ้าง `documents.models.document_upload_path` ได้

### Dynamic Implementation (ไม่ hardcode)
- **ค่าที่ปรับได้อยู่ใน settings:** `DOCUMENT_REPORT_HIDE_THRESHOLD` (5) และ `DOCUMENT_REPORT_DETAIL_MAX_LENGTH` (1000) อ่านผ่าน `get_report_hide_threshold()` / `get_report_detail_max_length()`
- **enum มาจาก `TextChoices` / `IntegerChoices` เท่านั้น:**
  - `DocumentVote.Value(UP=1, DOWN=-1)` ฝั่ง HTTP/JSON ใช้ชื่อ `up` / `down` ซึ่งแปลงด้วย `Value[name.upper()]` และ `.name.lower()`
  - กติกาบังคับกรอกรายละเอียดใช้ `DocumentReport.REASONS_REQUIRING_DETAIL` ไม่เช็ก `== "other"` ตรง ๆ
  - ตัวเลือกเหตุผลและปุ่มโหวตใน template วนจาก choices (`build_vote_options()`)
- **URL:** Python ใช้ `reverse()`, template ใช้ `{% url %}` และ JS อ่าน `data-vote-url`
- **เทสใช้ `@override_settings(DOCUMENT_REPORT_HIDE_THRESHOLD=...)`** เพื่อยืนยันว่าเกณฑ์ไม่ได้ฝังไว้ในโค้ด

---

## 2. Data model

**`Document`** (เพิ่มเติม): `is_hidden`, `hidden_at`

**`DocumentVote`**: `document`, `user`, `value` (±1), `created_at`, `updated_at`
- `UniqueConstraint(document, user)` ชื่อ `unique_vote_per_user`
- `Document.vote_score` เป็นค่า denormalized ที่คำนวณใหม่จาก `Sum("value")` ทุกครั้งที่โหวต

**`DocumentReport`**: `document`, `reporter`, `reason`, `detail`, `document_version`, `status`, `resolution`, `created_at`, `closed_at`
- `status`: `open` → `withdrawn` (ผู้ใช้ถอน) หรือ `resolved` (UC14 ตัดสิน)
- `resolution`: `dismissed` / `revision` / `removed` / `owner_deleted` ซึ่งตั้งโดย UC14 (`services/moderation.py`) และผูกกับ `DocumentReportDecision` ผ่าน `decision`
- partial unique `UniqueConstraint(document, reporter, condition=status="open")` ชื่อ `unique_open_report_per_user`

---

## 3. กติกาใน service

**`vote_document(user, document, value)` → `(score, my_vote)`**
1. ต้องผ่าน `_require_can_vote_or_report` คือเป็นสมาชิกวิชา, ไม่ใช่เจ้าของ และเอกสารไม่ถูกซ่อน
2. ยังไม่เคยโหวต = สร้าง, กดค่าเดิม = ลบ, กดอีกฝั่ง = แก้ value
3. ถ้าคำขอพร้อมกันชน `IntegrityError` ตอนสร้าง จะเปลี่ยนไปทาง update จึงไม่เกิดแถวซ้ำ
4. คำนวณ `vote_score` ใหม่แล้วบันทึกด้วย `.update()`

**`report_document(user, document, reason, detail)`**
1. ตรวจสิทธิ์แบบเดียวกับการโหวต
2. reason ต้องอยู่ใน `Reason.values` และถ้าอยู่ใน `REASONS_REQUIRING_DETAIL` ต้องมี detail ความยาวไม่เกินค่าที่ตั้งไว้
3. มี Report ที่ยังค้างอยู่แล้ว → `REPORT_DUPLICATE` (constraint ระดับ DB กันอีกชั้น)
4. เคยถูกปฏิเสธ (`resolved` + `dismissed`) ใน `document_version` เดียวกัน → `REPORT_ALREADY_DISMISSED` เมื่อเจ้าของเปลี่ยนไฟล์ `version` จะเพิ่มขึ้น และจะ Report ได้อีกครั้งโดยอัตโนมัติ
5. `_hide_if_threshold_reached` ทำงานดังนี้
   - นับผู้ Report ไม่ซ้ำคนของ Report ที่ค้าง ถ้าถึงเกณฑ์จะทำ conditional update `filter(is_hidden=False).update(is_hidden=True)`
   - แจ้งเตือนเฉพาะเมื่อ update ได้ 1 แถว จึงแจ้งครั้งเดียวแม้มีคน Report พร้อมกัน

**`withdraw_report(user, document)`**
- conditional update `open → withdrawn` ถ้าได้ 0 แถวจะได้ `REPORT_NOTHING_TO_WITHDRAW`
- เอกสารยังซ่อนต่อจนกว่า TA/อาจารย์จะตัดสิน ยกเว้นไม่เหลือ Report ค้าง จะยกเลิกการซ่อน เพื่อไม่ให้ค้างซ่อนทั้งที่ไม่อยู่ในคิว

---

## 4. การมองเห็นเอกสารที่ถูกซ่อน

| ผู้ใช้ | คลังเอกสาร | detail / download | โหวต / Report |
|---|---|---|---|
| เจ้าของ | เห็น (มีแท็ก "ซ่อนชั่วคราว") | เห็น + แบนเนอร์ | ไม่มีปุ่ม (เป็นเจ้าของ) |
| TA / อาจารย์ของวิชา | เห็น | เห็น + แบนเนอร์ | ไม่ได้ |
| นักศึกษาคนอื่น | ไม่เห็น | 404 | ไม่ได้ (403) |

ถ้าผู้ Report ส่ง Report แล้วทำให้เอกสารถูกซ่อน ระบบจะ redirect ไปหน้าคลังเอกสารแทน detail ที่ตอนนี้จะเป็น 404 สำหรับเขา
ข้อความแจ้งเตือนและแบนเนอร์ไม่ระบุชื่อผู้ Report

---

## 5. Endpoints

| URL name | Method | ผลลัพธ์ |
|---|---|---|
| `documents:vote` | POST `value=up\|down` | ถ้าขอ `Accept: application/json` ได้ `{"score", "my_vote"}` (หรือ 400/403 พร้อม `{"error"}`) ถ้าไม่ได้ขอ JSON จะ redirect |
| `documents:report` | POST `reason`, `detail` | redirect พร้อม message, 403 ถ้าไม่มีสิทธิ์ |
| `documents:withdraw_report` | POST | redirect พร้อม message |

---

## 6. Tests

`documents/tests/test_uc10_feedback.py` (14 tests) ครอบคลุม AC ทุกข้อ ดูตาราง UC10 ใน `README.md`

```bash
python manage.py test documents.tests.test_uc10_feedback
```

# เอกสารเทคนิค: UC14 TA/Teacher ตรวจเอกสารที่ถูก Report

- **ขอบเขต:** แอป `documents` (ส่วน UC14) และ `notifications` (ประเภท `doc_report_dismissed`, `doc_removed`, `doc_report_resolved`)
- **อัปเดตล่าสุด:** 2026-11-02 (branch `us14-pp`)
- **ต่อจาก:** UC10 (`docs/documents_uc10.md`) ซึ่งสร้าง `DocumentReport` และสถานะซ่อน
- **ส่วนที่ยังไม่ทำ:** หน้าจอให้เจ้าของลบเอกสารเอง (UC12) แต่มี service `close_reports_for_owner_deletion()` รอไว้แล้ว

---

## 1. โครงสร้างไฟล์ (Separation of Concerns)

| Layer | ไฟล์ | หน้าที่ |
|---|---|---|
| models | `documents/models/moderation.py` | `DocumentReportDecision` (audit log ของการตัดสิน) |
| models | `documents/models/document.py` | soft delete (`removed_at`, `removed_by`, `removal_reason`) และ `ActiveDocumentManager` |
| models | `documents/models/feedback.py` | `Resolution.OWNER_DELETED`, `DocumentReport.decision` และชุดกติกา `REVIEWER_RESOLUTIONS` / `RESOLUTIONS_REQUIRING_REASON` / `RESOLUTIONS_REQUIRING_CONFIRMATION` |
| selectors | `documents/selectors/moderation.py` | คิว (`reported_documents`), สรุปเหตุผล, Report พร้อมชื่อผู้ Report, ประวัติการตัดสิน |
| permissions | `documents/permissions.py` | `can_access_report_queue`, `can_moderate_reports` |
| services | `documents/services/moderation.py` | `get_reported_queue`, `get_report_review`, `resolve_reports`, `close_reports_for_owner_deletion` |
| notifiers | `documents/services/notifiers.py` | `notify_report_decision` |
| constants | `documents/constants/moderation.py` | ข้อความภาษาไทยทุกข้อความ (key ตามชื่อ member ของ `Resolution`) |
| views | `documents/views/moderation.py` | `reported_queue_view`, `report_review_view`, `resolve_reports_view` และ `build_decision_options` |
| templates | `reported_queue.html`, `report_review.html`, `partials/decision_forms.html` | |
| static | `documents/static/documents/js/moderation.js` | `confirm()` ก่อนลบ โดยอ่านข้อความจาก `data-confirm-message` |

### Dynamic Implementation
- ผลการตัดสินทั้งหมดมาจาก `DocumentReport.Resolution` ลำดับปุ่มมาจาก `REVIEWER_RESOLUTIONS` และกติกา "ต้องมีเหตุผล" / "ต้องยืนยัน" มาจาก frozenset บน model ไม่มีการเทียบ string ตรง ๆ
- ผลของแต่ละ outcome ต่อเอกสารใช้ dict dispatch `_APPLY_OUTCOME` และ type ของแจ้งเตือนเจ้าของใช้ `_OWNER_NOTIFICATION_TYPES`
- ความยาวเหตุผลสูงสุดตั้งที่ `DOCUMENT_REPORT_DECISION_REASON_MAX_LENGTH` ใน settings
- template วนจาก `decision_options` ที่ view สร้างให้ ไม่มีปุ่มที่เขียนตายตัว

---

## 2. Soft delete และ default manager

- `Document.objects` คือ `ActiveDocumentManager` ซึ่ง **ตัดเอกสารที่ `removed_at` ไม่ว่างออกโดยอัตโนมัติ**
  - ทุกจุดที่ใช้ `Document.objects` หรือ `get_object_or_404(Document, …)` (คลัง, detail, download, pin, คิว UC4, โหวต/Report) จึงมองไม่เห็นหรือได้ 404 กับเอกสารที่ถูกลบโดยไม่ต้องแก้ทีละจุด
- `Document.all_objects` เห็นทุกเอกสาร ใช้ใน Django admin (`DocumentAdmin.get_queryset`) และในเทส
- FK ย้อนกลับจาก `DocumentReport`, `DocumentReviewLog`, `DocumentReportDecision` ไปยังเอกสารใช้ base manager จึงยังอ่านเอกสารที่ถูกลบได้ ประวัติไม่หาย
- ไฟล์จริงถูกลบจาก storage ใน `transaction.on_commit` หลังบันทึกผลสำเร็จเท่านั้น

---

## 3. `resolve_reports(reviewer, document, outcome, reason, confirmed)`

1. **สิทธิ์:**
   - ต้องเป็น TA ที่อนุมัติแล้ว หรือ Teacher ที่อนุมัติแล้วของวิชา ถ้าไม่ใช่ได้ `QUEUE_FORBIDDEN` (403)
   - ถ้าเป็นผู้อัปโหลดเอง ได้ `CANNOT_MODERATE_OWN` (403)
   - ถ้าเอกสารถูกลบไปแล้ว ได้ `DOCUMENT_ALREADY_REMOVED`
2. **ข้อมูลนำเข้า:** outcome ต้องอยู่ใน `REVIEWER_RESOLUTIONS` การส่งกลับและการลบต้องมีเหตุผล และการลบต้อง `confirmed=True`
3. **ใน `transaction.atomic()`:**
   - สร้าง `DocumentReportDecision` (snapshot ชื่อและบทบาทผู้ตัดสิน, outcome, เหตุผล, เวอร์ชัน)
   - `open_reports(doc).update(status=resolved, resolution=outcome, decision=…, closed_at=now)`
   - **ถ้าได้ 0 แถว ให้ raise `ALREADY_HANDLED` และ rollback decision** วิธีนี้กันกรณีผู้ตรวจสองคนกดพร้อมกัน ผลถูกบันทึกครั้งเดียว และคนที่สองเห็น "เอกสารนี้ได้รับการดำเนินการแล้ว"
   - เรียก `_APPLY_OUTCOME[outcome]`:
     - **ปฏิเสธ:** เลิกซ่อน ป้าย Verified คงเดิม และจำนวน Report ที่ค้างกลายเป็น 0
     - **ส่งกลับ:** `NEEDS_REVISION`, ถอดป้าย Verified, `latest_review_comment = reason` และเลิกซ่อน
     - **ลบ:** soft delete, เลิกปักหมุด และลบไฟล์หลัง commit
   - แจ้งเตือนหลัง commit:
     - เจ้าของได้ข้อความตามผลพร้อมเหตุผล **ไม่มีชื่อผู้ Report**
     - ผู้ Report ทุกคนได้ `doc_report_resolved`
4. **เมื่อเจ้าของแก้ไฟล์ (UC12 / `replace_document_file`):**
   - ชีทสรุปและแนวข้อสอบกลับเป็น `PENDING` (เข้าคิว UC4)
   - การบ้านที่ถูกส่งกลับกลับเป็น `NONE`
   - ผู้ที่ Report ถูกปฏิเสธไปแล้ว Report ใหม่ได้ เพราะ `document_version` เปลี่ยน

---

## 4. ใครเห็นอะไร

| ข้อมูล | ผู้ตรวจ (TA/Teacher) | เจ้าของเอกสาร | นักศึกษาอื่น |
|---|---|---|---|
| คิวเอกสารที่ถูก Report | ✓ (ยกเว้นเอกสารที่ตัวเองอัปโหลด) | ✗ 403 | ✗ 403 |
| ชื่อผู้ Report | ✓ หน้า review | ✗ | ✗ |
| เหตุผลการตัดสิน | ✓ ประวัติการตัดสิน | ✓ ผ่านแจ้งเตือน และหน้า detail กรณีส่งกลับ | ✗ |
| เอกสารที่ถูกลบ | ✗ 404 (admin ใช้ `all_objects`) | ✗ 404 | ✗ 404 |

---

## 5. Endpoints

| URL name | Method | หมายเหตุ |
|---|---|---|
| `documents:reported_queue` | GET | `/courses/<id>/documents/reported-queue/` |
| `documents:report_review` | GET | `/courses/<id>/documents/reported-queue/<doc_id>/` |
| `documents:resolve_reports` | POST `outcome`, `reason`, `confirm_remove` | สำเร็จหรือ "ดำเนินการแล้ว" จะ redirect ไปที่คิว และไม่มีสิทธิ์ได้ 403 |

ทางเข้าคิวมี 3 จุด คือ ปุ่ม "🚩 เอกสารที่ถูก Report" ในหน้ารายวิชา (`courses/course_detail.html`), ปุ่มเดียวกันในคลังเอกสาร (พร้อมจำนวน) และปุ่ม "🚩 ตรวจ Report (N)" ในหน้า detail ของเอกสาร

---

## 6. Tests

`documents/tests/test_uc14_reports.py` (12 tests) ครอบคลุม AC ทุกข้อ ดูตาราง UC14 ใน `README.md`

```bash
python manage.py test documents.tests.test_uc14_reports
```

> เทส "สองคนกดพร้อมกัน" เรียกตัดสินสองครั้งต่อกัน (ไม่ใช่สอง thread จริง) เพื่อยืนยันว่าเงื่อนไข UPDATE ที่ได้ 0 แถวทำให้ rollback และไม่บันทึกซ้ำ

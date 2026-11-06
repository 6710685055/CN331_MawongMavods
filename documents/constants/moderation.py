"""User-facing (Thai) text for UC14: review reported documents.

Dicts are keyed by `DocumentReport.Resolution` member name (e.g. "DISMISSED").
Owner-facing text must never name the reporters.
"""

# Permission / state errors
QUEUE_FORBIDDEN = (
    "เฉพาะ TA ที่ได้รับอนุมัติและอาจารย์ผู้สอนของรายวิชานี้เท่านั้นที่สามารถเข้าถึงคิวเอกสารที่ถูก Report ได้"
)
CANNOT_MODERATE_OWN = (
    "ผู้ตรวจไม่สามารถตัดสิน Report ของเอกสารที่ตนเองอัปโหลดได้ ต้องให้ TA คนอื่นหรืออาจารย์ผู้สอนตัดสิน"
)
DOCUMENT_ALREADY_REMOVED = "เอกสารนี้ถูกลบไปแล้ว"
NOT_DOCUMENT_OWNER = "เฉพาะเจ้าของเอกสารเท่านั้นที่สามารถลบเอกสารของตนเองได้"
ALREADY_HANDLED = "เอกสารนี้ได้รับการดำเนินการแล้ว"
OUTCOME_INVALID = "ผลการตัดสินไม่ถูกต้อง"
REASON_REQUIRED = "กรุณาระบุเหตุผลเมื่อเลือก \"{outcome}\""
REASON_TOO_LONG = "เหตุผลต้องมีความยาวไม่เกิน {max_length} ตัวอักษร"
REMOVE_CONFIRM_REQUIRED = "กรุณายืนยันการลบเอกสารก่อนดำเนินการ"

# Reviewer UI
REMOVE_CONFIRM_LABEL = "ฉันยืนยันว่าต้องการลบเอกสารนี้ออกจากคลัง (ดาวน์โหลดไม่ได้อีก)"
REMOVE_CONFIRM_PROMPT = "ยืนยันการลบเอกสาร '{title}' หรือไม่? การลบไม่สามารถย้อนกลับได้"
DECISION_BUTTONS = {
    "DISMISSED": "ปฏิเสธ Report (แสดงเอกสารตามปกติ)",
    "REVISION": "ส่งกลับให้เจ้าของแก้ไข",
    "REMOVED": "ลบเอกสาร",
}
DECISION_HELP = {
    "DISMISSED": "ยกเลิกการซ่อน ป้าย Verified ที่มีอยู่ยังคงอยู่ และปิด Report ทั้งหมด",
    "REVISION": "เปลี่ยนสถานะเป็น \"ต้องแก้ไข\" และถอดป้าย Verified (ถ้ามี)",
    "REMOVED": "เอกสารจะหายจากคลังและดาวน์โหลดไม่ได้ แม้จะเคยได้รับป้าย Verified",
}
DECISION_BUTTON_STYLES = {
    "DISMISSED": "secondary",
    "REVISION": "danger",
    "REMOVED": "danger",
}

# Success messages for the reviewer
DECISION_DONE = {
    "DISMISSED": "ปฏิเสธ Report ของเอกสาร '{title}' แล้ว ({count} รายการ)",
    "REVISION": "ส่งเอกสาร '{title}' กลับให้เจ้าของแก้ไขแล้ว ({count} รายการ)",
    "REMOVED": "ลบเอกสาร '{title}' ออกจากคลังแล้ว ({count} รายการ)",
}

# Notifications to the document owner (with reason, never reporter names)
OWNER_TITLE = {
    "DISMISSED": "Report ต่อเอกสาร '{title}' ถูกปฏิเสธ",
    "REVISION": "เอกสาร '{title}' ถูกส่งกลับให้แก้ไขจากการถูก Report",
    "REMOVED": "เอกสาร '{title}' ถูกลบออกจากคลัง",
}
OWNER_MESSAGE = {
    "DISMISSED": (
        "ผู้ตรวจ ({reviewer} - {role}) ตรวจสอบ Report ต่อเอกสาร '{title}' ในวิชา {course_code} แล้ว "
        "เอกสารแสดงตามปกติ{reason_suffix}"
    ),
    "REVISION": (
        "ผู้ตรวจ ({reviewer} - {role}) ส่งเอกสาร '{title}' ในวิชา {course_code} กลับให้แก้ไข "
        "เหตุผล: \"{reason}\""
    ),
    "REMOVED": (
        "ผู้ตรวจ ({reviewer} - {role}) ลบเอกสาร '{title}' ในวิชา {course_code} ออกจากคลัง "
        "เหตุผล: \"{reason}\""
    ),
}
OWNER_REASON_SUFFIX = " หมายเหตุ: \"{reason}\""

# Notifications to every reporter
REPORTER_TITLE = "Report ของคุณต่อเอกสาร '{title}' ได้รับการดำเนินการแล้ว"
REPORTER_MESSAGE = "Report ต่อเอกสาร '{title}' ในวิชา {course_code} ได้รับการดำเนินการแล้ว ผลการตัดสิน: {outcome}"

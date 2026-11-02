"""User-facing (Thai) text for UC10: vote & report documents.

Templates with `{placeholders}` are filled with `.format(...)` by the caller.
"""

# Permission errors
NOT_COURSE_MEMBER = "เฉพาะผู้ที่ลงทะเบียนในรายวิชานี้เท่านั้นที่สามารถโหวตหรือ Report เอกสารได้"
OWNER_CANNOT_INTERACT = "ไม่สามารถโหวตหรือ Report เอกสารของตนเองได้"
DOCUMENT_HIDDEN_NO_INTERACT = "เอกสารนี้ถูกซ่อนชั่วคราวระหว่างรอการตรวจสอบ จึงยังโหวตหรือ Report ไม่ได้"

# Vote (icons keyed by DocumentVote.Value member name)
VOTE_INVALID = "รูปแบบการโหวตไม่ถูกต้อง"
VOTE_ICONS = {"UP": "👍", "DOWN": "👎"}
VOTE_MARKERS = {"UP": "▲", "DOWN": "▼"}

# Report
REPORT_REASON_REQUIRED = "กรุณาเลือกเหตุผลในการ Report"
REPORT_REASON_INVALID = "เหตุผลในการ Report ไม่ถูกต้อง"
REPORT_DETAIL_REQUIRED = "กรุณากรอกรายละเอียดเพิ่มเติมเมื่อเลือกเหตุผล \"{reason}\""
REPORT_DETAIL_TOO_LONG = "รายละเอียดต้องมีความยาวไม่เกิน {max_length} ตัวอักษร"
REPORT_DUPLICATE = "คุณเคย Report เอกสารนี้แล้ว และยังรอการตรวจสอบจาก TA/อาจารย์"
REPORT_ALREADY_DISMISSED = (
    "Report ของคุณสำหรับเอกสารเวอร์ชันนี้ถูกปฏิเสธไปแล้ว "
    "จะ Report ได้อีกครั้งเมื่อเจ้าของอัปโหลดไฟล์เวอร์ชันใหม่"
)
REPORT_SUBMITTED = "ส่ง Report เอกสาร '{title}' แล้ว TA/อาจารย์ของรายวิชาจะตรวจสอบต่อไป"
REPORT_NOTHING_TO_WITHDRAW = "ไม่มี Report ที่รอดำเนินการให้ถอน"
REPORT_WITHDRAWN = "ถอน Report เอกสาร '{title}' แล้ว"

# Hidden-at-threshold notifications (must never name the reporters)
HIDDEN_OWNER_TITLE = "เอกสาร '{title}' ถูกซ่อนชั่วคราว"
HIDDEN_OWNER_MESSAGE = (
    "เอกสาร '{title}' ในวิชา {course_code} ถูก Report ถึงเกณฑ์ ({threshold} คน) "
    "จึงถูกซ่อนชั่วคราวระหว่างรอ TA/อาจารย์ตรวจสอบ"
)
HIDDEN_STAFF_TITLE = "มีเอกสารถูกซ่อนจากการ Report ในวิชา {course_code}"
HIDDEN_STAFF_MESSAGE = (
    "เอกสาร '{title}' ถูก Report ถึงเกณฑ์ ({threshold} คน) และถูกซ่อนชั่วคราว กรุณาตรวจสอบ"
)

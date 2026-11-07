from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Type(models.TextChoices):
        DOCUMENT_VERIFIED = "doc_verified", "เอกสารได้รับการยืนยัน (Verified)"
        DOCUMENT_NEEDS_REVISION = "doc_revision", "เอกสารถูกส่งกลับให้แก้ไข"
        DOCUMENT_VERIFY_REVOKED = "doc_revoked", "เอกสารถูกยกเลิกการ Verify"
        DOCUMENT_HIDDEN = "doc_hidden", "เอกสารถูกซ่อนชั่วคราวจากการถูก Report"
        DOCUMENT_REPORT_DISMISSED = "doc_report_dismissed", "Report ต่อเอกสารถูกปฏิเสธ"
        DOCUMENT_REMOVED = "doc_removed", "เอกสารถูกลบจากการตรวจ Report"
        DOCUMENT_REPORT_RESOLVED = (
            "doc_report_resolved",
            "Report ของคุณได้รับการดำเนินการแล้ว",
        )
        MEETING_CREATED = "meeting_created", "มีนัดหมายประชุมใหม่"
        MEETING_REMINDER = "meeting_reminder", "แจ้งเตือนก่อนประชุม"
        MEETING_UPDATED = "meeting_updated", "มีการเปลี่ยนแปลงนัดหมายประชุม"
        TEAM_INVITATION = "team_invitation", "คำเชิญเข้ากลุ่ม"
        TEAM_INVITATION_RESPONSE = "team_response", "การตอบรับคำเชิญเข้ากลุ่ม"
        TEAM_CHAT_MESSAGE = "team_chat_message", "ข้อความใหม่ในแชทกลุ่ม"
        TEAM_MEMBERSHIP = "team_membership", "การเปลี่ยนแปลงสมาชิกกลุ่ม"
        PRIVATE_CHAT_MESSAGE = "private_chat_message", "ข้อความส่วนตัวใหม่"
        PRIVATE_REPORT_RESULT = "private_report_result", "ผลการพิจารณารายงานข้อความ"
        PRIVATE_CHAT_WARNING = "private_chat_warning", "คำเตือนการใช้แชทส่วนตัว"
        PRIVATE_CHAT_SUSPENDED = "private_chat_suspended", "ระงับการส่งข้อความส่วนตัว"
        PRIVATE_CHAT_UNSUSPENDED = (
            "private_chat_unsuspended",
            "ยกเลิกการระงับข้อความส่วนตัว",
        )
        GENERAL = "general", "ทั่วไป"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="ผู้รับแจ้งเตือน",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="ผู้ดำเนินการ",
    )
    notification_type = models.CharField(
        "ประเภทการแจ้งเตือน",
        max_length=30,
        choices=Type.choices,
        default=Type.GENERAL,
    )
    title = models.CharField("หัวข้อ", max_length=255)
    message = models.TextField("ข้อความแจ้งเตือน")
    target_url = models.CharField("ลิงก์ปลายทาง", max_length=500, blank=True)
    is_read = models.BooleanField("อ่านแล้ว", default=False)
    created_at = models.DateTimeField("วันเวลา", auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"[{self.get_notification_type_display()}] -> {self.recipient}: {self.title}"

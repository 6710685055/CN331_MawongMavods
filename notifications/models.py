from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Type(models.TextChoices):
        DOCUMENT_VERIFIED = "doc_verified", "เอกสารได้รับการยืนยัน (Verified)"
        DOCUMENT_NEEDS_REVISION = "doc_revision", "เอกสารถูกส่งกลับให้แก้ไข"
        DOCUMENT_VERIFY_REVOKED = "doc_revoked", "เอกสารถูกยกเลิกการ Verify"
        MEETING_REMINDER = "meeting_reminder", "แจ้งเตือนก่อนประชุม"
        MEETING_UPDATED = "meeting_updated", "มีการเปลี่ยนแปลงนัดหมายประชุม"
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

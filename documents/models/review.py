from django.conf import settings
from django.db import models

from .document import Document


class DocumentReviewLog(models.Model):
    class Action(models.TextChoices):
        VERIFY = "verify", "ยืนยันความถูกต้อง (Verify)"
        REQUEST_REVISION = "request_revision", "ส่งกลับให้แก้ไข"
        REVOKE_VERIFY = "revoke_verify", "ยกเลิกการ Verify"

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="review_logs",
        verbose_name="เอกสาร",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_review_logs",
        verbose_name="ผู้ตรวจ",
    )
    reviewer_name_snapshot = models.CharField("ชื่อผู้ตรวจ", max_length=255)
    reviewer_role_snapshot = models.CharField(
        "บทบาทผู้ตรวจ", max_length=20, choices=Document.VerifierRole.choices
    )
    action = models.CharField("การดำเนินการ", max_length=30, choices=Action.choices)
    document_version = models.PositiveIntegerField("เวอร์ชันไฟล์ที่ตรวจ")
    comment = models.TextField("ความคิดเห็น / เหตุผล", blank=True)
    created_at = models.DateTimeField("วันเวลา", auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return (
            f"{self.document.title} v{self.document_version} - "
            f"{self.get_action_display()} by {self.reviewer_name_snapshot}"
        )

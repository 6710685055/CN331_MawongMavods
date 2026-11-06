"""UC14: audit log of reviewer decisions on reported documents."""

from django.conf import settings
from django.db import models

from .document import Document
from .feedback import DocumentReport


class DocumentReportDecision(models.Model):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="report_decisions",
        verbose_name="เอกสาร",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_report_decisions",
        verbose_name="ผู้ตัดสิน",
    )
    reviewer_name_snapshot = models.CharField("ชื่อผู้ตัดสิน", max_length=255)
    reviewer_role_snapshot = models.CharField(
        "บทบาทผู้ตัดสิน",
        max_length=20,
        choices=Document.VerifierRole.choices,
        blank=True,  # empty when the owner deleted the document (UC12)
    )
    outcome = models.CharField(
        "ผลการตัดสิน", max_length=20, choices=DocumentReport.Resolution.choices
    )
    reason = models.TextField("เหตุผล", blank=True)
    document_version = models.PositiveIntegerField("เวอร์ชันไฟล์ที่ตัดสิน")
    report_count = models.PositiveIntegerField("จำนวน Report ที่ปิด", default=0)
    created_at = models.DateTimeField("วันเวลาที่ตัดสิน", auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.document.title} - {self.get_outcome_display()} by {self.reviewer_name_snapshot}"

"""UC10: votes and reports on course documents."""

from django.conf import settings
from django.db import models

from .document import Document


class DocumentVote(models.Model):
    class Value(models.IntegerChoices):
        UP = 1, "Upvote"
        DOWN = -1, "Downvote"

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="votes",
        verbose_name="เอกสาร",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="document_votes",
        verbose_name="ผู้โหวต",
    )
    value = models.SmallIntegerField("โหวต", choices=Value.choices)
    created_at = models.DateTimeField("วันเวลาที่โหวต", auto_now_add=True)
    updated_at = models.DateTimeField("แก้ไขล่าสุด", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document", "user"], name="unique_vote_per_user"
            )
        ]

    def __str__(self):
        return f"{self.user} {self.get_value_display()} {self.document.title}"


class ReportStatus(models.TextChoices):
    """Module level so DocumentReport.Meta can reference it in its constraint."""

    OPEN = "open", "รอดำเนินการ"
    WITHDRAWN = "withdrawn", "ถอนแล้ว"
    RESOLVED = "resolved", "ดำเนินการแล้ว"


class DocumentReport(models.Model):
    class Reason(models.TextChoices):
        WRONG_COURSE = "wrong_course", "ผิดวิชา/ผิดหมวดหมู่"
        INCORRECT = "incorrect", "เนื้อหาไม่ถูกต้อง"
        SPAM = "spam", "สแปม"
        COPYRIGHT = "copyright", "ละเมิดลิขสิทธิ์"
        INAPPROPRIATE = "inappropriate", "เนื้อหาไม่เหมาะสม"
        OTHER = "other", "อื่นๆ"

    REASONS_REQUIRING_DETAIL = frozenset({Reason.OTHER})

    Status = ReportStatus

    class Resolution(models.TextChoices):
        """Set by the reviewer when a report is resolved (UC14)."""

        DISMISSED = "dismissed", "ปฏิเสธ Report"
        REVISION = "revision", "ส่งกลับให้แก้ไข"
        REMOVED = "removed", "ลบเอกสาร"
        OWNER_DELETED = "owner_deleted", "เจ้าของลบเอกสาร"

    # Reviewer choices in display order, and which of them need extra input (UC14).
    REVIEWER_RESOLUTIONS = (
        Resolution.DISMISSED,
        Resolution.REVISION,
        Resolution.REMOVED,
    )
    RESOLUTIONS_REQUIRING_REASON = frozenset({Resolution.REVISION, Resolution.REMOVED})
    RESOLUTIONS_REQUIRING_CONFIRMATION = frozenset({Resolution.REMOVED})

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="reports",
        verbose_name="เอกสาร",
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="document_reports",
        verbose_name="ผู้ Report",
    )
    reason = models.CharField("เหตุผล", max_length=20, choices=Reason.choices)
    detail = models.TextField("รายละเอียดเพิ่มเติม", blank=True)
    document_version = models.PositiveIntegerField("เวอร์ชันไฟล์ที่ถูก Report")
    status = models.CharField(
        "สถานะ", max_length=20, choices=Status.choices, default=Status.OPEN
    )
    resolution = models.CharField(
        "ผลการตัดสิน", max_length=20, choices=Resolution.choices, blank=True
    )
    decision = models.ForeignKey(
        "documents.DocumentReportDecision",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
        verbose_name="การตัดสิน",
    )
    created_at = models.DateTimeField("วันเวลาที่ Report", auto_now_add=True)
    closed_at = models.DateTimeField("วันเวลาที่ปิด", null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "reporter"],
                condition=models.Q(status=ReportStatus.OPEN),
                name="unique_open_report_per_user",
            )
        ]

    def __str__(self):
        return f"{self.document.title} - {self.get_reason_display()} ({self.get_status_display()})"

    @property
    def requires_detail(self) -> bool:
        return self.reason in self.REASONS_REQUIRING_DETAIL

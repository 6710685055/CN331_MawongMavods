from pathlib import Path

from django.conf import settings
from django.db import models

from courses.models import Course

from .validators import validate_document_file


def document_upload_path(instance, filename: str) -> str:
    safe_name = Path(filename).name
    course_code = instance.course.code if instance.course_id else "unknown"
    version = instance.version or 1
    return f"documents/{course_code}/v{version}/{safe_name}"


class Document(models.Model):
    class DocType(models.TextChoices):
        SUMMARY = "summary", "ชีทสรุป"
        EXAM = "exam", "แนวข้อสอบ"
        HOMEWORK = "homework", "การบ้าน"

    VERIFIABLE_DOC_TYPES = frozenset({DocType.SUMMARY, DocType.EXAM})

    class Semester(models.TextChoices):
        FIRST = "1", "เทอม 1"
        SECOND = "2", "เทอม 2"
        SUMMER = "summer", "ฤดูร้อน (Summer)"

    class VerifyStatus(models.TextChoices):
        NONE = "none", "ไม่มีสถานะ Verify"
        PENDING = "pending", "รอตรวจ"
        VERIFIED = "verified", "Verified"
        NEEDS_REVISION = "needs_revision", "ต้องแก้ไข"

    class VerifierRole(models.TextChoices):
        TA = "TA", "TA"
        TEACHER = "Teacher", "Teacher"

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name="รายวิชา",
    )
    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="uploaded_documents",
        verbose_name="ผู้อัปโหลด",
    )
    title = models.CharField("ชื่อเอกสาร", max_length=255)
    doc_type = models.CharField(
        "ประเภทเอกสาร", max_length=20, choices=DocType.choices
    )
    academic_year = models.PositiveSmallIntegerField("ปีการศึกษา (พ.ศ.)")
    semester = models.CharField(
        "ภาคการศึกษา", max_length=10, choices=Semester.choices
    )
    description = models.TextField("คำอธิบาย", blank=True)
    related_chapter = models.CharField("บทที่เกี่ยวข้อง", max_length=200, blank=True)

    file = models.FileField(
        "ไฟล์เอกสาร",
        upload_to=document_upload_path,
        validators=[validate_document_file],
    )
    original_filename = models.CharField("ชื่อไฟล์ต้นฉบับ", max_length=255, blank=True)
    file_size = models.PositiveBigIntegerField("ขนาดไฟล์ (Bytes)", default=0)
    version = models.PositiveIntegerField("เวอร์ชันไฟล์", default=1)
    vote_score = models.IntegerField("คะแนนโหวต", default=0)

    is_pinned = models.BooleanField("ปักหมุด", default=False)
    pinned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="ผู้ปักหมุด",
    )
    pinned_at = models.DateTimeField("วันเวลาที่ปักหมุด", null=True, blank=True)

    verify_status = models.CharField(
        "สถานะการตรวจสอบ",
        max_length=20,
        choices=VerifyStatus.choices,
        default=VerifyStatus.NONE,
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_documents",
        verbose_name="ผู้ตรวจ",
    )
    verified_by_name = models.CharField(
        "ชื่อผู้ตรวจ (Snapshot)", max_length=255, blank=True
    )
    verified_by_role = models.CharField(
        "บทบาทผู้ตรวจ (Snapshot)",
        max_length=20,
        choices=VerifierRole.choices,
        blank=True,
    )
    verified_at = models.DateTimeField("วันเวลาที่ Verify", null=True, blank=True)
    verified_version = models.PositiveIntegerField(
        "เวอร์ชันไฟล์ที่ Verify", null=True, blank=True
    )
    latest_review_comment = models.TextField("ความคิดเห็นผู้ตรวจล่าสุด", blank=True)

    created_at = models.DateTimeField("วันเวลาที่อัปโหลด", auto_now_add=True)
    updated_at = models.DateTimeField("แก้ไขล่าสุด", auto_now=True)

    class Meta:
        ordering = ["-is_pinned", "-pinned_at", "-created_at", "-id"]

    def __str__(self):
        return f"[{self.course.code}] {self.title} (v{self.version})"

    @classmethod
    def initial_verify_status_for_type(cls, doc_type: str) -> str:
        """Return initial verification status based on document type (UC3)."""
        if doc_type in cls.VERIFIABLE_DOC_TYPES:
            return cls.VerifyStatus.PENDING
        return cls.VerifyStatus.NONE

    @property
    def is_verifiable(self) -> bool:
        """True if this document type participates in UC4 verification."""
        return self.doc_type in self.VERIFIABLE_DOC_TYPES

    @property
    def is_homework(self) -> bool:
        return self.doc_type == self.DocType.HOMEWORK

    @property
    def has_active_verified_badge(self) -> bool:
        """True if verified on the current file version."""
        return bool(
            self.is_verifiable
            and self.verify_status == self.VerifyStatus.VERIFIED
            and self.verified_version == self.version
            and self.verified_by_role
        )

    def clear_verification(self) -> None:
        """Drop the verifier snapshot (in memory). Callers set verify_status and save."""
        self.verified_by = None
        self.verified_by_name = ""
        self.verified_by_role = ""
        self.verified_at = None
        self.verified_version = None

    @property
    def verified_badge_label(self) -> str:
        """Return 'Verified by TA' or 'Verified by Teacher' when active."""
        if not self.has_active_verified_badge:
            return ""
        return f"Verified by {self.verified_by_role}"


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
        return f"{self.document.title} v{self.document_version} - {self.get_action_display()} by {self.reviewer_name_snapshot}"

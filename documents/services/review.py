"""UC4: Verify Document (review queue, verify, request revision, revoke)."""

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification
from notifications.services import send_notification

from ..models import Document, DocumentReviewLog
from ..permissions import can_access_review_queue, get_reviewer_role_snapshot
from .errors import DocumentPermissionError, DocumentServiceError

_REVIEW_UPDATE_FIELDS = [
    "verify_status",
    "verified_by",
    "verified_by_name",
    "verified_by_role",
    "verified_at",
    "verified_version",
    "latest_review_comment",
    "updated_at",
]


def get_verification_queue(*, reviewer, course):
    """
    Return the FIFO queue of pending verifiable documents (SUMMARY, EXAM)
    excluding documents uploaded by the reviewer themselves (UC4).
    """
    if not can_access_review_queue(reviewer, course):
        raise DocumentPermissionError(
            "เฉพาะ TA ที่ได้รับอนุมัติและอาจารย์ผู้สอนของรายวิชานี้เท่านั้นที่สามารถเข้าถึงคิวเอกสารรอตรวจได้"
        )

    return (
        Document.objects.filter(
            course=course,
            doc_type__in=Document.VERIFIABLE_DOC_TYPES,
            verify_status=Document.VerifyStatus.PENDING,
        )
        .exclude(uploader=reviewer)
        .select_related("uploader", "course")
        .order_by("created_at", "id")
    )


def _check_reviewer_permissions(reviewer, document: Document) -> str:
    """Validate common UC4 permissions and return reviewer role snapshot ('TA' or 'Teacher')."""
    if not can_access_review_queue(reviewer, document.course):
        raise DocumentPermissionError(
            "เฉพาะ TA ที่ได้รับอนุมัติและอาจารย์ผู้สอนของรายวิชานี้เท่านั้นที่สามารถตรวจสอบเอกสารได้"
        )
    if not document.is_verifiable:
        raise DocumentServiceError("เอกสารประเภทการบ้านไม่สามารถ Verify ได้")
    if document.uploader_id == reviewer.id:
        raise DocumentPermissionError(
            "ผู้ตรวจไม่สามารถ Verify หรือตรวจสอบเอกสารที่ตนเองอัปโหลดได้ ต้องให้ TA คนอื่นหรืออาจารย์ผู้สอนตรวจ"
        )
    return get_reviewer_role_snapshot(reviewer, document.course)


def _document_detail_url(document: Document) -> str:
    return reverse(
        "documents:detail",
        kwargs={"course_id": document.course_id, "doc_id": document.id},
    )


def _record_review(
    *,
    document: Document,
    reviewer,
    reviewer_name: str,
    role_snapshot: str,
    action: str,
    comment: str,
    notification_type: str,
    title: str,
    message: str,
) -> None:
    """Save the review fields, write a DocumentReviewLog, and notify the owner. Call inside a transaction."""
    document.save(update_fields=_REVIEW_UPDATE_FIELDS)

    DocumentReviewLog.objects.create(
        document=document,
        reviewer=reviewer,
        reviewer_name_snapshot=reviewer_name,
        reviewer_role_snapshot=role_snapshot,
        action=action,
        document_version=document.version,
        comment=comment,
    )

    send_notification(
        recipient=document.uploader,
        actor=reviewer,
        notification_type=notification_type,
        title=title,
        message=message,
        target_url=_document_detail_url(document),
    )


def verify_document(*, reviewer, document: Document) -> Document:
    """
    Verify a summary/exam document (UC4).
    Snapshots verifier name, role ('TA'/'Teacher'), timestamp, and file version,
    then notifies the document owner.
    """
    role_snapshot = _check_reviewer_permissions(reviewer, document)
    reviewer_name = reviewer.full_name
    badge_text = f"Verified by {role_snapshot}"

    with transaction.atomic():
        document.verify_status = Document.VerifyStatus.VERIFIED
        document.verified_by = reviewer
        document.verified_by_name = reviewer_name
        document.verified_by_role = role_snapshot
        document.verified_at = timezone.now()
        document.verified_version = document.version
        document.latest_review_comment = ""

        _record_review(
            document=document,
            reviewer=reviewer,
            reviewer_name=reviewer_name,
            role_snapshot=role_snapshot,
            action=DocumentReviewLog.Action.VERIFY,
            comment="",
            notification_type=Notification.Type.DOCUMENT_VERIFIED,
            title=f"เอกสาร '{document.title}' ได้รับป้าย {badge_text}",
            message=(
                f"เอกสาร '{document.title}' (เวอร์ชัน {document.version}) ในวิชา {document.course.code} "
                f"ได้รับการยืนยันความถูกต้อง ({badge_text}) โดย {reviewer_name}"
            ),
        )

    return document


def request_document_revision(
    *, reviewer, document: Document, comment: str
) -> Document:
    """
    Return a document to the owner for revision with a required comment (UC4).
    """
    role_snapshot = _check_reviewer_permissions(reviewer, document)
    cleaned_comment = (comment or "").strip()
    if not cleaned_comment:
        raise DocumentServiceError("กรุณากรอกความคิดเห็นก่อนส่งกลับให้แก้ไข")

    reviewer_name = reviewer.full_name

    with transaction.atomic():
        document.verify_status = Document.VerifyStatus.NEEDS_REVISION
        document.clear_verification()
        document.latest_review_comment = cleaned_comment

        _record_review(
            document=document,
            reviewer=reviewer,
            reviewer_name=reviewer_name,
            role_snapshot=role_snapshot,
            action=DocumentReviewLog.Action.REQUEST_REVISION,
            comment=cleaned_comment,
            notification_type=Notification.Type.DOCUMENT_NEEDS_REVISION,
            title=f"เอกสาร '{document.title}' ถูกส่งกลับให้แก้ไข",
            message=(
                f"ผู้ตรวจ ({reviewer_name} - {role_snapshot}) ได้ส่งกลับเอกสาร '{document.title}' "
                f"ในวิชา {document.course.code} ให้แก้ไข พร้อมความคิดเห็น: \"{cleaned_comment}\""
            ),
        )

    return document


def revoke_document_verification(
    *, reviewer, document: Document, reason: str
) -> Document:
    """
    Revoke an active Verified badge with a required reason, setting status to NEEDS_REVISION (UC4).
    """
    role_snapshot = _check_reviewer_permissions(reviewer, document)
    if not document.has_active_verified_badge:
        raise DocumentServiceError("เอกสารนี้ยังไม่ได้รับการ Verify จึงไม่สามารถยกเลิกได้")

    cleaned_reason = (reason or "").strip()
    if not cleaned_reason:
        raise DocumentServiceError("กรุณาระบุเหตุผลในการยกเลิก Verify")

    reviewer_name = reviewer.full_name

    with transaction.atomic():
        document.verify_status = Document.VerifyStatus.NEEDS_REVISION
        document.clear_verification()
        document.latest_review_comment = cleaned_reason

        _record_review(
            document=document,
            reviewer=reviewer,
            reviewer_name=reviewer_name,
            role_snapshot=role_snapshot,
            action=DocumentReviewLog.Action.REVOKE_VERIFY,
            comment=cleaned_reason,
            notification_type=Notification.Type.DOCUMENT_VERIFY_REVOKED,
            title=f"เอกสาร '{document.title}' ถูกยกเลิกการ Verify",
            message=(
                f"ผู้ตรวจ ({reviewer_name} - {role_snapshot}) ได้ยกเลิกป้าย Verified ของเอกสาร '{document.title}' "
                f"ในวิชา {document.course.code} และเปลี่ยนสถานะเป็นต้องแก้ไข เหตุผล: \"{cleaned_reason}\""
            ),
        )

    return document

"""UC3: Upload & Share Document (library listing, upload, pin)."""

from pathlib import Path

from django.db import models, transaction
from django.utils import timezone

from ..models import Document
from ..permissions import can_access_course_documents, can_pin_document
from .errors import DocumentPermissionError, DocumentServiceError, _validate_file_or_raise


def list_course_documents(
    *,
    user,
    course,
    doc_type: str = "",
    semester: str = "",
    academic_year: str = "",
    verified_only: bool = False,
    query: str = "",
):
    """Return filtered queryset of documents in a course, with pinned items first."""
    if not can_access_course_documents(user, course):
        raise DocumentPermissionError(
            "เฉพาะผู้ที่ลงทะเบียนในรายวิชานี้เท่านั้นที่สามารถเข้าถึงคลังเอกสารได้"
        )

    qs = Document.objects.filter(course=course).select_related("uploader", "course")

    if doc_type:
        qs = qs.filter(doc_type=doc_type)
    if semester:
        qs = qs.filter(semester=semester)
    if academic_year and str(academic_year).isdigit():
        qs = qs.filter(academic_year=int(academic_year))
    if verified_only:
        qs = qs.filter(
            verify_status=Document.VerifyStatus.VERIFIED,
            verified_version=models.F("version"),
        )
    if query:
        q = query.strip()
        qs = qs.filter(
            models.Q(title__icontains=q)
            | models.Q(description__icontains=q)
            | models.Q(related_chapter__icontains=q)
        )

    return qs.order_by("-is_pinned", "-pinned_at", "-created_at", "-id")


def upload_document(
    *,
    user,
    course,
    title: str,
    doc_type: str,
    academic_year: int,
    semester: str,
    uploaded_file,
    description: str = "",
    related_chapter: str = "",
    is_pinned: bool = False,
    confirm_past_deadline: bool = False,
) -> Document:
    """
    Upload and share a new document in a course (UC3).
    Enforces server-side membership, file validation, homework confirmation,
    TA/Teacher pinning permission, and atomic cleanup on failure.
    """
    if not can_access_course_documents(user, course):
        raise DocumentPermissionError(
            "เฉพาะผู้ที่ลงทะเบียนในรายวิชานี้เท่านั้นที่สามารถอัปโหลดเอกสารได้"
        )

    title = (title or "").strip()
    if not title or not doc_type or not academic_year or not semester or not uploaded_file:
        raise DocumentServiceError(
            "กรุณากรอกข้อมูลบังคับให้ครบถ้วน (ชื่อเอกสาร, ประเภท, ปีการศึกษา, เทอม และไฟล์แนบ)"
        )

    valid_doc_types = {choice for choice, _ in Document.DocType.choices}
    if doc_type not in valid_doc_types:
        raise DocumentServiceError("ประเภทเอกสารไม่ถูกต้อง")

    if doc_type == Document.DocType.HOMEWORK and not confirm_past_deadline:
        raise DocumentServiceError(
            "การอัปโหลดเอกสารประเภทการบ้าน ต้องยืนยันว่าเป็นงานที่หมดกำหนดส่งแล้ว"
        )

    if is_pinned and not can_pin_document(user, course):
        raise DocumentPermissionError(
            "เฉพาะ TA ที่ได้รับอนุมัติหรืออาจารย์ผู้สอนของรายวิชานี้เท่านั้นที่สามารถปักหมุดเอกสารได้"
        )

    _validate_file_or_raise(uploaded_file)

    initial_status = Document.initial_verify_status_for_type(doc_type)
    now = timezone.now()
    doc = None

    try:
        with transaction.atomic():
            doc = Document(
                course=course,
                uploader=user,
                title=title,
                doc_type=doc_type,
                academic_year=academic_year,
                semester=semester,
                description=(description or "").strip(),
                related_chapter=(related_chapter or "").strip(),
                file=uploaded_file,
                original_filename=Path(uploaded_file.name).name,
                file_size=getattr(uploaded_file, "size", 0) or 0,
                version=1,
                vote_score=0,
                is_pinned=bool(is_pinned),
                pinned_by=user if is_pinned else None,
                pinned_at=now if is_pinned else None,
                verify_status=initial_status,
            )
            doc.save()
            return doc
    except DocumentServiceError:
        raise
    except Exception as exc:
        if doc is not None and getattr(doc, "file", None):
            try:
                doc.file.delete(save=False)
            except Exception:
                pass
        raise DocumentServiceError(
            "การอัปโหลดเอกสารล้มเหลวกลางทาง กรุณาลองใหม่อีกครั้ง"
        ) from exc


def toggle_document_pin(
    *, user, document: Document, pinned: bool | None = None
) -> Document:
    """Pin or unpin a document in a course (UC3). Restricted to course TA or Teacher."""
    if not can_pin_document(user, document.course):
        raise DocumentPermissionError(
            "เฉพาะ TA ที่ได้รับอนุมัติหรืออาจารย์ผู้สอนของรายวิชานี้เท่านั้นที่สามารถปักหมุดหรือเลิกปักหมุดเอกสารได้"
        )

    target_state = (not document.is_pinned) if pinned is None else bool(pinned)
    document.is_pinned = target_state
    if target_state:
        document.pinned_by = user
        document.pinned_at = timezone.now()
    else:
        document.pinned_by = None
        document.pinned_at = None

    document.save(update_fields=["is_pinned", "pinned_by", "pinned_at", "updated_at"])
    return document

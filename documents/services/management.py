"""Owner management actions for documents (US-12)."""

from django.db import transaction

from ..models import Document
from ..permissions import can_access_course_documents
from .errors import DocumentPermissionError, DocumentServiceError


def _require_document_owner(user, document):
    if not can_access_course_documents(user, document.course):
        raise DocumentPermissionError("คุณไม่ได้ลงทะเบียนในรายวิชานี้")
    if document.uploader_id != user.id:
        raise DocumentPermissionError(
            "เฉพาะเจ้าของเอกสารเท่านั้นที่สามารถแก้ไขหรือลบเอกสารได้"
        )


def update_document_metadata(
    *, user, document: Document, confirm_past_deadline=False, **metadata
) -> Document:
    """Update owner-editable fields without changing the document file/version."""
    _require_document_owner(user, document)
    allowed_fields = {
        "title",
        "doc_type",
        "academic_year",
        "semester",
        "related_chapter",
        "description",
    }
    if metadata.keys() - allowed_fields:
        raise ValueError("Unsupported document metadata field")
    title = (metadata.get("title") or "").strip()
    if not title:
        raise DocumentServiceError("กรุณากรอกชื่อเอกสาร")
    if metadata.get("doc_type") not in {value for value, _ in Document.DocType.choices}:
        raise DocumentServiceError("ประเภทเอกสารไม่ถูกต้อง")
    if metadata.get("semester") not in {value for value, _ in Document.Semester.choices}:
        raise DocumentServiceError("ภาคการศึกษาไม่ถูกต้อง")
    year = metadata.get("academic_year")
    if year is None or year < 2500 or year > 2700:
        raise DocumentServiceError(
            "กรุณาระบุปีการศึกษาเป็น พ.ศ. ที่ถูกต้อง (เช่น 2569)"
        )
    metadata["title"] = title
    metadata["related_chapter"] = (metadata.get("related_chapter") or "").strip()
    metadata["description"] = (metadata.get("description") or "").strip()

    with transaction.atomic():
        document = (
            Document.objects.select_for_update()
            .select_related("course")
            .get(pk=document.pk)
        )
        _require_document_owner(user, document)
        old_doc_type = document.doc_type
        if (
            metadata["doc_type"] == Document.DocType.HOMEWORK
            and old_doc_type != Document.DocType.HOMEWORK
            and not confirm_past_deadline
        ):
            raise DocumentServiceError(
                "การเปลี่ยนประเภทเป็นการบ้าน ต้องยืนยันว่าเป็นงานที่หมดกำหนดส่งแล้ว"
            )
        for field, value in metadata.items():
            setattr(document, field, value)

        if document.doc_type != old_doc_type:
            document.clear_verification()
            document.latest_review_comment = ""
            document.verify_status = Document.initial_verify_status_for_type(document.doc_type)

        document.save()
    return document


def delete_document(*, user, document: Document) -> str:
    """Permanently delete an owner's document and its stored file."""
    _require_document_owner(user, document)
    title = document.title
    with transaction.atomic():
        document = (
            Document.objects.select_for_update()
            .select_related("course")
            .get(pk=document.pk)
        )
        _require_document_owner(user, document)
        title = document.title
        file_field = document.file
        file_name = file_field.name if file_field else ""
        document.delete()  # Related votes, reports, and review logs cascade with the document.

    if file_name:
        storage = file_field.storage
        transaction.on_commit(lambda: storage.delete(file_name))
    return title

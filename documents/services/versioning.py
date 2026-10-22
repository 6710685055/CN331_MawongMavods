"""Replacing a document's file (connects UC4 with UC12)."""

from pathlib import Path

from django.db import transaction

from ..models import Document
from ..permissions import can_access_course_documents
from .errors import DocumentPermissionError, _validate_file_or_raise


def replace_document_file(*, user, document: Document, new_file) -> Document:
    """
    Update a document's file (connects UC4 with UC12).
    Increments file version, revokes any existing Verified badge,
    and returns verifiable documents to the PENDING queue.
    """
    if not can_access_course_documents(user, document.course):
        raise DocumentPermissionError("คุณไม่ได้ลงทะเบียนในรายวิชานี้")
    if document.uploader_id != user.id:
        raise DocumentPermissionError("เฉพาะเจ้าของเอกสารเท่านั้นที่สามารถอัปเดตไฟล์เอกสารได้")

    _validate_file_or_raise(new_file)

    with transaction.atomic():
        document.version += 1
        document.file = new_file
        document.original_filename = Path(new_file.name).name
        document.file_size = getattr(new_file, "size", 0) or 0

        if document.is_verifiable:
            document.verify_status = Document.VerifyStatus.PENDING
            document.clear_verification()

        document.save()

    return document

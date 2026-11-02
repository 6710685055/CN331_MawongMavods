"""Document business logic, split by use case. Import from here: `from documents.services import X`."""

from .errors import DocumentPermissionError, DocumentServiceError
from .feedback import report_document, vote_document, withdraw_report
from .library import list_course_documents, toggle_document_pin, upload_document
from .review import (
    get_verification_queue,
    request_document_revision,
    revoke_document_verification,
    verify_document,
)
from .versioning import replace_document_file

__all__ = [
    "DocumentPermissionError",
    "DocumentServiceError",
    "get_verification_queue",
    "list_course_documents",
    "replace_document_file",
    "report_document",
    "request_document_revision",
    "revoke_document_verification",
    "toggle_document_pin",
    "upload_document",
    "verify_document",
    "vote_document",
    "withdraw_report",
]

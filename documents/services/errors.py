from django.core.exceptions import ValidationError

from ..validators import validate_document_file


class DocumentServiceError(Exception):
    """Raised with a user-facing (Thai) business error message."""


class DocumentPermissionError(DocumentServiceError):
    """Raised when server-side authorization fails for a document operation."""


def _validate_file_or_raise(uploaded_file) -> None:
    """Run the document file validator, re-raising its first message as DocumentServiceError."""
    try:
        validate_document_file(uploaded_file)
    except ValidationError as exc:
        msg = exc.messages[0] if getattr(exc, "messages", None) else str(exc)
        raise DocumentServiceError(msg) from exc

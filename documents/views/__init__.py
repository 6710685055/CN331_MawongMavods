"""Document views, split by use case. `urls.py` refers to them as `views.<name>`."""

from .feedback import report_document_view, vote_document_view, withdraw_report_view
from .library import (
    document_detail,
    document_library,
    download_document,
    toggle_pin_view,
    upload_document_view,
)
from .review import (
    replace_file_view,
    request_revision_view,
    review_queue_view,
    revoke_verify_view,
    verify_document_view,
)

__all__ = [
    "document_detail",
    "document_library",
    "download_document",
    "replace_file_view",
    "report_document_view",
    "request_revision_view",
    "review_queue_view",
    "revoke_verify_view",
    "toggle_pin_view",
    "upload_document_view",
    "verify_document_view",
    "vote_document_view",
    "withdraw_report_view",
]

"""Compose and send document notifications. Business rules stay in the calling service."""

from django.urls import reverse

from notifications.models import Notification
from notifications.services import send_notification

from ..constants import feedback as texts
from ..models import Document
from ..selectors import course_staff_users, get_report_hide_threshold


def _document_detail_url(document: Document) -> str:
    return reverse(
        "documents:detail",
        kwargs={"course_id": document.course_id, "doc_id": document.id},
    )


def notify_document_hidden(document: Document) -> None:
    """Tell the owner and course staff that a document was hidden by reports (UC10). Never names reporters."""
    fields = {
        "title": document.title,
        "course_code": document.course.code,
        "threshold": get_report_hide_threshold(),
    }
    target_url = _document_detail_url(document)

    send_notification(
        recipient=document.uploader,
        notification_type=Notification.Type.DOCUMENT_HIDDEN,
        title=texts.HIDDEN_OWNER_TITLE.format(**fields),
        message=texts.HIDDEN_OWNER_MESSAGE.format(**fields),
        target_url=target_url,
    )
    for staff in course_staff_users(document.course).exclude(pk=document.uploader_id):
        send_notification(
            recipient=staff,
            notification_type=Notification.Type.DOCUMENT_HIDDEN,
            title=texts.HIDDEN_STAFF_TITLE.format(**fields),
            message=texts.HIDDEN_STAFF_MESSAGE.format(**fields),
            target_url=target_url,
        )

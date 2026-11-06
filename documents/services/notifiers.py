"""Compose and send document notifications. Business rules stay in the calling service."""

from django.contrib.auth import get_user_model
from django.urls import reverse

from notifications.models import Notification
from notifications.services import send_notification

from ..constants import feedback as texts
from ..constants import moderation as moderation_texts
from ..models import Document, DocumentReport, DocumentReportDecision
from ..selectors import course_staff_users, get_report_hide_threshold


def _document_detail_url(document: Document) -> str:
    return reverse(
        "documents:detail",
        kwargs={"course_id": document.course_id, "doc_id": document.id},
    )


def _document_url(document: Document) -> str:
    """Detail page, or the course library once the document is removed (its detail page is a 404)."""
    if document.is_removed:
        return reverse("documents:library", kwargs={"course_id": document.course_id})
    return _document_detail_url(document)


_Resolution = DocumentReport.Resolution

# Owner notification type per reviewer outcome. OWNER_DELETED has no entry: the owner acted themselves.
_OWNER_NOTIFICATION_TYPES = {
    _Resolution.DISMISSED: Notification.Type.DOCUMENT_REPORT_DISMISSED,
    _Resolution.REVISION: Notification.Type.DOCUMENT_NEEDS_REVISION,
    _Resolution.REMOVED: Notification.Type.DOCUMENT_REMOVED,
}


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


def _notify_owner_of_decision(decision: DocumentReportDecision) -> None:
    outcome = _Resolution(decision.outcome)
    notification_type = _OWNER_NOTIFICATION_TYPES.get(outcome)
    if notification_type is None:
        return

    document = decision.document
    key = outcome.name
    fields = {
        "title": document.title,
        "course_code": document.course.code,
        "reviewer": decision.reviewer_name_snapshot,
        "role": decision.reviewer_role_snapshot,
        "reason": decision.reason,
        "reason_suffix": (
            moderation_texts.OWNER_REASON_SUFFIX.format(reason=decision.reason)
            if decision.reason
            else ""
        ),
    }
    send_notification(
        recipient=document.uploader,
        actor=decision.reviewer,
        notification_type=notification_type,
        title=moderation_texts.OWNER_TITLE[key].format(**fields),
        message=moderation_texts.OWNER_MESSAGE[key].format(**fields),
        target_url=_document_url(document),
    )


def notify_report_decision(decision: DocumentReportDecision, reporter_ids) -> None:
    """
    UC14: tell the owner the outcome and reason (never the reporters' names),
    and tell every reporter that their report was handled, whatever the outcome.
    """
    document = decision.document
    _notify_owner_of_decision(decision)

    fields = {
        "title": document.title,
        "course_code": document.course.code,
        "outcome": decision.get_outcome_display(),
    }
    reporters = get_user_model().objects.filter(pk__in=list(reporter_ids))
    for reporter in reporters:
        send_notification(
            recipient=reporter,
            actor=decision.reviewer,
            notification_type=Notification.Type.DOCUMENT_REPORT_RESOLVED,
            title=moderation_texts.REPORTER_TITLE.format(**fields),
            message=moderation_texts.REPORTER_MESSAGE.format(**fields),
            target_url=_document_url(document),
        )

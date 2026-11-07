"""UC10: Upvote/Downvote/Report Document."""

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from ..constants import feedback as texts
from ..models import Document, DocumentReport, DocumentVote
from ..permissions import can_access_course_documents
from ..selectors import (
    get_report_detail_max_length,
    get_report_hide_threshold,
    has_dismissed_report,
    has_open_report,
    open_reporter_count,
    open_reports,
)
from .errors import DocumentPermissionError, DocumentServiceError
from .notifiers import notify_document_hidden


def _require_can_vote_or_report(user, document: Document) -> None:
    """Raise with the matching message when permissions.can_vote_or_report() would be False."""
    if not can_access_course_documents(user, document.course):
        raise DocumentPermissionError(texts.NOT_COURSE_MEMBER)
    if document.uploader_id == user.id:
        raise DocumentPermissionError(texts.OWNER_CANNOT_INTERACT)
    if document.is_hidden:
        raise DocumentPermissionError(texts.DOCUMENT_HIDDEN_NO_INTERACT)


def _recalculate_vote_score(document: Document) -> int:
    score = DocumentVote.objects.filter(document=document).aggregate(
        total=Coalesce(Sum("value"), 0)
    )["total"]
    Document.objects.filter(pk=document.pk).update(vote_score=score)
    document.vote_score = score
    return score


def vote_document(
    *, user, document: Document, value
) -> tuple[int, DocumentVote.Value | None]:
    """
    Toggle the user's vote (UC10): same value again removes it, the other value switches it.
    Returns (net score, the user's vote after the change or None).
    """
    _require_can_vote_or_report(user, document)
    try:
        value = DocumentVote.Value(value)
    except ValueError as exc:
        raise DocumentServiceError(texts.VOTE_INVALID) from exc

    with transaction.atomic():
        existing = (
            DocumentVote.objects.select_for_update()
            .filter(document=document, user=user)
            .first()
        )
        if existing is None:
            try:
                with transaction.atomic():
                    DocumentVote.objects.create(
                        document=document, user=user, value=value
                    )
                my_vote = value
            except IntegrityError:
                # A concurrent request created the vote first; treat this one as a change.
                DocumentVote.objects.filter(document=document, user=user).update(
                    value=value
                )
                my_vote = value
        elif existing.value == value:
            existing.delete()
            my_vote = None
        else:
            existing.value = value
            existing.save(update_fields=["value", "updated_at"])
            my_vote = value

        score = _recalculate_vote_score(document)

    return score, my_vote


def _clean_report_input(reason: str, detail: str) -> tuple[str, str]:
    if not reason:
        raise DocumentServiceError(texts.REPORT_REASON_REQUIRED)
    if reason not in DocumentReport.Reason.values:
        raise DocumentServiceError(texts.REPORT_REASON_INVALID)

    detail = (detail or "").strip()
    if reason in DocumentReport.REASONS_REQUIRING_DETAIL and not detail:
        raise DocumentServiceError(
            texts.REPORT_DETAIL_REQUIRED.format(
                reason=DocumentReport.Reason(reason).label
            )
        )
    max_length = get_report_detail_max_length()
    if len(detail) > max_length:
        raise DocumentServiceError(
            texts.REPORT_DETAIL_TOO_LONG.format(max_length=max_length)
        )
    return reason, detail


def _hide_if_threshold_reached(document: Document) -> bool:
    """Hide the document once distinct open reporters reach the threshold. Notifies only on the transition."""
    if open_reporter_count(document) < get_report_hide_threshold():
        return False
    hidden = Document.objects.filter(pk=document.pk, is_hidden=False).update(
        is_hidden=True, hidden_at=timezone.now()
    )
    document.refresh_from_db(fields=["is_hidden", "hidden_at"])
    if hidden:
        notify_document_hidden(document)
    return bool(hidden)


def report_document(
    *, user, document: Document, reason: str, detail: str = ""
) -> DocumentReport:
    """
    Report a document to the course TAs/Teachers (UC10).
    One open report per user per document (also enforced by a DB constraint);
    a report dismissed in UC14 blocks re-reporting until the file version changes.
    """
    _require_can_vote_or_report(user, document)
    reason, detail = _clean_report_input(reason, detail)

    if has_open_report(user, document):
        raise DocumentServiceError(texts.REPORT_DUPLICATE)
    if has_dismissed_report(user, document):
        raise DocumentServiceError(texts.REPORT_ALREADY_DISMISSED)

    try:
        with transaction.atomic():
            report = DocumentReport.objects.create(
                document=document,
                reporter=user,
                reason=reason,
                detail=detail,
                document_version=document.version,
            )
    except IntegrityError as exc:
        raise DocumentServiceError(texts.REPORT_DUPLICATE) from exc

    _hide_if_threshold_reached(document)
    return report


def withdraw_report(*, user, document: Document) -> None:
    """
    Withdraw the user's open report before a reviewer decides (UC10).
    A hidden document stays hidden for the reviewer unless no open reports remain.
    """
    with transaction.atomic():
        withdrawn = (
            open_reports(document)
            .filter(reporter=user)
            .update(status=DocumentReport.Status.WITHDRAWN, closed_at=timezone.now())
        )
        if not withdrawn:
            raise DocumentServiceError(texts.REPORT_NOTHING_TO_WITHDRAW)

        if not open_reports(document).exists():
            Document.objects.filter(pk=document.pk, is_hidden=True).update(
                is_hidden=False, hidden_at=None
            )
            document.refresh_from_db(fields=["is_hidden", "hidden_at"])

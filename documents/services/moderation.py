"""UC14: Review Reported Documents (queue, dismiss / send back / remove)."""

from django.db import transaction
from django.utils import timezone

from ..constants import moderation as texts
from ..models import Document, DocumentReport, DocumentReportDecision
from ..permissions import can_access_report_queue, get_reviewer_role_snapshot
from ..selectors import (
    decisions_for,
    get_decision_reason_max_length,
    open_reports,
    open_reports_with_reporters,
    reported_documents,
)
from .errors import DocumentPermissionError, DocumentServiceError
from .notifiers import notify_report_decision

Resolution = DocumentReport.Resolution

_HIDE_RESET_FIELDS = {"is_hidden": False, "hidden_at": None}


def get_reported_queue(*, reviewer, course):
    """Documents with open reports, hidden first then by report count; never the reviewer's own uploads."""
    if not can_access_report_queue(reviewer, course):
        raise DocumentPermissionError(texts.QUEUE_FORBIDDEN)
    return reported_documents(course, exclude_uploader=reviewer)


def _require_can_moderate(reviewer, document: Document) -> None:
    """Raise with the matching message when permissions.can_moderate_reports() would be False."""
    if not can_access_report_queue(reviewer, document.course):
        raise DocumentPermissionError(texts.QUEUE_FORBIDDEN)
    if document.uploader_id == reviewer.id:
        raise DocumentPermissionError(texts.CANNOT_MODERATE_OWN)
    if document.is_removed:
        raise DocumentServiceError(texts.DOCUMENT_ALREADY_REMOVED)


def get_report_review(*, reviewer, document: Document):
    """Return (open reports with reporter names, past decisions) for a reviewer."""
    _require_can_moderate(reviewer, document)
    return open_reports_with_reporters(document), decisions_for(document)


def _clean_decision_input(outcome, reason: str, confirmed: bool):
    try:
        outcome = Resolution(outcome)
    except ValueError as exc:
        raise DocumentServiceError(texts.OUTCOME_INVALID) from exc
    if outcome not in DocumentReport.REVIEWER_RESOLUTIONS:
        raise DocumentServiceError(texts.OUTCOME_INVALID)

    reason = (reason or "").strip()
    if outcome in DocumentReport.RESOLUTIONS_REQUIRING_REASON and not reason:
        raise DocumentServiceError(texts.REASON_REQUIRED.format(outcome=outcome.label))
    max_length = get_decision_reason_max_length()
    if len(reason) > max_length:
        raise DocumentServiceError(texts.REASON_TOO_LONG.format(max_length=max_length))
    if outcome in DocumentReport.RESOLUTIONS_REQUIRING_CONFIRMATION and not confirmed:
        raise DocumentServiceError(texts.REMOVE_CONFIRM_REQUIRED)
    return outcome, reason


# --- Outcome effects on the document (called inside the decision transaction) ---


def _apply_dismiss(document: Document, reviewer, reason: str) -> None:
    """Show the document again. The Verified badge is untouched; open report count is now 0."""
    Document.objects.filter(pk=document.pk).update(**_HIDE_RESET_FIELDS)


def _apply_revision(document: Document, reviewer, reason: str) -> None:
    """Back to the owner: status 'needs revision', Verified badge dropped, visible again."""
    document.verify_status = Document.VerifyStatus.NEEDS_REVISION
    document.clear_verification()
    document.latest_review_comment = reason
    for field, value in _HIDE_RESET_FIELDS.items():
        setattr(document, field, value)
    document.save(
        update_fields=[
            "verify_status",
            "verified_by",
            "verified_by_name",
            "verified_by_role",
            "verified_at",
            "verified_version",
            "latest_review_comment",
            *_HIDE_RESET_FIELDS,
            "updated_at",
        ]
    )


def _apply_remove(document: Document, reviewer, reason: str) -> None:
    """Soft delete: gone from the library and downloads (even if Verified). The file is deleted after commit."""
    file_field = document.file
    Document.all_objects.filter(pk=document.pk).update(
        removed_at=timezone.now(),
        removed_by=reviewer,
        removal_reason=reason,
        is_pinned=False,
        pinned_by=None,
        pinned_at=None,
        **_HIDE_RESET_FIELDS,
    )
    if file_field:
        storage, name = file_field.storage, file_field.name
        transaction.on_commit(lambda: storage.delete(name))


_APPLY_OUTCOME = {
    Resolution.DISMISSED: _apply_dismiss,
    Resolution.REVISION: _apply_revision,
    Resolution.REMOVED: _apply_remove,
}


def _close_open_reports(
    *, document: Document, reviewer, reviewer_name: str, role: str, outcome, reason: str
) -> DocumentReportDecision:
    """
    Record the decision and close every open report of the document in one transaction.
    Closing is a conditional UPDATE: if another reviewer already closed them, 0 rows change,
    ALREADY_HANDLED is raised and the decision row is rolled back (recorded only once).
    """
    decision = DocumentReportDecision.objects.create(
        document=document,
        reviewer=reviewer,
        reviewer_name_snapshot=reviewer_name,
        reviewer_role_snapshot=role,
        outcome=outcome,
        reason=reason,
        document_version=document.version,
    )
    closed = open_reports(document).update(
        status=DocumentReport.Status.RESOLVED,
        resolution=outcome,
        decision=decision,
        closed_at=timezone.now(),
    )
    if not closed:
        raise DocumentServiceError(texts.ALREADY_HANDLED)
    decision.report_count = closed
    decision.save(update_fields=["report_count"])
    return decision


def _notify_after_commit(
    decision: DocumentReportDecision, *, document: Document | None = None
) -> None:
    """
    Send the decision notifications once the transaction commits.
    Pass `document` when the row will be gone by then (owner hard delete, UC12): the in-memory
    instance is used instead of reloading it. Reporter ids are read now, while the reports still exist.
    """
    reporter_ids = list(
        DocumentReport.objects.filter(decision=decision)
        .values_list("reporter_id", flat=True)
        .distinct()
    )

    def _send():
        decision.document = document or Document.all_objects.select_related(
            "course", "uploader"
        ).get(pk=decision.document_id)
        notify_report_decision(decision, reporter_ids)

    transaction.on_commit(_send)


def resolve_reports(
    *, reviewer, document: Document, outcome, reason: str = "", confirmed: bool = False
) -> DocumentReportDecision:
    """
    Decide on all open reports of a document (UC14): dismiss, send back for revision, or remove.
    Reason is required for revision/removal and removal must be confirmed.
    """
    _require_can_moderate(reviewer, document)
    outcome, reason = _clean_decision_input(outcome, reason, confirmed)

    with transaction.atomic():
        decision = _close_open_reports(
            document=document,
            reviewer=reviewer,
            reviewer_name=reviewer.full_name,
            role=get_reviewer_role_snapshot(reviewer, document.course),
            outcome=outcome,
            reason=reason,
        )
        _APPLY_OUTCOME[outcome](document, reviewer, reason)
        _notify_after_commit(decision)

    document.refresh_from_db()  # uses the base manager, so a removed document still reloads
    return decision


def close_reports_for_owner_deletion(
    *, document: Document, owner
) -> DocumentReportDecision | None:
    """
    Hook for UC12: when the owner deletes their document, close its open reports and tell the reporters.
    Call it inside the deleting transaction, before `document.delete()`, with the same instance
    (services/management.py: delete_document). Returns None when there was nothing open to close.
    """
    if document.uploader_id != owner.id:
        raise DocumentPermissionError(texts.NOT_DOCUMENT_OWNER)
    try:
        with transaction.atomic():
            decision = _close_open_reports(
                document=document,
                reviewer=owner,
                reviewer_name=owner.full_name,
                role="",
                outcome=Resolution.OWNER_DELETED,
                reason="",
            )
            _notify_after_commit(decision, document=document)
    except DocumentServiceError:
        return None
    return decision

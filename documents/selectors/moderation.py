"""Read-only queries for UC14 (no side effects)."""

from collections import defaultdict

from django.conf import settings
from django.db.models import Count, Max, Q

from ..models import Document, DocumentReport, DocumentReportDecision
from .feedback import open_reports

_OPEN = Q(reports__status=DocumentReport.Status.OPEN)


def get_decision_reason_max_length() -> int:
    return int(getattr(settings, "DOCUMENT_REPORT_DECISION_REASON_MAX_LENGTH", 1000))


def reported_documents(course, *, exclude_uploader):
    """
    Documents in the course with open reports, hidden ones first, then by report count.
    Excludes documents uploaded by `exclude_uploader` (a reviewer never judges their own upload).
    """
    return (
        Document.objects.filter(_OPEN, course=course)
        .exclude(uploader=exclude_uploader)
        .annotate(
            open_report_count=Count("reports", filter=_OPEN, distinct=True),
            last_reported_at=Max("reports__created_at", filter=_OPEN),
        )
        .select_related("uploader", "course")
        .order_by("-is_hidden", "-open_report_count", "last_reported_at", "id")
    )


def reason_summary_for(documents) -> dict:
    """Map document id -> [(reason label, count), ...] over open reports, most frequent first."""
    rows = (
        DocumentReport.objects.filter(
            document__in=list(documents), status=DocumentReport.Status.OPEN
        )
        .values("document_id", "reason")
        .annotate(total=Count("id"))
        .order_by("document_id", "-total", "reason")
    )
    summary = defaultdict(list)
    for row in rows:
        summary[row["document_id"]].append(
            (DocumentReport.Reason(row["reason"]).label, row["total"])
        )
    return dict(summary)


def open_report_count(document: Document) -> int:
    return open_reports(document).count()


def open_reports_with_reporters(document: Document):
    """Open reports including reporter identity. Only for course reviewers, never for the owner."""
    return (
        open_reports(document).select_related("reporter").order_by("created_at", "id")
    )


def decisions_for(document: Document):
    return DocumentReportDecision.objects.filter(document=document).select_related(
        "reviewer"
    )

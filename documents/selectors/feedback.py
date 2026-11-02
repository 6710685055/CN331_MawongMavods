"""Read-only queries for UC10 (no side effects)."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q

from courses.models import Enrollment

from ..models import Document, DocumentReport, DocumentVote


def get_report_hide_threshold() -> int:
    return int(getattr(settings, "DOCUMENT_REPORT_HIDE_THRESHOLD", 5))


def get_report_detail_max_length() -> int:
    return int(getattr(settings, "DOCUMENT_REPORT_DETAIL_MAX_LENGTH", 1000))


def open_reports(document: Document):
    return DocumentReport.objects.filter(
        document=document, status=DocumentReport.Status.OPEN
    )


def open_reporter_count(document: Document) -> int:
    """Distinct users with an open report on the document."""
    return open_reports(document).values("reporter").distinct().count()


def has_open_report(user, document: Document) -> bool:
    return open_reports(document).filter(reporter=user).exists()


def has_dismissed_report(user, document: Document) -> bool:
    """True if the user's report on the document's current file version was dismissed (UC14)."""
    return DocumentReport.objects.filter(
        document=document,
        reporter=user,
        status=DocumentReport.Status.RESOLVED,
        resolution=DocumentReport.Resolution.DISMISSED,
        document_version=document.version,
    ).exists()


def user_vote_for(user, document: Document):
    """Return the user's DocumentVote.Value on the document, or None."""
    return user_votes_for(user, [document]).get(document.id)


def user_votes_for(user, documents) -> dict:
    """Map document id -> DocumentVote.Value for the given user."""
    rows = DocumentVote.objects.filter(
        user=user, document__in=list(documents)
    ).values_list("document_id", "value")
    return {doc_id: DocumentVote.Value(value) for doc_id, value in rows}


def user_open_report_doc_ids(user, documents) -> set:
    return set(
        DocumentReport.objects.filter(
            reporter=user,
            document__in=list(documents),
            status=DocumentReport.Status.OPEN,
        ).values_list("document_id", flat=True)
    )


def course_staff_users(course):
    """Approved TAs and approved Teachers of the course (same rule as courses.permissions.is_course_staff)."""
    User = get_user_model()
    return User.objects.filter(
        Q(enrollments__role=Enrollment.Role.TA)
        | Q(
            enrollments__role=Enrollment.Role.TEACHER,
            teacher_status=User.TeacherStatus.APPROVED,
        ),
        enrollments__course=course,
    ).distinct()

"""UC14 views: reported-documents queue, report review page, resolve reports."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from courses.models import Course

from ..constants import moderation as texts
from ..forms import ResolveReportsForm
from ..models import Document, DocumentReport
from ..selectors import reason_summary_for
from ..services import (
    DocumentPermissionError,
    DocumentServiceError,
    get_report_review,
    get_reported_queue,
    resolve_reports,
)

Resolution = DocumentReport.Resolution


def build_decision_options(document: Document) -> list[dict]:
    """Decision forms for the template, derived from DocumentReport.REVIEWER_RESOLUTIONS."""
    return [
        {
            "value": outcome.value,
            "label": outcome.label,
            "button": texts.DECISION_BUTTONS[outcome.name],
            "help": texts.DECISION_HELP[outcome.name],
            "style": texts.DECISION_BUTTON_STYLES[outcome.name],
            "requires_reason": outcome in DocumentReport.RESOLUTIONS_REQUIRING_REASON,
            "requires_confirmation": outcome in DocumentReport.RESOLUTIONS_REQUIRING_CONFIRMATION,
            "confirm_prompt": texts.REMOVE_CONFIRM_PROMPT.format(title=document.title),
        }
        for outcome in DocumentReport.REVIEWER_RESOLUTIONS
    ]


def _get_document(course_id, doc_id):
    course = get_object_or_404(Course, pk=course_id)
    document = get_object_or_404(
        Document.objects.select_related("uploader", "course"), pk=doc_id, course=course
    )
    return course, document


@login_required
def reported_queue_view(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    try:
        queue_documents = list(get_reported_queue(reviewer=request.user, course=course))
    except DocumentPermissionError as exc:
        return HttpResponseForbidden(str(exc))

    summaries = reason_summary_for(queue_documents)
    for doc in queue_documents:
        doc.reason_summary = summaries.get(doc.id, [])

    return render(
        request,
        "documents/reported_queue.html",
        {"course": course, "queue_documents": queue_documents},
    )


@login_required
def report_review_view(request, course_id, doc_id):
    course, document = _get_document(course_id, doc_id)
    try:
        reports, decisions = get_report_review(reviewer=request.user, document=document)
    except DocumentPermissionError as exc:
        return HttpResponseForbidden(str(exc))
    except DocumentServiceError as exc:
        messages.error(request, str(exc))
        return redirect("documents:reported_queue", course_id=course.id)

    return render(
        request,
        "documents/report_review.html",
        {
            "course": course,
            "document": document,
            "reports": reports,
            "decisions": decisions,
            "decision_options": build_decision_options(document),
            "form": ResolveReportsForm(),
        },
    )


@login_required
@require_POST
def resolve_reports_view(request, course_id, doc_id):
    course, document = _get_document(course_id, doc_id)

    form = ResolveReportsForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            messages.error(request, errors[0])
        return redirect("documents:report_review", course_id=course.id, doc_id=document.id)

    title = document.title
    try:
        decision = resolve_reports(
            reviewer=request.user,
            document=document,
            outcome=form.cleaned_data["outcome"],
            reason=form.cleaned_data["reason"],
            confirmed=form.cleaned_data["confirm_remove"],
        )
    except DocumentPermissionError as exc:
        return HttpResponseForbidden(str(exc))
    except DocumentServiceError as exc:
        messages.info(request, str(exc))
        return redirect("documents:reported_queue", course_id=course.id)

    outcome = Resolution(decision.outcome)
    messages.success(
        request,
        texts.DECISION_DONE[outcome.name].format(title=title, count=decision.report_count),
    )
    return redirect("documents:reported_queue", course_id=course.id)

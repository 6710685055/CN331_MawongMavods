"""UC10 views: vote, report, withdraw report."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from courses.models import Course

from ..constants import feedback as texts
from ..forms import ReportDocumentForm
from ..models import Document, DocumentVote
from ..permissions import can_view_document
from ..services import (
    DocumentPermissionError,
    DocumentServiceError,
    report_document,
    vote_document,
    withdraw_report,
)
from .common import _safe_redirect


def _wants_json(request) -> bool:
    return "application/json" in request.headers.get("Accept", "")


def _vote_name(value) -> str | None:
    """DocumentVote.Value -> 'up' / 'down' (the form and JSON representation)."""
    return value.name.lower() if value is not None else None


def build_vote_options(my_vote) -> list[dict]:
    """Vote buttons for templates, derived from DocumentVote.Value so nothing is hardcoded in HTML."""
    return [
        {
            "value": _vote_name(choice),
            "label": choice.label,
            "icon": texts.VOTE_ICONS.get(choice.name, choice.label),
            "active": choice == my_vote,
        }
        for choice in DocumentVote.Value
    ]


def vote_marker(my_vote) -> str:
    return texts.VOTE_MARKERS.get(my_vote.name, "") if my_vote is not None else ""


def _parse_vote(raw: str):
    try:
        return DocumentVote.Value[(raw or "").strip().upper()]
    except KeyError:
        return None


def _get_document(course_id, doc_id):
    course = get_object_or_404(Course, pk=course_id)
    return get_object_or_404(
        Document.objects.select_related("course"), pk=doc_id, course=course
    )


def _redirect_to_detail(request, document):
    """Back to the document, or to the library once the user can no longer see it (e.g. it just got hidden)."""
    if not can_view_document(request.user, document):
        return redirect("documents:library", course_id=document.course_id)
    return _safe_redirect(
        request, "documents:detail", course_id=document.course_id, doc_id=document.id
    )


@login_required
@require_POST
def vote_document_view(request, course_id, doc_id):
    document = _get_document(course_id, doc_id)
    wants_json = _wants_json(request)

    value = _parse_vote(request.POST.get("value"))
    if value is None:
        if wants_json:
            return JsonResponse({"error": texts.VOTE_INVALID}, status=400)
        messages.error(request, texts.VOTE_INVALID)
        return _redirect_to_detail(request, document)

    try:
        score, my_vote = vote_document(
            user=request.user, document=document, value=value
        )
    except DocumentPermissionError as exc:
        if wants_json:
            return JsonResponse({"error": str(exc)}, status=403)
        return HttpResponseForbidden(str(exc))
    except DocumentServiceError as exc:
        if wants_json:
            return JsonResponse({"error": str(exc)}, status=400)
        messages.error(request, str(exc))
        return _redirect_to_detail(request, document)

    if wants_json:
        return JsonResponse({"score": score, "my_vote": _vote_name(my_vote)})
    return _redirect_to_detail(request, document)


@login_required
@require_POST
def report_document_view(request, course_id, doc_id):
    document = _get_document(course_id, doc_id)

    form = ReportDocumentForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            messages.error(request, errors[0])
        return _redirect_to_detail(request, document)

    try:
        report_document(
            user=request.user,
            document=document,
            reason=form.cleaned_data["reason"],
            detail=form.cleaned_data["detail"],
        )
    except DocumentPermissionError as exc:
        return HttpResponseForbidden(str(exc))
    except DocumentServiceError as exc:
        messages.error(request, str(exc))
        return _redirect_to_detail(request, document)

    messages.success(request, texts.REPORT_SUBMITTED.format(title=document.title))
    return _redirect_to_detail(request, document)


@login_required
@require_POST
def withdraw_report_view(request, course_id, doc_id):
    document = _get_document(course_id, doc_id)

    try:
        withdraw_report(user=request.user, document=document)
    except DocumentServiceError as exc:
        messages.error(request, str(exc))
    else:
        messages.info(request, texts.REPORT_WITHDRAWN.format(title=document.title))
    return _redirect_to_detail(request, document)

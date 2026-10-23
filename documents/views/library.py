"""UC3 views: library, upload, detail, download, pin."""

from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from courses.models import Course

from ..forms import (
    DocumentUploadForm,
    ReplaceDocumentFileForm,
    RequestRevisionForm,
    RevokeVerifyForm,
)
from ..models import Document
from ..permissions import (
    can_access_course_documents,
    can_access_review_queue,
    can_pin_document,
    can_revoke_verification,
    can_verify_document,
    can_view_review_details,
)
from ..services import (
    DocumentPermissionError,
    DocumentServiceError,
    get_verification_queue,
    list_course_documents,
    toggle_document_pin,
    upload_document,
)
from .common import _safe_redirect


@login_required
def document_library(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    doc_type = request.GET.get("doc_type", "").strip()
    semester = request.GET.get("semester", "").strip()
    academic_year = request.GET.get("academic_year", "").strip()
    verified_only = request.GET.get("verified") == "1"
    q = request.GET.get("q", "").strip()

    try:
        documents_qs = list_course_documents(
            user=request.user,
            course=course,
            doc_type=doc_type,
            semester=semester,
            academic_year=academic_year,
            verified_only=verified_only,
            query=q,
        )
    except DocumentPermissionError as exc:
        return HttpResponseForbidden(str(exc))

    documents = list(documents_qs)
    for doc in documents:
        doc.show_review_details = can_view_review_details(request.user, doc)

    can_pin = can_pin_document(request.user, course)
    can_review = can_access_review_queue(request.user, course)
    pending_queue_count = 0
    if can_review:
        pending_queue_count = get_verification_queue(
            reviewer=request.user, course=course
        ).count()

    return render(
        request,
        "documents/library.html",
        {
            "course": course,
            "documents": documents,
            "can_pin": can_pin,
            "can_review": can_review,
            "pending_queue_count": pending_queue_count,
            "doc_types": Document.DocType.choices,
            "semesters": Document.Semester.choices,
            "filter_doc_type": doc_type,
            "filter_semester": semester,
            "filter_academic_year": academic_year,
            "filter_verified_only": verified_only,
            "filter_q": q,
        },
    )


@login_required
def upload_document_view(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if not can_access_course_documents(request.user, course):
        return HttpResponseForbidden(
            "เฉพาะผู้ที่ลงทะเบียนในรายวิชานี้เท่านั้นที่สามารถอัปโหลดเอกสารได้"
        )

    if request.method == "POST":
        form = DocumentUploadForm(
            request.POST, request.FILES, user=request.user, course=course
        )
        if form.is_valid():
            cd = form.cleaned_data
            try:
                doc = upload_document(
                    user=request.user,
                    course=course,
                    title=cd["title"],
                    doc_type=cd["doc_type"],
                    academic_year=cd["academic_year"],
                    semester=cd["semester"],
                    uploaded_file=cd["file"],
                    description=cd.get("description", ""),
                    related_chapter=cd.get("related_chapter", ""),
                    is_pinned=bool(cd.get("is_pinned", False)),
                    confirm_past_deadline=bool(cd.get("confirm_past_deadline", False)),
                )
            except DocumentPermissionError as exc:
                return HttpResponseForbidden(str(exc))
            except DocumentServiceError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request, f"อัปโหลดเอกสาร '{doc.title}' เข้าคลังเอกสารเรียบร้อยแล้ว"
                )
                return redirect("documents:library", course_id=course.id)
    else:
        form = DocumentUploadForm(user=request.user, course=course)

    return render(
        request,
        "documents/upload.html",
        {
            "course": course,
            "form": form,
            "can_pin": can_pin_document(request.user, course),
        },
    )


@login_required
def document_detail(request, course_id, doc_id):
    course = get_object_or_404(Course, pk=course_id)
    if not can_access_course_documents(request.user, course):
        return HttpResponseForbidden(
            "เฉพาะผู้ที่ลงทะเบียนในรายวิชานี้เท่านั้นที่สามารถเข้าถึงเอกสารได้"
        )

    document = get_object_or_404(
        Document.objects.select_related("uploader", "course"),
        pk=doc_id,
        course=course,
    )

    show_review_details = can_view_review_details(request.user, document)
    can_verify = can_verify_document(request.user, document)
    can_revoke = can_revoke_verification(request.user, document)
    can_pin = can_pin_document(request.user, course)
    is_owner = document.uploader_id == request.user.id

    review_logs = document.review_logs.all() if show_review_details else []

    return render(
        request,
        "documents/detail.html",
        {
            "course": course,
            "document": document,
            "show_review_details": show_review_details,
            "can_verify": can_verify,
            "can_revoke": can_revoke,
            "can_pin": can_pin,
            "is_owner": is_owner,
            "review_logs": review_logs,
            "revision_form": RequestRevisionForm(),
            "revoke_form": RevokeVerifyForm(),
            "replace_file_form": ReplaceDocumentFileForm() if is_owner else None,
        },
    )


@login_required
def download_document(request, course_id, doc_id):
    course = get_object_or_404(Course, pk=course_id)
    if not can_access_course_documents(request.user, course):
        return HttpResponseForbidden(
            "เฉพาะผู้ที่ลงทะเบียนในรายวิชานี้เท่านั้นที่สามารถดาวน์โหลดเอกสารได้"
        )

    document = get_object_or_404(Document, pk=doc_id, course=course)
    if not document.file:
        raise Http404("ไม่พบไฟล์เอกสาร")

    try:
        file_handle = document.file.open("rb")
    except FileNotFoundError as exc:
        raise Http404("ไม่พบไฟล์เอกสารในระบบ") from exc

    filename = document.original_filename or Path(document.file.name).name
    return FileResponse(file_handle, as_attachment=True, filename=filename)


@login_required
@require_POST
def toggle_pin_view(request, course_id, doc_id):
    course = get_object_or_404(Course, pk=course_id)
    document = get_object_or_404(Document, pk=doc_id, course=course)

    try:
        updated = toggle_document_pin(user=request.user, document=document)
    except DocumentPermissionError as exc:
        return HttpResponseForbidden(str(exc))

    if updated.is_pinned:
        messages.success(request, f"ปักหมุดเอกสาร '{updated.title}' ไว้บนสุดแล้ว")
    else:
        messages.info(request, f"เลิกปักหมุดเอกสาร '{updated.title}' แล้ว")

    return _safe_redirect(request, "documents:library", course_id=course.id)

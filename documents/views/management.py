"""Owner edit/delete endpoints for US-12."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from courses.models import Course

from ..forms import DocumentEditForm
from ..models import Document
from ..permissions import can_access_course_documents
from ..services import (
    DocumentPermissionError,
    DocumentServiceError,
    delete_document,
    update_document_metadata,
)


@login_required
def edit_document_view(request, course_id, doc_id):
    course = get_object_or_404(Course, pk=course_id)
    if not can_access_course_documents(request.user, course):
        return HttpResponseForbidden(
            "เฉพาะผู้ที่ลงทะเบียนในรายวิชานี้เท่านั้นที่สามารถแก้ไขเอกสารได้"
        )
    document = get_object_or_404(Document, pk=doc_id, course=course)
    if document.uploader_id != request.user.id:
        return HttpResponseForbidden("เฉพาะเจ้าของเอกสารเท่านั้นที่สามารถแก้ไขเอกสารได้")

    if request.method == "POST":
        form = DocumentEditForm(request.POST, instance=document)
        if form.is_valid():
            form_data = form.cleaned_data.copy()
            confirm_past_deadline = form_data.pop("confirm_past_deadline", False)
            try:
                document = update_document_metadata(
                    user=request.user,
                    document=document,
                    confirm_past_deadline=confirm_past_deadline,
                    **form_data,
                )
            except DocumentPermissionError as exc:
                return HttpResponseForbidden(str(exc))
            except DocumentServiceError as exc:
                messages.error(request, str(exc))
                return redirect("documents:edit", course_id=course.id, doc_id=document.id)
            messages.success(request, f"แก้ไขข้อมูลเอกสาร '{document.title}' เรียบร้อยแล้ว")
            return redirect("documents:detail", course_id=course.id, doc_id=document.id)
    else:
        form = DocumentEditForm(instance=document)

    return render(
        request,
        "documents/edit.html",
        {"course": course, "document": document, "form": form},
    )


@login_required
@require_POST
def delete_document_view(request, course_id, doc_id):
    course = get_object_or_404(Course, pk=course_id)
    document = get_object_or_404(Document, pk=doc_id, course=course)
    try:
        title = delete_document(user=request.user, document=document)
    except DocumentPermissionError as exc:
        return HttpResponseForbidden(str(exc))

    messages.success(request, f"ลบเอกสาร '{title}' เรียบร้อยแล้ว")
    return redirect("documents:library", course_id=course.id)

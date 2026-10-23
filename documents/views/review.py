"""UC4 views: review queue, verify, request revision, revoke, replace file."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from courses.models import Course

from ..forms import ReplaceDocumentFileForm, RequestRevisionForm, RevokeVerifyForm
from ..models import Document
from ..permissions import can_access_review_queue
from ..services import (
    DocumentPermissionError,
    DocumentServiceError,
    get_verification_queue,
    replace_document_file,
    request_document_revision,
    revoke_document_verification,
    verify_document,
)
from .common import _safe_redirect


@login_required
def review_queue_view(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    try:
        queue_documents = get_verification_queue(reviewer=request.user, course=course)
    except DocumentPermissionError as exc:
        return HttpResponseForbidden(str(exc))

    return render(
        request,
        "documents/review_queue.html",
        {
            "course": course,
            "queue_documents": queue_documents,
        },
    )


@login_required
@require_POST
def verify_document_view(request, course_id, doc_id):
    course = get_object_or_404(Course, pk=course_id)
    document = get_object_or_404(Document, pk=doc_id, course=course)

    try:
        verified_doc = verify_document(reviewer=request.user, document=document)
    except DocumentPermissionError as exc:
        return HttpResponseForbidden(str(exc))
    except DocumentServiceError as exc:
        messages.error(request, str(exc))
        return redirect("documents:detail", course_id=course.id, doc_id=document.id)

    messages.success(
        request,
        f"ยืนยันความถูกต้อง ({verified_doc.verified_badge_label}) สำหรับ '{verified_doc.title}' เรียบร้อยแล้ว",
    )
    return _safe_redirect(
        request, "documents:detail", course_id=course.id, doc_id=document.id
    )


@login_required
@require_POST
def request_revision_view(request, course_id, doc_id):
    course = get_object_or_404(Course, pk=course_id)
    document = get_object_or_404(Document, pk=doc_id, course=course)

    if not can_access_review_queue(request.user, course):
        return HttpResponseForbidden(
            "เฉพาะ TA ที่ได้รับอนุมัติและอาจารย์ผู้สอนของรายวิชานี้เท่านั้นที่สามารถส่งกลับเอกสารได้"
        )

    form = RequestRevisionForm(request.POST)
    if not form.is_valid():
        err_msg = form.errors.get("comment", ["กรุณากรอกความคิดเห็นก่อนส่งกลับให้แก้ไข"])[0]
        messages.error(request, err_msg)
        return redirect("documents:detail", course_id=course.id, doc_id=document.id)

    try:
        request_document_revision(
            reviewer=request.user,
            document=document,
            comment=form.cleaned_data["comment"],
        )
    except DocumentPermissionError as exc:
        return HttpResponseForbidden(str(exc))
    except DocumentServiceError as exc:
        messages.error(request, str(exc))
        return redirect("documents:detail", course_id=course.id, doc_id=document.id)

    messages.info(
        request,
        f"ส่งกลับเอกสาร '{document.title}' ให้เจ้าของแก้ไขพร้อมแจ้งเตือนเรียบร้อยแล้ว",
    )
    return _safe_redirect(
        request, "documents:detail", course_id=course.id, doc_id=document.id
    )


@login_required
@require_POST
def revoke_verify_view(request, course_id, doc_id):
    course = get_object_or_404(Course, pk=course_id)
    document = get_object_or_404(Document, pk=doc_id, course=course)

    if not can_access_review_queue(request.user, course):
        return HttpResponseForbidden(
            "เฉพาะ TA ที่ได้รับอนุมัติและอาจารย์ผู้สอนของรายวิชานี้เท่านั้นที่สามารถยกเลิก Verify ได้"
        )

    form = RevokeVerifyForm(request.POST)
    if not form.is_valid():
        err_msg = form.errors.get("reason", ["กรุณาระบุเหตุผลในการยกเลิก Verify"])[0]
        messages.error(request, err_msg)
        return redirect("documents:detail", course_id=course.id, doc_id=document.id)

    try:
        revoke_document_verification(
            reviewer=request.user,
            document=document,
            reason=form.cleaned_data["reason"],
        )
    except DocumentPermissionError as exc:
        return HttpResponseForbidden(str(exc))
    except DocumentServiceError as exc:
        messages.error(request, str(exc))
        return redirect("documents:detail", course_id=course.id, doc_id=document.id)

    messages.info(
        request,
        f"ยกเลิกป้าย Verified ของ '{document.title}' และเปลี่ยนสถานะเป็นต้องแก้ไขแล้ว",
    )
    return _safe_redirect(
        request, "documents:detail", course_id=course.id, doc_id=document.id
    )


@login_required
@require_POST
def replace_file_view(request, course_id, doc_id):
    course = get_object_or_404(Course, pk=course_id)
    document = get_object_or_404(Document, pk=doc_id, course=course)

    if document.uploader_id != request.user.id:
        return HttpResponseForbidden("เฉพาะเจ้าของเอกสารเท่านั้นที่สามารถอัปเดตไฟล์เอกสารได้")

    form = ReplaceDocumentFileForm(request.POST, request.FILES)
    if not form.is_valid():
        err_msg = form.errors.get("file", ["ไฟล์ที่อัปโหลดไม่ถูกต้อง"])[0]
        messages.error(request, err_msg)
        return redirect("documents:detail", course_id=course.id, doc_id=document.id)

    try:
        updated = replace_document_file(
            user=request.user,
            document=document,
            new_file=form.cleaned_data["file"],
        )
    except DocumentPermissionError as exc:
        return HttpResponseForbidden(str(exc))
    except DocumentServiceError as exc:
        messages.error(request, str(exc))
        return redirect("documents:detail", course_id=course.id, doc_id=document.id)

    messages.success(
        request,
        f"อัปเดตไฟล์เป็นเวอร์ชัน {updated.version} เรียบร้อยแล้ว",
    )
    return redirect("documents:detail", course_id=course.id, doc_id=document.id)

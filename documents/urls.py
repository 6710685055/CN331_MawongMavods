from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path(
        "courses/<int:course_id>/documents/",
        views.document_library,
        name="library",
    ),
    path(
        "courses/<int:course_id>/documents/upload/",
        views.upload_document_view,
        name="upload",
    ),
    path(
        "courses/<int:course_id>/documents/review-queue/",
        views.review_queue_view,
        name="review_queue",
    ),
    path(
        "courses/<int:course_id>/documents/<int:doc_id>/",
        views.document_detail,
        name="detail",
    ),
    path(
        "courses/<int:course_id>/documents/<int:doc_id>/download/",
        views.download_document,
        name="download",
    ),
    path(
        "courses/<int:course_id>/documents/<int:doc_id>/pin/",
        views.toggle_pin_view,
        name="toggle_pin",
    ),
    path(
        "courses/<int:course_id>/documents/<int:doc_id>/verify/",
        views.verify_document_view,
        name="verify",
    ),
    path(
        "courses/<int:course_id>/documents/<int:doc_id>/request-revision/",
        views.request_revision_view,
        name="request_revision",
    ),
    path(
        "courses/<int:course_id>/documents/<int:doc_id>/revoke-verify/",
        views.revoke_verify_view,
        name="revoke_verify",
    ),
    path(
        "courses/<int:course_id>/documents/<int:doc_id>/replace-file/",
        views.replace_file_view,
        name="replace_file",
    ),
]

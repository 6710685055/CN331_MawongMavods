from django.contrib import admin

from .models import Document, DocumentReviewLog


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "course",
        "doc_type",
        "uploader",
        "version",
        "verify_status",
        "is_pinned",
        "vote_score",
        "created_at",
    )
    list_filter = ("doc_type", "verify_status", "is_pinned", "course")
    search_fields = ("title", "description", "uploader__email", "course__code")


@admin.register(DocumentReviewLog)
class DocumentReviewLogAdmin(admin.ModelAdmin):
    list_display = (
        "document",
        "action",
        "reviewer_name_snapshot",
        "reviewer_role_snapshot",
        "document_version",
        "created_at",
    )
    list_filter = ("action", "reviewer_role_snapshot")

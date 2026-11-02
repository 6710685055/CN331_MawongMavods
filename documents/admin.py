from django.contrib import admin

from .models import Document, DocumentReport, DocumentReviewLog, DocumentVote


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
        "is_hidden",
        "vote_score",
        "created_at",
    )
    list_filter = ("doc_type", "verify_status", "is_pinned", "is_hidden", "course")
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


@admin.register(DocumentVote)
class DocumentVoteAdmin(admin.ModelAdmin):
    list_display = ("document", "user", "value", "updated_at")
    list_filter = ("value",)
    search_fields = ("document__title", "user__email")


@admin.register(DocumentReport)
class DocumentReportAdmin(admin.ModelAdmin):
    list_display = (
        "document",
        "reporter",
        "reason",
        "status",
        "resolution",
        "document_version",
        "created_at",
    )
    list_filter = ("status", "reason", "resolution")
    search_fields = ("document__title", "reporter__email", "detail")

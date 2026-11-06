from django.contrib import admin

from .models import (
    Document,
    DocumentReport,
    DocumentReportDecision,
    DocumentReviewLog,
    DocumentVote,
)


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
        "removed_at",
        "vote_score",
        "created_at",
    )
    list_filter = ("doc_type", "verify_status", "is_pinned", "is_hidden", "course")
    search_fields = ("title", "description", "uploader__email", "course__code")

    def get_queryset(self, request):
        # Include documents soft-deleted by a reviewer (UC14).
        return Document.all_objects.select_related("course", "uploader")


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


@admin.register(DocumentReportDecision)
class DocumentReportDecisionAdmin(admin.ModelAdmin):
    list_display = (
        "document",
        "outcome",
        "reviewer_name_snapshot",
        "reviewer_role_snapshot",
        "report_count",
        "created_at",
    )
    list_filter = ("outcome", "reviewer_role_snapshot")
    search_fields = ("document__title", "reviewer_name_snapshot", "reason")

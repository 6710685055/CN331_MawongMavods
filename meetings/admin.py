from django.contrib import admin

from .models import Meeting


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ("title", "starts_at", "created_by", "group_content_type", "group_object_id", "reminder_sent_at")
    list_filter = ("starts_at", "group_content_type")
    search_fields = ("title", "created_by__email")
    readonly_fields = ("created_at", "updated_at", "reminder_sent_at")

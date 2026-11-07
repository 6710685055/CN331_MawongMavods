from django import forms
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from .models import (
    Course,
    Enrollment,
    PrivateChat,
    PrivateChatIncident,
    PrivateChatMessage,
    PrivateChatModerationLog,
    PrivateChatSuspension,
    PrivateMessageReport,
    Team,
    TeamChat,
    TeamChatMessage,
    TeamInvitation,
    TeamMembership,
    UserBlock,
)
from .private_chat_moderation import can_review, decide_report, lift_suspension
from .private_chat_services import PrivateChatError


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("user", "course", "role", "created_at")
    list_filter = ("role", "course")


admin.site.register(Team)
admin.site.register(TeamMembership)
admin.site.register(TeamInvitation)
admin.site.register(TeamChat)
admin.site.register(TeamChatMessage)


class ReportReviewForm(forms.ModelForm):
    decision = forms.ChoiceField(
        label="ผลการพิจารณา",
        choices=[
            ("", "— เลือกผลการพิจารณา —"),
            (
                PrivateMessageReport.Status.CONFIRMED,
                "ยืนยันรายงาน (ซ่อนข้อความและดำเนินการกับผู้ส่ง)",
            ),
            (PrivateMessageReport.Status.REJECTED, "ปฏิเสธรายงาน (ข้อความแสดงตามปกติ)"),
        ],
    )

    class Meta:
        model = PrivateMessageReport
        fields = ["review_note"]

    def clean(self):
        cleaned = super().clean()
        # Re-read the row: another moderator may have decided it after this page loaded.
        if (
            self.instance.pk
            and not PrivateMessageReport.objects.filter(
                pk=self.instance.pk, status=PrivateMessageReport.Status.PENDING
            ).exists()
        ):
            raise forms.ValidationError("รายงานนี้ได้รับการพิจารณาไปแล้ว")
        return cleaned


@admin.register(PrivateMessageReport)
class PrivateMessageReportAdmin(admin.ModelAdmin):
    """Review queue. Reading needs view or review permission; deciding needs review permission."""

    form = ReportReviewForm
    list_display = (
        "created_at",
        "status",
        "course",
        "reporter",
        "reported_user",
        "reason",
    )
    list_filter = ("status", "reason", "course")
    search_fields = ("reporter__email", "reported_user__email", "message_body")
    evidence_fields = (
        "status",
        "course",
        "reporter",
        "reported_user",
        "reason",
        "details",
        "message_body",
        "message_sent_at",
        "created_at",
        "context_display",
    )
    decided_fields = ("reviewed_by", "reviewed_at", "review_note", "incident")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) or can_review(request.user)

    def has_change_permission(self, request, obj=None):
        pending = obj is None or obj.status == PrivateMessageReport.Status.PENDING
        return can_review(request.user) and pending

    def get_fields(self, request, obj=None):
        if obj is not None and self.has_change_permission(request, obj):
            return [*self.evidence_fields, "decision", "review_note"]
        return [*self.evidence_fields, *self.decided_fields]

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and self.has_change_permission(request, obj):
            return self.evidence_fields
        return [*self.evidence_fields, *self.decided_fields]

    @admin.display(description="บริบทข้อความใกล้เคียง (เฉพาะผู้ตรวจ)")
    def context_display(self, obj):
        if not obj.context_snapshot:
            return "-"
        return format_html(
            "<ol>{}</ol>",
            format_html_join(
                "",
                "<li{}><strong>{}</strong> ({}): {}</li>",
                (
                    (
                        (
                            format_html(
                                ' style="{}"', "font-weight:bold;background:#fff3cd"
                            )
                            if item.get("reported")
                            else ""
                        ),
                        item.get("sender_name", ""),
                        item.get("sent_at", ""),
                        item.get("body", ""),
                    )
                    for item in obj.context_snapshot
                ),
            ),
        )

    def save_model(self, request, obj, form, change):
        # The service does the write (compare-and-set on status) so a double submit
        # cannot issue a second warning or suspension.
        try:
            decide_report(
                report_id=obj.pk,
                reviewer=request.user,
                decision=form.cleaned_data["decision"],
                note=form.cleaned_data.get("review_note", ""),
            )
        except PrivateChatError as error:
            self.message_user(request, str(error), level=messages.ERROR)


class LiftSuspensionForm(forms.ModelForm):
    class Meta:
        model = PrivateChatSuspension
        fields = ["lift_reason"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lift_reason"].required = True

    def clean(self):
        cleaned = super().clean()
        if (
            self.instance.pk
            and not PrivateChatSuspension.objects.filter(
                pk=self.instance.pk, lifted_at__isnull=True, ends_at__gt=timezone.now()
            ).exists()
        ):
            raise forms.ValidationError("การระงับนี้สิ้นสุดหรือถูกยกเลิกไปแล้ว")
        return cleaned


@admin.register(PrivateChatSuspension)
class PrivateChatSuspensionAdmin(admin.ModelAdmin):
    """Saving the form with a reason lifts an active suspension early."""

    form = LiftSuspensionForm
    list_display = (
        "user",
        "counterpart",
        "starts_at",
        "ends_at",
        "is_active_display",
        "lifted_at",
    )
    list_filter = ("lifted_at",)
    search_fields = ("user__email", "counterpart__email")
    record_fields = (
        "incident",
        "user",
        "counterpart",
        "starts_at",
        "ends_at",
        "is_active_display",
    )
    lifted_fields = ("lifted_by", "lifted_at", "lift_reason")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) or can_review(request.user)

    def has_change_permission(self, request, obj=None):
        active = obj is None or obj.is_active(timezone.now())
        return can_review(request.user) and active

    def get_fields(self, request, obj=None):
        if obj is not None and self.has_change_permission(request, obj):
            return [*self.record_fields, "lift_reason"]
        return [*self.record_fields, *self.lifted_fields]

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and self.has_change_permission(request, obj):
            return self.record_fields
        return [*self.record_fields, *self.lifted_fields]

    @admin.display(description="กำลังมีผล", boolean=True)
    def is_active_display(self, obj):
        return obj.is_active(timezone.now())

    def save_model(self, request, obj, form, change):
        try:
            lift_suspension(
                suspension_id=obj.pk,
                actor=request.user,
                reason=form.cleaned_data["lift_reason"],
            )
        except PrivateChatError as error:
            self.message_user(request, str(error), level=messages.ERROR)


class ReadOnlyModerationAdmin(admin.ModelAdmin):
    """Audit records: visible to reviewers, never edited or deleted through admin."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) or can_review(request.user)


@admin.register(PrivateChatIncident)
class PrivateChatIncidentAdmin(ReadOnlyModerationAdmin):
    list_display = (
        "confirmed_at",
        "offender",
        "sequence",
        "action",
        "course",
        "confirmed_by",
    )
    list_filter = ("action", "course")
    search_fields = ("offender__email", "message_body")


@admin.register(PrivateChatModerationLog)
class PrivateChatModerationLogAdmin(ReadOnlyModerationAdmin):
    list_display = ("created_at", "action", "actor", "target_user", "note")
    list_filter = ("action",)
    search_fields = ("actor__email", "target_user__email", "note")


admin.site.register(PrivateChat)
admin.site.register(PrivateChatMessage)
admin.site.register(UserBlock)

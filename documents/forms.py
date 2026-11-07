from django import forms
from django.core.validators import MaxLengthValidator
from django.utils import timezone

from .constants import feedback as feedback_texts
from .constants import moderation as moderation_texts
from .models import Document, DocumentReport
from .permissions import can_pin_document
from .selectors import get_decision_reason_max_length, get_report_detail_max_length
from .validators import (
    get_allowed_extensions,
    get_allowed_extensions_display,
    get_max_file_size_mb,
    validate_document_file,
)


def _default_thai_academic_year() -> int:
    return timezone.now().year + 543


class DocumentUploadForm(forms.ModelForm):
    confirm_past_deadline = forms.BooleanField(
        label="ฉันยืนยันว่าการบ้านชิ้นนี้เป็นงานที่หมดกำหนดส่งแล้ว",
        required=False,
        help_text="จำเป็นต้องติ๊กยืนยันเมื่อเลือกประเภทเอกสารเป็น 'การบ้าน'",
    )

    class Meta:
        model = Document
        fields = [
            "title",
            "doc_type",
            "academic_year",
            "semester",
            "related_chapter",
            "description",
            "file",
            "is_pinned",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }
        error_messages = {
            "title": {"required": "กรุณากรอกชื่อเอกสาร"},
            "doc_type": {"required": "กรุณาเลือกประเภทเอกสาร"},
            "academic_year": {"required": "กรุณาระบุปีการศึกษา"},
            "semester": {"required": "กรุณาเลือกภาคการศึกษา"},
            "file": {"required": "กรุณาแนบไฟล์เอกสาร"},
        }

    def __init__(self, *args, user=None, course=None, **kwargs):
        self.user = user
        self.course = course
        super().__init__(*args, **kwargs)

        if not self.is_bound and not self.initial.get("academic_year"):
            self.initial["academic_year"] = _default_thai_academic_year()

        accept_attr = ",".join(get_allowed_extensions())
        self.fields["file"].widget.attrs["accept"] = accept_attr
        self.fields["file"].help_text = (
            f"รองรับไฟล์ {get_allowed_extensions_display()} ขนาดไม่เกิน {get_max_file_size_mb()}MB"
        )
        self.fields["related_chapter"].help_text = (
            "ไม่บังคับ (เช่น บทที่ 1-3 หรือ Midterm)"
        )
        self.fields["description"].help_text = "ไม่บังคับ"

        if can_pin_document(user, course):
            self.fields["is_pinned"].label = (
                "ปักหมุดเอกสารนี้ไว้บนสุดของคลังเอกสาร (Pin)"
            )
            self.fields["is_pinned"].help_text = (
                "สำหรับ TA และอาจารย์ผู้สอน (ไม่บังคับ)"
            )
        else:
            self.fields.pop("is_pinned", None)

    def clean_academic_year(self):
        year = self.cleaned_data.get("academic_year")
        if year is not None and (year < 2500 or year > 2700):
            raise forms.ValidationError(
                "กรุณาระบุปีการศึกษาเป็น พ.ศ. ที่ถูกต้อง (เช่น 2569)"
            )
        return year

    def clean(self):
        cleaned_data = super().clean()
        doc_type = cleaned_data.get("doc_type")
        confirmed = cleaned_data.get("confirm_past_deadline")

        if doc_type == Document.DocType.HOMEWORK and not confirmed:
            self.add_error(
                "confirm_past_deadline",
                "การอัปโหลดเอกสารประเภทการบ้าน ต้องติ๊กยืนยันว่าเป็นงานที่หมดกำหนดส่งแล้ว",
            )
        return cleaned_data


class DocumentEditForm(forms.ModelForm):
    """Owner-editable metadata for an existing document (US-12)."""

    confirm_past_deadline = forms.BooleanField(
        label="ฉันยืนยันว่าการบ้านชิ้นนี้เป็นงานที่หมดกำหนดส่งแล้ว",
        required=False,
        help_text="จำเป็นเมื่อต้องเปลี่ยนประเภทเอกสารเป็น 'การบ้าน'",
    )

    class Meta:
        model = Document
        fields = [
            "title",
            "doc_type",
            "academic_year",
            "semester",
            "related_chapter",
            "description",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip()
        if not title:
            raise forms.ValidationError("กรุณากรอกชื่อเอกสาร")
        return title

    def clean_academic_year(self):
        year = self.cleaned_data.get("academic_year")
        if year is not None and (year < 2500 or year > 2700):
            raise forms.ValidationError(
                "กรุณาระบุปีการศึกษาเป็น พ.ศ. ที่ถูกต้อง (เช่น 2569)"
            )
        return year

    def clean_related_chapter(self):
        return (self.cleaned_data.get("related_chapter") or "").strip()

    def clean_description(self):
        return (self.cleaned_data.get("description") or "").strip()

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("doc_type") == Document.DocType.HOMEWORK
            and self.instance.doc_type != Document.DocType.HOMEWORK
            and not cleaned_data.get("confirm_past_deadline")
        ):
            self.add_error(
                "confirm_past_deadline",
                "กรุณายืนยันว่าการบ้านชิ้นนี้หมดกำหนดส่งแล้ว",
            )
        return cleaned_data


class RequestRevisionForm(forms.Form):
    comment = forms.CharField(
        label="ความคิดเห็นสำหรับเจ้าของเอกสาร",
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "ระบุจุดที่ไม่ถูกต้องหรือสิ่งที่ต้องการให้แก้ไข...",
            }
        ),
        required=True,
        error_messages={"required": "กรุณากรอกความคิดเห็นก่อนส่งกลับให้แก้ไข"},
    )

    def clean_comment(self):
        comment = (self.cleaned_data.get("comment") or "").strip()
        if not comment:
            raise forms.ValidationError("กรุณากรอกความคิดเห็นก่อนส่งกลับให้แก้ไข")
        return comment


class RevokeVerifyForm(forms.Form):
    reason = forms.CharField(
        label="เหตุผลในการยกเลิก Verify",
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "ระบุเหตุผลที่ยกเลิกป้าย Verified ของเอกสารนี้...",
            }
        ),
        required=True,
        error_messages={"required": "กรุณาระบุเหตุผลในการยกเลิก Verify"},
    )

    def clean_reason(self):
        reason = (self.cleaned_data.get("reason") or "").strip()
        if not reason:
            raise forms.ValidationError("กรุณาระบุเหตุผลในการยกเลิก Verify")
        return reason


class ReplaceDocumentFileForm(forms.Form):
    file = forms.FileField(
        label="อัปโหลดไฟล์ฉบับแก้ไข (เวอร์ชันใหม่)",
        validators=[validate_document_file],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].widget.attrs["accept"] = ",".join(get_allowed_extensions())
        self.fields["file"].help_text = (
            f"เมื่ออัปโหลดไฟล์ใหม่ ระบบจะเพิ่มเลขเวอร์ชัน ยกเลิกป้าย Verified เดิม (ถ้ามี) "
            "และส่งเอกสารกลับเข้าคิวรอตรวจอัตโนมัติ "
            f"(รองรับ {get_allowed_extensions_display()} "
            f"ไม่เกิน {get_max_file_size_mb()}MB)"
        )


class ReportDocumentForm(forms.Form):
    reason = forms.ChoiceField(
        label="เหตุผลในการ Report",
        choices=DocumentReport.Reason.choices,
        widget=forms.RadioSelect,
        error_messages={
            "required": feedback_texts.REPORT_REASON_REQUIRED,
            "invalid_choice": feedback_texts.REPORT_REASON_INVALID,
        },
    )
    detail = forms.CharField(
        label="รายละเอียดเพิ่มเติม",
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": "อธิบายปัญหาที่พบในเอกสารนี้..."}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        max_length = get_report_detail_max_length()
        self.fields["detail"].widget.attrs["maxlength"] = max_length
        self.fields["detail"].validators.append(
            MaxLengthValidator(
                max_length,
                message=feedback_texts.REPORT_DETAIL_TOO_LONG.format(
                    max_length=max_length
                ),
            )
        )
        required_labels = ", ".join(
            DocumentReport.Reason(reason).label
            for reason in DocumentReport.REASONS_REQUIRING_DETAIL
        )
        self.fields["detail"].help_text = f"จำเป็นต้องกรอกเมื่อเลือก: {required_labels}"

    def clean(self):
        cleaned_data = super().clean()
        reason = cleaned_data.get("reason")
        detail = (cleaned_data.get("detail") or "").strip()
        cleaned_data["detail"] = detail
        if reason in DocumentReport.REASONS_REQUIRING_DETAIL and not detail:
            self.add_error(
                "detail",
                feedback_texts.REPORT_DETAIL_REQUIRED.format(
                    reason=DocumentReport.Reason(reason).label
                ),
            )
        return cleaned_data


class ResolveReportsForm(forms.Form):
    """One reviewer decision on all open reports of a document (UC14). Rules mirror services.resolve_reports."""

    outcome = forms.ChoiceField(
        choices=[
            (outcome.value, outcome.label)
            for outcome in DocumentReport.REVIEWER_RESOLUTIONS
        ],
        widget=forms.HiddenInput,
        error_messages={
            "required": moderation_texts.OUTCOME_INVALID,
            "invalid_choice": moderation_texts.OUTCOME_INVALID,
        },
    )
    reason = forms.CharField(
        label="เหตุผล",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm_remove = forms.BooleanField(
        label=moderation_texts.REMOVE_CONFIRM_LABEL, required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        max_length = get_decision_reason_max_length()
        self.fields["reason"].widget.attrs["maxlength"] = max_length
        self.fields["reason"].validators.append(
            MaxLengthValidator(
                max_length,
                message=moderation_texts.REASON_TOO_LONG.format(max_length=max_length),
            )
        )

    def clean(self):
        cleaned_data = super().clean()
        outcome = cleaned_data.get("outcome")
        if not outcome:
            return cleaned_data
        outcome = DocumentReport.Resolution(outcome)
        reason = (cleaned_data.get("reason") or "").strip()
        cleaned_data["reason"] = reason

        if outcome in DocumentReport.RESOLUTIONS_REQUIRING_REASON and not reason:
            self.add_error(
                "reason", moderation_texts.REASON_REQUIRED.format(outcome=outcome.label)
            )
        if (
            outcome in DocumentReport.RESOLUTIONS_REQUIRING_CONFIRMATION
            and not cleaned_data.get("confirm_remove")
        ):
            self.add_error("confirm_remove", moderation_texts.REMOVE_CONFIRM_REQUIRED)
        return cleaned_data

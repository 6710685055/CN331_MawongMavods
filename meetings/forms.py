from urllib.parse import urlparse

from django import forms
from django.utils import timezone

from .models import Meeting


class MeetingForm(forms.ModelForm):
    starts_at = forms.DateTimeField(
        label="วันและเวลา",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )

    class Meta:
        model = Meeting
        fields = ("title", "meeting_url", "starts_at")
        widgets = {
            "title": forms.TextInput(attrs={"maxlength": 160, "placeholder": "เช่น ทบทวนงาน Sprint"}),
            "meeting_url": forms.URLInput(attrs={"placeholder": "https://meet.google.com/..."}),
        }

    def clean_meeting_url(self):
        value = self.cleaned_data["meeting_url"].strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise forms.ValidationError("กรุณากรอกลิงก์ประชุมที่ขึ้นต้นด้วย http:// หรือ https://")
        return value

    def clean_starts_at(self):
        value = self.cleaned_data["starts_at"]
        if value <= timezone.now():
            raise forms.ValidationError("วันและเวลาประชุมต้องอยู่ในอนาคต")
        return value

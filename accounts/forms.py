from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import User


class RegisterForm(forms.ModelForm):
    ROLE_CHOICES = [
        (User.Role.STUDENT, "นักศึกษา (Student)"),
        (User.Role.TA, "ผู้ช่วยสอน (TA)"),
        (User.Role.TEACHER, "อาจารย์ (Teacher)"),
    ]

    role = forms.ChoiceField(label="ประเภทบัญชี", choices=ROLE_CHOICES)
    password1 = forms.CharField(
        label="รหัสผ่าน", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )
    password2 = forms.CharField(
        label="ยืนยันรหัสผ่าน",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "role"]
        labels = {"first_name": "ชื่อ", "last_name": "นามสกุล"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("อีเมลนี้ถูกใช้สมัครแล้ว กรุณาเข้าสู่ระบบหรือใช้อีเมลอื่น", code="duplicate")
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2:
            if p1 != p2:
                self.add_error("password2", "รหัสผ่านทั้งสองช่องไม่ตรงกัน")
            else:
                candidate = User(
                    email=cleaned.get("email", ""),
                    first_name=cleaned.get("first_name", ""),
                    last_name=cleaned.get("last_name", ""),
                )
                try:
                    validate_password(p1, candidate)
                except ValidationError as e:
                    self.add_error("password1", e)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        user.email_verified = False
        if user.role == User.Role.TEACHER:
            user.teacher_status = User.TeacherStatus.PENDING
        if commit:
            user.save()
        return user


class EmailLoginForm(AuthenticationForm):
    username = forms.EmailField(
        label="อีเมล", widget=forms.EmailInput(attrs={"autofocus": True})
    )

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.email_verified:
            raise ValidationError(
                "ยังไม่ได้ยืนยันอีเมล กรุณากดลิงก์ในอีเมลที่เราส่งให้ หรือขอส่งอีเมลยืนยันอีกครั้ง",
                code="unverified",
            )

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class ResendVerificationForm(forms.Form):
    email = forms.EmailField(label="อีเมลที่ใช้สมัคร")


class AdminUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "first_name", "last_name", "role")

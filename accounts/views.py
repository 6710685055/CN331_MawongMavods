from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render

from .emails import send_verification_email
from .forms import EmailLoginForm, RegisterForm, ResendVerificationForm
from .models import User
from .tokens import read_token


def register(request):
    if request.user.is_authenticated:
        return redirect("courses:my")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        send_verification_email(request, user)
        request.session["pending_verification_email"] = user.email
        return redirect("accounts:check_email")
    return render(request, "accounts/register.html", {"form": form})


def check_email(request):
    email = request.session.get("pending_verification_email")
    return render(request, "accounts/check_email.html", {"email": email})


def verify_email(request, token):
    data = read_token(token)
    user = User.objects.filter(pk=data["uid"], email=data["email"]).first() if data else None
    if user is None:
        return render(request, "accounts/verify_failed.html", status=400)
    if not user.email_verified:
        user.email_verified = True
        user.save(update_fields=["email_verified"])
    messages.success(request, "ยืนยันอีเมลเรียบร้อยแล้ว เข้าสู่ระบบได้เลย")
    return redirect("accounts:login")


def resend_verification(request):
    form = ResendVerificationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = User.objects.filter(
            email__iexact=form.cleaned_data["email"], email_verified=False
        ).first()
        if user:
            send_verification_email(request, user)
        # Same message either way, so this page can't be used to probe which emails exist.
        messages.info(
            request, "ถ้าอีเมลนี้สมัครไว้และยังไม่ได้ยืนยัน เราได้ส่งลิงก์ยืนยันไปให้แล้ว"
        )
        return redirect("accounts:login")
    return render(request, "accounts/resend_verification.html", {"form": form})


class LoginPage(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailLoginForm
    redirect_authenticated_user = True

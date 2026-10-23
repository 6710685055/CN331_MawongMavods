from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

from .tokens import make_token


def send_verification_email(request, user):
    url = request.build_absolute_uri(
        reverse("accounts:verify_email", args=[make_token(user)])
    )

    body = render_to_string(
        "accounts/verify_email.txt",
        {
            "user": user,
            "url": url,
        },
    )

    send_mail(
        subject="ยืนยันอีเมลของคุณ",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )

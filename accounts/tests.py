from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .models import User
from .tokens import make_token

PW = "Str0ng-pass-2026"


def register_payload(**over):
    data = {
        "first_name": "สมชาย",
        "last_name": "ใจดี",
        "email": "somchai@example.com",
        "role": "student",
        "password1": PW,
        "password2": PW,
    }
    data.update(over)
    return data


class RegisterTests(TestCase):
    def test_register_any_email_creates_unverified_user_and_sends_mail(self):
        r = self.client.post(reverse("accounts:register"), register_payload(email="a@gmail.com"))
        self.assertRedirects(r, reverse("accounts:check_email"))
        u = User.objects.get(email="a@gmail.com")
        self.assertFalse(u.email_verified)
        self.assertEqual(u.role, "student")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["a@gmail.com"])

    def test_duplicate_email_rejected_case_insensitive(self):
        User.objects.create_user("dup@example.com", PW)
        r = self.client.post(reverse("accounts:register"), register_payload(email="DUP@example.com"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_password_mismatch_and_weak_rejected(self):
        r = self.client.post(reverse("accounts:register"), register_payload(password2="different"))
        self.assertEqual(r.status_code, 200)
        r = self.client.post(
            reverse("accounts:register"), register_payload(password1="12345678", password2="12345678")
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.count(), 0)

    def test_teacher_starts_pending(self):
        self.client.post(reverse("accounts:register"), register_payload(role="teacher"))
        u = User.objects.get(email="somchai@example.com")
        self.assertEqual(u.teacher_status, "pending")

    def test_admin_role_cannot_be_self_selected(self):
        r = self.client.post(reverse("accounts:register"), register_payload(role="admin"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.count(), 0)


class VerifyAndLoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "u@example.com", PW, first_name="U", last_name="Ser", email_verified=False
        )

    def login(self):
        return self.client.post(reverse("accounts:login"), {"username": "u@example.com", "password": PW})

    def test_cannot_login_before_verification(self):
        r = self.login()
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_verify_then_login(self):
        r = self.client.get(reverse("accounts:verify_email", args=[make_token(self.user)]))
        self.assertRedirects(r, reverse("accounts:login"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)
        r = self.login()
        self.assertEqual(r.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_bad_token_rejected(self):
        r = self.client.get(reverse("accounts:verify_email", args=["not-a-token"]))
        self.assertEqual(r.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)

    def test_wrong_password_rejected(self):
        self.user.email_verified = True
        self.user.save()
        r = self.client.post(reverse("accounts:login"), {"username": "u@example.com", "password": "nope"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_resend_sends_only_for_unverified(self):
        self.client.post(reverse("accounts:resend_verification"), {"email": "u@example.com"})
        self.assertEqual(len(mail.outbox), 1)
        self.client.post(reverse("accounts:resend_verification"), {"email": "nobody@example.com"})
        self.assertEqual(len(mail.outbox), 1)


class PasswordResetTests(TestCase):
    def test_reset_email_sent_to_existing_user(self):
        User.objects.create_user("r@example.com", PW, email_verified=True)
        r = self.client.post(reverse("accounts:password_reset"), {"email": "r@example.com"})
        self.assertRedirects(r, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)

    def test_unknown_email_gets_same_response_but_no_mail(self):
        r = self.client.post(reverse("accounts:password_reset"), {"email": "x@example.com"})
        self.assertRedirects(r, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

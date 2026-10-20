from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from .models import Course, Enrollment
from .services import EnrollmentError, enroll

PW = "Str0ng-pass-2026"


def make_user(email, role="student", **kw):
    return User.objects.create_user(email, PW, role=role, email_verified=True, **kw)


class EnrollServiceTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(code="CN331", name="Software Engineering")

    def test_student_enrolls_as_student(self):
        e = enroll(make_user("s@x.com"), self.course)
        self.assertEqual(e.role, Enrollment.Role.STUDENT)

    def test_ta_enrolls_without_ta_rights(self):
        e = enroll(make_user("t@x.com", "ta"), self.course)
        self.assertEqual(e.role, Enrollment.Role.TA_PENDING)

    def test_pending_teacher_cannot_enroll(self):
        t = make_user("p@x.com", "teacher", teacher_status="pending")
        with self.assertRaises(EnrollmentError):
            enroll(t, self.course)
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_approved_teacher_enrolls_as_teacher(self):
        t = make_user("a@x.com", "teacher", teacher_status="approved")
        self.assertEqual(enroll(t, self.course).role, Enrollment.Role.TEACHER)

    def test_double_enroll_rejected(self):
        u = make_user("d@x.com")
        enroll(u, self.course)
        with self.assertRaises(EnrollmentError):
            enroll(u, self.course)
        self.assertEqual(Enrollment.objects.count(), 1)


class CourseViewTests(TestCase):
    def setUp(self):
        self.c1 = Course.objects.create(code="CN331", name="Software Engineering")
        Course.objects.create(code="CN310", name="Database Systems")
        self.user = make_user("s@x.com")

    def test_anonymous_redirected_to_login(self):
        r = self.client.get(reverse("courses:list"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("accounts:login"), r["Location"])

    def test_search_by_code_and_name(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("courses:list"), {"q": "cn331"})
        self.assertContains(r, "Software Engineering")
        self.assertNotContains(r, "Database Systems")
        r = self.client.get(reverse("courses:list"), {"q": "database"})
        self.assertContains(r, "CN310")

    def test_enroll_via_post_then_listed_in_my_courses(self):
        self.client.force_login(self.user)
        self.client.post(reverse("courses:enroll", args=[self.c1.id]))
        r = self.client.get(reverse("courses:my"))
        self.assertContains(r, "CN331")

    def test_enroll_requires_post(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("courses:enroll", args=[self.c1.id]))
        self.assertEqual(r.status_code, 405)

    def test_external_next_url_ignored(self):
        self.client.force_login(self.user)
        r = self.client.post(
            reverse("courses:enroll", args=[self.c1.id]), {"next": "https://evil.example/"}
        )
        self.assertRedirects(r, reverse("courses:list"))

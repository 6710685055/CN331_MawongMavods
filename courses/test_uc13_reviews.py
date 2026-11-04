from django.test import TestCase
from django.urls import reverse

from accounts.models import User

from .models import Course, CourseReview, Enrollment


PW = "Str0ng-pass-2026"


def make_user(email, role="student", **extra):
    return User.objects.create_user(email, PW, role=role, email_verified=True, **extra)


class CourseReviewViewsTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(code="CN331", name="Software Engineering")
        self.author = make_user("author@example.com")
        self.other = make_user("other@example.com")
        self.author_enrollment = Enrollment.objects.create(
            user=self.author,
            course=self.course,
            role=Enrollment.Role.STUDENT,
            completed=True,
        )
        self.review = CourseReview.objects.create(
            course=self.course,
            author=self.author,
            difficulty_rating=4,
            workload_rating=3,
            content="เนื้อหาดีและได้ฝึกทำโปรเจกต์",
        )

    def test_author_can_edit_review_and_course_list_shows_updated_values(self):
        self.client.force_login(self.author)
        response = self.client.post(
            reverse("courses:edit_review", args=[self.review.id]),
            {"difficulty_rating": 2, "workload_rating": 5, "content": "แก้ไขรีวิวแล้ว"},
        )

        self.assertRedirects(response, reverse("courses:reviews", args=[self.course.id]))
        self.review.refresh_from_db()
        self.assertEqual(self.review.difficulty_rating, 2)
        self.assertEqual(self.review.workload_rating, 5)
        self.assertEqual(self.review.content, "แก้ไขรีวิวแล้ว")
        self.assertContains(self.client.get(reverse("courses:reviews", args=[self.course.id])), "แก้ไขรีวิวแล้ว")

    def test_author_must_confirm_before_delete_and_delete_is_post_only(self):
        self.client.force_login(self.author)
        url = reverse("courses:delete_review", args=[self.review.id])
        self.assertContains(self.client.get(url), "ยืนยันการลบรีวิว")
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(CourseReview.objects.filter(pk=self.review.pk).exists())
        self.assertEqual(self.course.reviews.count(), 0)

    def test_non_author_cannot_edit_or_delete_even_by_direct_request(self):
        self.client.force_login(self.other)
        edit = reverse("courses:edit_review", args=[self.review.id])
        delete = reverse("courses:delete_review", args=[self.review.id])

        self.assertEqual(self.client.get(edit).status_code, 403)
        self.assertEqual(
            self.client.post(edit, {"difficulty_rating": 1, "workload_rating": 1, "content": "hijack"}).status_code,
            403,
        )
        self.assertEqual(self.client.get(delete).status_code, 403)
        self.assertEqual(self.client.post(delete).status_code, 403)
        self.review.refresh_from_db()
        self.assertEqual(self.review.content, "เนื้อหาดีและได้ฝึกทำโปรเจกต์")

    def test_review_form_rejects_ratings_outside_one_to_five(self):
        self.client.force_login(self.author)
        response = self.client.post(
            reverse("courses:edit_review", args=[self.review.id]),
            {"difficulty_rating": 6, "workload_rating": 0, "content": "ข้อความ"},
        )
        self.assertEqual(response.status_code, 200)
        self.review.refresh_from_db()
        self.assertEqual(self.review.difficulty_rating, 4)
        self.assertEqual(self.review.workload_rating, 3)

    def test_completed_student_can_create_one_review(self):
        self.review.delete()
        self.client.force_login(self.author)
        response = self.client.post(
            reverse("courses:reviews", args=[self.course.id]),
            {"difficulty_rating": 5, "workload_rating": 4, "content": "แนะนำวิชานี้"},
        )
        self.assertRedirects(response, reverse("courses:reviews", args=[self.course.id]))
        review = CourseReview.objects.get(course=self.course, author=self.author)
        self.assertEqual(review.content, "แนะนำวิชานี้")

    def test_student_who_has_not_completed_course_cannot_post_review(self):
        self.author_enrollment.completed = False
        self.author_enrollment.save(update_fields=["completed"])
        self.client.force_login(self.author)
        response = self.client.post(
            reverse("courses:reviews", args=[self.course.id]),
            {"difficulty_rating": 5, "workload_rating": 4, "content": "ไม่ควรบันทึก"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(CourseReview.objects.filter(course=self.course, author=self.author).count(), 1)

    def test_only_course_owner_can_change_student_completion_status(self):
        teacher = make_user(
            "teacher@example.com",
            role="teacher",
            teacher_status=User.TeacherStatus.APPROVED,
        )
        self.course.owner = teacher
        self.course.save(update_fields=["owner"])
        url = reverse(
            "courses:set_completed",
            args=[self.course.id, self.author_enrollment.id],
        )

        self.client.force_login(teacher)
        self.assertRedirects(
            self.client.post(url, {"completed": "1"}),
            reverse("courses:members", args=[self.course.id]),
        )
        self.author_enrollment.refresh_from_db()
        self.assertTrue(self.author_enrollment.completed)

        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url, {"completed": "0"}).status_code, 403)
        self.author_enrollment.refresh_from_db()
        self.assertTrue(self.author_enrollment.completed)

    def test_reviews_page_shows_alumni_badge_and_owner_controls_only(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("courses:reviews", args=[self.course.id]))
        self.assertContains(response, "🎓 Alumni")
        self.assertNotContains(response, reverse("courses:edit_review", args=[self.review.id]))

        self.client.force_login(self.author)
        response = self.client.get(reverse("courses:reviews", args=[self.course.id]))
        self.assertContains(response, reverse("courses:edit_review", args=[self.review.id]))
        self.assertContains(response, reverse("courses:delete_review", args=[self.review.id]))


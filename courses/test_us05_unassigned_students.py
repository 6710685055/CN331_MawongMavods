from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from notifications.models import Notification

from .models import (
    MAX_TEAM_MEMBERS,
    Course,
    Enrollment,
    Team,
    TeamInvitation,
    TeamMembership,
)

PW = "Str0ng-pass-2026"


def make_user(email, role=User.Role.STUDENT, **kwargs):
    return User.objects.create_user(
        email=email,
        password=PW,
        email_verified=True,
        role=role,
        **kwargs,
    )


class ManageUnassignedStudentsTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(code="CN331", name="Software Engineering")

        # Create TA
        self.ta = make_user("ta@example.com", role=User.Role.TA)
        Enrollment.objects.create(
            user=self.ta,
            course=self.course,
            role=Enrollment.Role.TA,
        )

        # Create Teacher (Owner)
        self.teacher = make_user(
            "teacher@example.com",
            role=User.Role.TEACHER,
            teacher_status=User.TeacherStatus.APPROVED,
        )
        self.course.owner = self.teacher
        self.course.save(update_fields=["owner"])
        Enrollment.objects.create(
            user=self.teacher,
            course=self.course,
            role=Enrollment.Role.TEACHER,
        )

        # Create 6 students
        self.students = [
            make_user(f"student{i}@example.com", first_name="Student", last_name=str(i))
            for i in range(1, 7)
        ]
        for student in self.students:
            Enrollment.objects.create(
                user=student,
                course=self.course,
                role=Enrollment.Role.STUDENT,
            )

        # Create 1 existing team with 1 creator student
        self.team1 = Team.objects.create(
            course=self.course,
            name="Team Alpha",
            created_by=self.students[0],
        )
        TeamMembership.objects.create(
            team=self.team1,
            course=self.course,
            user=self.students[0],
        )

    def test_ta_can_access_manage_unassigned_students_page(self):
        self.client.force_login(self.ta)
        response = self.client.get(
            reverse("courses:manage_unassigned_students", args=[self.course.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "จัดการกลุ่มนักศึกษา — CN331")
        self.assertContains(response, self.students[1].email)
        self.assertContains(response, "Team Alpha")
        self.assertContains(response, "จัดกลุ่มอัตโนมัติทั้งหมด")

    def test_teacher_can_also_access_manage_unassigned_students_page(self):
        self.client.force_login(self.teacher)
        response = self.client.get(
            reverse("courses:manage_unassigned_students", args=[self.course.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_student_cannot_access_manage_unassigned_students_page(self):
        self.client.force_login(self.students[1])
        response = self.client.get(
            reverse("courses:manage_unassigned_students", args=[self.course.id])
        )
        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(
            reverse("courses:manage_unassigned_students", args=[self.course.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_ta_can_assign_unassigned_student_to_existing_team(self):
        student = self.students[1]
        self.client.force_login(self.ta)
        response = self.client.post(
            reverse("courses:ta_assign_student", args=[self.course.id]),
            {"student_id": student.id, "team_id": self.team1.id},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            TeamMembership.objects.filter(
                team=self.team1,
                course=self.course,
                user=student,
            ).exists()
        )
        # Check notification sent to student
        notification = Notification.objects.filter(
            recipient=student,
            notification_type=Notification.Type.TEAM_MEMBERSHIP,
        ).first()
        self.assertIsNotNone(notification)
        self.assertIn("Team Alpha", notification.message)

    def test_assignment_cancels_pending_team_invitations(self):
        student = self.students[1]
        other_team = Team.objects.create(
            course=self.course,
            name="Team Beta",
            created_by=self.students[2],
        )
        TeamMembership.objects.create(
            team=other_team,
            course=self.course,
            user=self.students[2],
        )
        invitation = TeamInvitation.objects.create(
            team=other_team,
            inviter=self.students[2],
            invitee=student,
            status=TeamInvitation.Status.PENDING,
        )

        self.client.force_login(self.ta)
        self.client.post(
            reverse("courses:ta_assign_student", args=[self.course.id]),
            {"student_id": student.id, "team_id": self.team1.id},
        )

        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeamInvitation.Status.CANCELLED)

    def test_ta_cannot_assign_to_full_team(self):
        # Fill team1 up to MAX_TEAM_MEMBERS (5 members)
        for i in range(1, MAX_TEAM_MEMBERS):
            TeamMembership.objects.create(
                team=self.team1,
                course=self.course,
                user=self.students[i],
            )
        self.assertEqual(self.team1.memberships.count(), MAX_TEAM_MEMBERS)

        # Try to assign 6th student
        unassigned_student = self.students[5]
        self.client.force_login(self.ta)
        response = self.client.post(
            reverse("courses:ta_assign_student", args=[self.course.id]),
            {"student_id": unassigned_student.id, "team_id": self.team1.id},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"กลุ่ม &#x27;{self.team1.name}&#x27; เต็มแล้ว")
        self.assertFalse(
            TeamMembership.objects.filter(
                team=self.team1,
                user=unassigned_student,
            ).exists()
        )

    def test_ta_can_create_new_team_and_assign_selected_students(self):
        selected_students = [self.students[1], self.students[2], self.students[3]]
        self.client.force_login(self.ta)
        response = self.client.post(
            reverse("courses:ta_create_and_assign_team", args=[self.course.id]),
            {
                "name": "Team Gamma",
                "student_ids": [s.id for s in selected_students],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        team = Team.objects.get(name="Team Gamma", course=self.course)
        self.assertEqual(team.memberships.count(), 3)
        for s in selected_students:
            self.assertTrue(team.memberships.filter(user=s).exists())

    def test_ta_auto_assign_unassigned_students(self):
        # We have team1 with 1 member (capacity 5, slots = 4).
        # We have 5 unassigned students (students[1] through students[5]).
        # Auto-assign should put 4 into team1, and 1 into a newly created team.
        self.client.force_login(self.ta)
        response = self.client.post(
            reverse("courses:ta_auto_assign", args=[self.course.id]),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "จัดนักศึกษาที่ยังไม่มีกลุ่มเข้ากลุ่มอัตโนมัติสำเร็จทั้งหมด 5 คน"
        )

        # Verify all 6 students now have a team in this course
        for student in self.students:
            self.assertTrue(
                TeamMembership.objects.filter(
                    user=student, course=self.course
                ).exists(),
                f"{student.email} should have a team",
            )
        # Verify team1 is now full (5 members)
        self.assertEqual(self.team1.memberships.count(), MAX_TEAM_MEMBERS)

    def test_staff_visiting_groups_redirects_to_manage_page(self):
        self.client.force_login(self.ta)
        response = self.client.get(reverse("courses:groups", args=[self.course.id]))
        self.assertRedirects(
            response,
            reverse("courses:manage_unassigned_students", args=[self.course.id]),
        )

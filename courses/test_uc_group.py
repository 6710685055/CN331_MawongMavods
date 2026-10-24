from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from notifications.models import Notification

from .models import (
    Course,
    Enrollment,
    MAX_TEAM_MEMBERS,
    Team,
    TeamChat,
    TeamChatMessage,
    TeamInvitation,
    TeamMembership,
)

PW = "Str0ng-pass-2026"


def make_student(email):
    return User.objects.create_user(email, PW, email_verified=True)


class GroupFormationTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(code="CN331", name="Software Engineering")
        self.students = [
            make_student(f"student{i}@example.com")
            for i in range(1, MAX_TEAM_MEMBERS + 2)
        ]
        for student in self.students:
            Enrollment.objects.create(
                user=student,
                course=self.course,
                role=Enrollment.Role.STUDENT,
            )

    def login_as(self, user):
        self.client.force_login(user)

    def create_team(self, user=None, name="Team Alpha"):
        user = user or self.students[0]
        self.login_as(user)
        return self.client.post(
            reverse("courses:create_team", args=[self.course.id]),
            {"name": name},
        )

    def test_dashboard_shows_students_and_group_creation(self):
        self.login_as(self.students[0])
        response = self.client.get(reverse("courses:groups", args=[self.course.id]))
        self.assertContains(response, "ระบบจัดกลุ่ม")
        self.assertContains(response, self.students[1].email)
        self.assertContains(response, "สร้างกลุ่ม")

    def test_create_team_adds_creator_as_member(self):
        response = self.create_team()
        team = Team.objects.get(course=self.course)
        self.assertRedirects(response, reverse("courses:groups", args=[self.course.id]))
        self.assertTrue(
            TeamMembership.objects.filter(
                team=team,
                course=self.course,
                user=self.students[0],
            ).exists()
        )

    def test_invitation_notifies_friend_and_acceptance_creates_chat(self):
        self.create_team()
        team = Team.objects.get(course=self.course)
        self.client.post(
            reverse("courses:invite_to_team", args=[self.course.id, team.id]),
            {"invitee_ids": str(self.students[1].id)},
        )
        invitation = TeamInvitation.objects.get(team=team, invitee=self.students[1])
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.students[1],
                notification_type=Notification.Type.TEAM_INVITATION,
            ).exists()
        )

        self.login_as(self.students[1])
        response = self.client.post(
            reverse(
                "courses:respond_to_team_invitation",
                args=[self.course.id, invitation.id],
            ),
            {"action": "accept"},
        )
        self.assertRedirects(response, reverse("courses:groups", args=[self.course.id]))
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeamInvitation.Status.ACCEPTED)
        self.assertEqual(TeamMembership.objects.filter(team=team).count(), 2)
        chat = TeamChat.objects.get(team=team)

        response = self.client.post(
            reverse("courses:team_chat", args=[self.course.id, team.id]),
            {"body": "Hello group"},
        )
        self.assertRedirects(
            response,
            reverse("courses:team_chat", args=[self.course.id, team.id]),
        )
        self.assertTrue(
            TeamChatMessage.objects.filter(chat=chat, sender=self.students[1], body="Hello group").exists()
        )
        self.assertContains(
            self.client.get(reverse("courses:team_chat", args=[self.course.id, team.id])),
            "Hello group",
        )

    def test_declining_invitation_leaves_student_ungrouped_and_notifies_inviter(self):
        self.create_team()
        team = Team.objects.get(course=self.course)
        self.client.post(
            reverse("courses:invite_to_team", args=[self.course.id, team.id]),
            {"invitee_ids": str(self.students[1].id)},
        )
        invitation = TeamInvitation.objects.get(team=team, invitee=self.students[1])
        self.login_as(self.students[1])
        self.client.post(
            reverse(
                "courses:respond_to_team_invitation",
                args=[self.course.id, invitation.id],
            ),
            {"action": "decline"},
        )
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeamInvitation.Status.DECLINED)
        self.assertFalse(
            TeamMembership.objects.filter(user=self.students[1], course=self.course).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.students[0],
                notification_type=Notification.Type.TEAM_INVITATION_RESPONSE,
            ).exists()
        )

    def test_pending_invites_reserve_slots_and_group_never_exceeds_five(self):
        self.create_team()
        team = Team.objects.get(course=self.course)
        invite_url = reverse("courses:invite_to_team", args=[self.course.id, team.id])
        response = self.client.post(
            invite_url,
            {"invitee_ids": [str(student.id) for student in self.students[1:5]]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(team.available_slots, 0)
        response = self.client.get(reverse("courses:groups", args=[self.course.id]))
        self.assertNotContains(response, "ส่งคำเชิญที่เลือก")
        self.assertEqual(TeamInvitation.objects.filter(team=team).count(), 4)

        for student in self.students[1:5]:
            invitation = TeamInvitation.objects.get(team=team, invitee=student)
            self.login_as(student)
            self.client.post(
                reverse(
                    "courses:respond_to_team_invitation",
                    args=[self.course.id, invitation.id],
                ),
                {"action": "accept"},
            )
        self.assertEqual(team.memberships.count(), MAX_TEAM_MEMBERS)
        self.assertEqual(team.available_slots, 0)
        self.login_as(self.students[0])
        self.client.post(
            invite_url,
            {"invitee_ids": str(self.students[5].id)},
        )
        self.assertFalse(
            TeamInvitation.objects.filter(team=team, invitee=self.students[5]).exists()
        )

    def test_student_without_approved_course_enrollment_cannot_access_groups(self):
        student = make_student("pending@example.com")
        Enrollment.objects.create(
            user=student,
            course=self.course,
            role=Enrollment.Role.STUDENT_PENDING,
        )
        self.login_as(student)
        response = self.client.get(reverse("courses:groups", args=[self.course.id]))
        self.assertRedirects(response, reverse("courses:detail", args=[self.course.id]))

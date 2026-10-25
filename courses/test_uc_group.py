import tempfile

from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from accounts.models import User
from courses.consumers import TeamChatConsumer
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
        response = self.client.get(reverse("courses:groups", args=[self.course.id]))
        self.assertContains(response, "หัวหน้ากลุ่ม")

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
        chat_page = self.client.get(
            reverse("courses:team_chat", args=[self.course.id, team.id])
        )
        self.assertContains(chat_page, "หัวหน้ากลุ่ม")
        self.assertContains(chat_page, self.students[0].full_name)

        response = self.client.post(
            reverse("courses:team_chat", args=[self.course.id, team.id]),
            {"body": "Hello group"},
            follow=True,
        )
        self.assertRedirects(response, reverse("courses:team_chat", args=[self.course.id, team.id]))
        self.assertContains(response, "ส่งข้อความแล้ว")
        self.assertTrue(
            TeamChatMessage.objects.filter(chat=chat, sender=self.students[1], body="Hello group").exists()
        )
        self.assertContains(response, "Hello group")
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.students[0],
                notification_type=Notification.Type.TEAM_CHAT_MESSAGE,
                target_url=reverse("courses:team_chat", args=[self.course.id, team.id]),
            ).exists()
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

    def test_only_team_members_can_access_group_chat(self):
        self.create_team()
        team = Team.objects.get(course=self.course)
        TeamMembership.objects.create(
            team=team,
            course=self.course,
            user=self.students[1],
        )
        chat = TeamChat.objects.create(team=team)
        chat_url = reverse("courses:team_chat", args=[self.course.id, team.id])

        self.login_as(self.students[2])
        self.assertEqual(self.client.get(chat_url).status_code, 404)
        self.assertEqual(self.client.post(chat_url, {"body": "Not a member"}).status_code, 404)
        self.assertFalse(TeamChatMessage.objects.filter(chat=chat).exists())

    def test_blank_group_chat_message_is_not_saved(self):
        self.create_team()
        team = Team.objects.get(course=self.course)
        TeamMembership.objects.create(
            team=team,
            course=self.course,
            user=self.students[1],
        )
        chat = TeamChat.objects.create(team=team)

        response = self.client.post(
            reverse("courses:team_chat", args=[self.course.id, team.id]),
            {"body": "   "},
            follow=True,
        )

        self.assertFalse(TeamChatMessage.objects.filter(chat=chat).exists())
        self.assertContains(response, "กรุณาพิมพ์ข้อความหรือแนบไฟล์ก่อนส่ง")

    def test_leaving_as_team_creator_transfers_leadership_and_notifies_members(self):
        self.create_team()
        team = Team.objects.get(course=self.course)
        TeamMembership.objects.create(team=team, course=self.course, user=self.students[1])
        self.login_as(self.students[0])

        response = self.client.post(
            reverse("courses:leave_team", args=[self.course.id, team.id]),
            follow=True,
        )

        self.assertRedirects(response, reverse("courses:groups", args=[self.course.id]))
        self.assertFalse(
            TeamMembership.objects.filter(team=team, user=self.students[0]).exists()
        )
        team.refresh_from_db()
        self.assertEqual(team.created_by, self.students[1])
        self.assertFalse(
            TeamMembership.objects.filter(user=self.students[0], course=self.course).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.students[1],
                notification_type=Notification.Type.TEAM_MEMBERSHIP,
            ).exists()
        )
        self.assertContains(response, "โอนหัวหน้ากลุ่มให้")
        self.assertContains(response, "หัวหน้ากลุ่ม")

    def test_regular_member_can_leave_and_notifies_remaining_leader(self):
        self.create_team()
        team = Team.objects.get(course=self.course)
        TeamMembership.objects.create(team=team, course=self.course, user=self.students[1])
        self.login_as(self.students[1])

        self.client.post(reverse("courses:leave_team", args=[self.course.id, team.id]))

        self.assertTrue(Team.objects.filter(pk=team.id, created_by=self.students[0]).exists())
        self.assertFalse(
            TeamMembership.objects.filter(team=team, user=self.students[1]).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.students[0],
                actor=self.students[1],
                notification_type=Notification.Type.TEAM_MEMBERSHIP,
            ).exists()
        )

    def test_leaving_as_last_member_deletes_team_chat_and_messages(self):
        self.create_team()
        team = Team.objects.get(course=self.course)
        chat = TeamChat.objects.create(team=team)
        TeamChatMessage.objects.create(chat=chat, sender=self.students[0], body="Keep no history")
        self.login_as(self.students[0])

        response = self.client.post(
            reverse("courses:leave_team", args=[self.course.id, team.id]),
            follow=True,
        )

        self.assertRedirects(response, reverse("courses:groups", args=[self.course.id]))
        self.assertFalse(Team.objects.filter(pk=team.id).exists())
        self.assertFalse(TeamChat.objects.filter(pk=chat.id).exists())
        self.assertFalse(TeamChatMessage.objects.filter(chat_id=chat.id).exists())
        self.assertFalse(
            TeamMembership.objects.filter(user=self.students[0], course=self.course).exists()
        )
        self.assertContains(response, "ระบบยุบกลุ่ม")

    def test_non_member_cannot_leave_a_team(self):
        self.create_team()
        team = Team.objects.get(course=self.course)
        self.login_as(self.students[1])

        response = self.client.post(
            reverse("courses:leave_team", args=[self.course.id, team.id]),
            follow=True,
        )

        self.assertContains(response, "คุณไม่ได้เป็นสมาชิกของกลุ่มนี้")
        self.assertTrue(Team.objects.filter(pk=team.id).exists())
        self.assertTrue(
            TeamMembership.objects.filter(team=team, user=self.students[0]).exists()
        )

    def test_chat_attachment_is_downloadable_only_to_team_members(self):
        self.create_team()
        team = Team.objects.get(course=self.course)
        TeamMembership.objects.create(team=team, course=self.course, user=self.students[1])
        TeamChat.objects.create(team=team)
        self.login_as(self.students[1])

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    reverse("courses:team_chat", args=[self.course.id, team.id]),
                    {
                        "body": "เอกสารประชุม",
                        "attachment": SimpleUploadedFile(
                            "meeting.pdf",
                            b"meeting notes",
                            content_type="application/pdf",
                        ),
                    },
                    HTTP_ACCEPT="application/json",
                )

                self.assertEqual(response.status_code, 201)
                message = TeamChatMessage.objects.get(chat__team=team)
                self.assertEqual(message.attachment.name.rsplit("/", 1)[-1], "meeting.pdf")
                self.assertTrue(
                    Notification.objects.filter(
                        recipient=self.students[0],
                        notification_type=Notification.Type.TEAM_CHAT_MESSAGE,
                    ).exists()
                )
                download_url = reverse(
                    "courses:download_chat_attachment",
                    args=[self.course.id, team.id, message.id],
                )
                downloaded = self.client.get(download_url)
                self.assertEqual(b"".join(downloaded.streaming_content), b"meeting notes")

        self.login_as(self.students[2])
        self.assertEqual(self.client.get(download_url).status_code, 404)


class TeamChatWebsocketTests(TransactionTestCase):
    async def test_group_members_receive_new_messages_over_websocket(self):
        course = await self.create_chat_data()
        team = await self.get_team(course)
        user1, user2 = await self.get_members(team)
        path = f"/ws/courses/{course}/groups/{team}/chat/"
        url_route = {"kwargs": {"course_id": course, "team_id": team}}
        first = WebsocketCommunicator(TeamChatConsumer.as_asgi(), path)
        second = WebsocketCommunicator(TeamChatConsumer.as_asgi(), path)
        first.scope.update(user=user1, url_route=url_route)
        second.scope.update(user=user2, url_route=url_route)
        connected1, _ = await first.connect()
        connected2, _ = await second.connect()
        self.assertTrue(connected1)
        self.assertTrue(connected2)

        await first.send_json_to({"type": "message.send", "body": "Live update"})
        event1 = await first.receive_json_from()
        event2 = await second.receive_json_from()
        self.assertEqual(event1["type"], "message.new")
        self.assertEqual(event2["message"], event1["message"])
        self.assertEqual(event1["message"]["body"], "Live update")

        from asgiref.sync import sync_to_async

        await sync_to_async(
            TeamMembership.objects.filter(team_id=team, user_id=user2.id).delete
        )()
        await get_channel_layer().group_send(
            f"team_chat_{team}",
            {"type": "team.member_removed", "user_id": user2.id},
        )
        close_event = await second.receive_output()
        self.assertEqual(close_event["type"], "websocket.close")
        await first.send_json_to({"type": "message.send", "body": "Still a member"})
        await first.receive_json_from()
        await first.disconnect()
        await second.disconnect()

    @staticmethod
    async def create_chat_data():
        from asgiref.sync import sync_to_async

        @sync_to_async
        def create():
            course = Course.objects.create(code="WS101", name="WebSockets")
            users = [make_student(f"socket{i}@example.com") for i in range(2)]
            team = Team.objects.create(course=course, name="Realtime", created_by=users[0])
            for user in users:
                Enrollment.objects.create(user=user, course=course, role=Enrollment.Role.STUDENT)
                TeamMembership.objects.create(team=team, course=course, user=user)
            TeamChat.objects.create(team=team)
            return course.id

        return await create()

    @staticmethod
    async def get_team(course_id):
        from asgiref.sync import sync_to_async

        @sync_to_async
        def get():
            return Team.objects.get(course_id=course_id).id

        return await get()

    @staticmethod
    async def get_members(team_id):
        from asgiref.sync import sync_to_async

        @sync_to_async
        def get_users():
            return list(
                User.objects.filter(team_memberships__team_id=team_id).order_by("id")
            )

        return await get_users()

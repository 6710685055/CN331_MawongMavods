from unittest.mock import patch

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.db import IntegrityError, connection, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from courses.consumers import PrivateChatConsumer
from notifications.models import Notification

from .models import (
    Course,
    Enrollment,
    PrivateChat,
    PrivateChatMessage,
    PrivateMessageReport,
    UserBlock,
)
from .private_chat_services import (
    PRIVATE_CHAT_PAGE_SIZE,
    PrivateChatError,
    get_or_create_private_chat,
    post_private_message,
    report_message,
)

PW = "Str0ng-pass-2026"


def make_user(email, role=User.Role.STUDENT):
    return User.objects.create_user(
        email, PW, email_verified=True, role=role, first_name=email.split("@")[0]
    )


class PrivateChatTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.course = Course.objects.create(code="CN331", name="Software Engineering")
        cls.other_course = Course.objects.create(code="CN332", name="Other Course")
        cls.alice = make_user("alice@example.com")
        cls.bob = make_user("bob@example.com")
        cls.ta = make_user("ta@example.com", role=User.Role.TA)
        cls.outsider = make_user("outsider@example.com")
        cls.pending = make_user("pending@example.com")
        cls.teacher = make_user("teacher@example.com", role=User.Role.TEACHER)
        for user, role in (
            (cls.alice, Enrollment.Role.STUDENT),
            (cls.bob, Enrollment.Role.STUDENT),
            (cls.ta, Enrollment.Role.TA),
            (cls.pending, Enrollment.Role.STUDENT_PENDING),
            (cls.teacher, Enrollment.Role.TEACHER),
        ):
            Enrollment.objects.create(user=user, course=cls.course, role=role)
        Enrollment.objects.create(
            user=cls.outsider, course=cls.other_course, role=Enrollment.Role.STUDENT
        )

    def start_chat(self, user, other):
        self.client.force_login(user)
        return self.client.post(
            reverse("courses:start_private_chat", args=[self.course.id, other.id])
        )

    def make_chat(self, user=None, other=None):
        chat, _ = get_or_create_private_chat(
            course=self.course, user=user or self.alice, other=other or self.bob
        )
        return chat

    def chat_url(self, chat):
        return reverse("courses:private_chat", args=[self.course.id, chat.id])


class OpenPrivateChatTests(PrivateChatTestBase):
    def test_list_shows_classmates_with_send_button(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("courses:private_chats", args=[self.course.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "courses/private_chat_list.html")
        self.assertContains(response, self.bob.email)
        self.assertContains(response, self.ta.email)
        self.assertContains(response, "ส่งข้อความ")
        self.assertContains(response, "ยังไม่มีบทสนทนา")
        # Only approved students/TAs of the same course are listed.
        self.assertNotContains(response, self.outsider.email)
        self.assertNotContains(response, self.pending.email)
        self.assertNotContains(response, self.teacher.email)

    def test_course_detail_links_to_private_chat_for_students(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("courses:detail", args=[self.course.id]))
        self.assertContains(response, reverse("courses:private_chats", args=[self.course.id]))

    def test_list_requires_login(self):
        response = self.client.get(reverse("courses:private_chats", args=[self.course.id]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_non_eligible_user_cannot_open_list(self):
        for user in (self.outsider, self.pending, self.teacher):
            self.client.force_login(user)
            response = self.client.get(reverse("courses:private_chats", args=[self.course.id]))
            self.assertRedirects(response, reverse("courses:detail", args=[self.course.id]))

    def test_start_chat_creates_room_once_and_reopens_existing(self):
        response = self.start_chat(self.alice, self.bob)
        chat = PrivateChat.objects.get()
        self.assertRedirects(response, self.chat_url(chat))
        self.assertEqual(chat.course, self.course)
        self.assertEqual({chat.user_low, chat.user_high}, {self.alice, self.bob})

        # Same user again and the other participant both land in the same room.
        self.assertRedirects(self.start_chat(self.alice, self.bob), self.chat_url(chat))
        self.assertRedirects(self.start_chat(self.bob, self.alice), self.chat_url(chat))
        self.assertEqual(PrivateChat.objects.count(), 1)

    def test_empty_room_shows_empty_state(self):
        chat = self.make_chat()
        self.client.force_login(self.bob)
        response = self.client.get(self.chat_url(chat))
        self.assertTemplateUsed(response, "courses/private_chat.html")
        self.assertContains(response, "ยังไม่มีข้อความ")

    def test_student_can_chat_with_ta(self):
        response = self.start_chat(self.alice, self.ta)
        chat = PrivateChat.objects.get()
        self.assertRedirects(response, self.chat_url(chat))

    def test_cannot_start_chat_with_user_outside_course(self):
        response = self.start_chat(self.alice, self.outsider)
        self.assertRedirects(response, reverse("courses:private_chats", args=[self.course.id]))
        self.assertFalse(PrivateChat.objects.exists())

    def test_cannot_start_chat_with_pending_or_teacher(self):
        for other in (self.pending, self.teacher):
            self.start_chat(self.alice, other)
        self.assertFalse(PrivateChat.objects.exists())

    def test_non_member_cannot_start_chat_in_course(self):
        response = self.start_chat(self.outsider, self.alice)
        self.assertRedirects(response, reverse("courses:detail", args=[self.course.id]))
        self.assertFalse(PrivateChat.objects.exists())

    def test_cannot_start_chat_with_self(self):
        with self.assertRaises(PrivateChatError):
            get_or_create_private_chat(course=self.course, user=self.alice, other=self.alice)

    def test_start_chat_requires_post(self):
        self.client.force_login(self.alice)
        response = self.client.get(
            reverse("courses:start_private_chat", args=[self.course.id, self.bob.id])
        )
        self.assertEqual(response.status_code, 405)
        self.assertFalse(PrivateChat.objects.exists())

    def test_list_shows_existing_conversation_with_last_message(self):
        chat = self.make_chat()
        post_private_message(chat=chat, sender=self.bob, body="งานส่งวันไหน")
        self.client.force_login(self.alice)
        response = self.client.get(reverse("courses:private_chats", args=[self.course.id]))
        self.assertContains(response, "งานส่งวันไหน")
        self.assertContains(response, self.chat_url(chat))


class ChatListAccessTests(PrivateChatTestBase):
    """The list only offers rooms the chat page would actually open."""

    def setUp(self):
        self.chat = self.make_chat()
        post_private_message(chat=self.chat, sender=self.bob, body="ข้อความเก่าจากบ็อบ")
        self.list_url = reverse("courses:private_chats", args=[self.course.id])

    def listed_chats(self):
        self.client.force_login(self.alice)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        return response

    def assert_room_unlisted_but_kept(self):
        response = self.listed_chats()
        self.assertEqual(response.context["chats"], [])
        self.assertNotContains(response, self.chat_url(self.chat))
        self.assertNotContains(response, "ข้อความเก่าจากบ็อบ")
        self.assertContains(response, "ยังไม่มีบทสนทนา")
        # The room still refuses direct access, and nothing was deleted.
        self.assertEqual(self.client.get(self.chat_url(self.chat)).status_code, 404)
        self.assertTrue(PrivateChat.objects.filter(pk=self.chat.pk).exists())
        self.assertEqual(self.chat.messages.count(), 1)

    def test_room_with_eligible_partner_is_listed(self):
        response = self.listed_chats()
        self.assertEqual([chat.id for chat in response.context["chats"]], [self.chat.id])
        self.assertContains(response, self.chat_url(self.chat))
        self.assertContains(response, "ข้อความเก่าจากบ็อบ")
        self.assertEqual(self.client.get(self.chat_url(self.chat)).status_code, 200)

    def test_room_is_hidden_when_partner_leaves_the_course(self):
        Enrollment.objects.filter(user=self.bob, course=self.course).delete()
        self.assert_room_unlisted_but_kept()

    def test_room_is_hidden_when_partner_role_is_not_allowed(self):
        for role in (Enrollment.Role.TEACHER, Enrollment.Role.STUDENT_PENDING):
            Enrollment.objects.filter(user=self.bob, course=self.course).update(role=role)
            self.assert_room_unlisted_but_kept()

    def test_room_is_hidden_when_partner_account_is_inactive(self):
        User.objects.filter(pk=self.bob.pk).update(is_active=False)
        self.assert_room_unlisted_but_kept()

    def test_room_returns_when_partner_is_enrolled_again(self):
        Enrollment.objects.filter(user=self.bob, course=self.course).delete()
        Enrollment.objects.create(user=self.bob, course=self.course, role=Enrollment.Role.TA)
        self.assertEqual([chat.id for chat in self.listed_chats().context["chats"]], [self.chat.id])

    def test_list_does_not_show_other_peoples_rooms(self):
        other = self.make_chat(self.bob, self.ta)
        response = self.listed_chats()
        self.assertNotIn(other.id, [chat.id for chat in response.context["chats"]])

    def test_removed_partner_still_cannot_open_room_or_history(self):
        Enrollment.objects.filter(user=self.bob, course=self.course).delete()
        history_url = reverse("courses:private_chat_history", args=[self.course.id, self.chat.id])
        last_id = self.chat.messages.get().id
        for user in (self.alice, self.bob):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.chat_url(self.chat)).status_code, 404)
            self.assertEqual(self.client.get(history_url, {"before": last_id}).status_code, 404)

    def test_list_checks_access_without_a_query_per_room(self):
        def count_queries():
            with CaptureQueriesContext(connection) as queries:
                self.client.get(self.list_url)
            return len(queries)

        self.client.force_login(self.alice)
        one_room = count_queries()
        for classmate in (make_user(f"mate{i}@example.com") for i in range(5)):
            Enrollment.objects.create(user=classmate, course=self.course, role=Enrollment.Role.STUDENT)
            self.make_chat(self.alice, classmate)
        # Partner access is filtered in the room query itself; each extra room only adds
        # the existing last-message lookup.
        self.assertEqual(count_queries(), one_room + 5)


class DuplicateRoomTests(PrivateChatTestBase):
    def test_database_rejects_duplicate_pair_in_same_course(self):
        chat = self.make_chat()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PrivateChat.objects.create(
                course=self.course, user_low=chat.user_low, user_high=chat.user_high
            )

    def test_database_rejects_unordered_pair(self):
        low, high = sorted((self.alice, self.bob), key=lambda user: user.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PrivateChat.objects.create(course=self.course, user_low=high, user_high=low)

    def test_concurrent_create_falls_back_to_existing_room(self):
        existing = self.make_chat()
        # Simulate another request inserting the room between lookup and insert.
        with patch.object(
            PrivateChat.objects, "get_or_create", side_effect=IntegrityError("duplicate")
        ):
            chat, created = get_or_create_private_chat(
                course=self.course, user=self.bob, other=self.alice
            )
        self.assertEqual(chat, existing)
        self.assertFalse(created)
        self.assertEqual(PrivateChat.objects.count(), 1)

    def test_same_pair_gets_separate_room_per_course(self):
        Enrollment.objects.create(
            user=self.alice, course=self.other_course, role=Enrollment.Role.STUDENT
        )
        first = self.make_chat(self.alice, self.bob)
        Enrollment.objects.create(
            user=self.bob, course=self.other_course, role=Enrollment.Role.STUDENT
        )
        second, created = get_or_create_private_chat(
            course=self.other_course, user=self.alice, other=self.bob
        )
        self.assertTrue(created)
        self.assertNotEqual(first, second)


class SendMessageTests(PrivateChatTestBase):
    def test_send_message_saves_history_and_notifies_recipient(self):
        chat = self.make_chat()
        self.client.force_login(self.alice)
        response = self.client.post(self.chat_url(chat), {"body": "สวัสดี Bob"})
        self.assertRedirects(response, self.chat_url(chat))

        message = PrivateChatMessage.objects.get(chat=chat)
        self.assertEqual(message.sender, self.alice)
        self.assertEqual(message.body, "สวัสดี Bob")
        notification = Notification.objects.get(
            recipient=self.bob,
            notification_type=Notification.Type.PRIVATE_CHAT_MESSAGE,
        )
        self.assertEqual(notification.actor, self.alice)
        self.assertEqual(notification.target_url, self.chat_url(chat))
        self.assertFalse(Notification.objects.filter(recipient=self.alice).exists())

        self.client.force_login(self.bob)
        response = self.client.get(self.chat_url(chat))
        self.assertContains(response, "สวัสดี Bob")

    def test_send_message_as_json(self):
        chat = self.make_chat()
        self.client.force_login(self.alice)
        response = self.client.post(
            self.chat_url(chat), {"body": "hi"}, HTTP_ACCEPT="application/json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["message"]["body"], "hi")

    def test_blank_message_is_rejected(self):
        chat = self.make_chat()
        self.client.force_login(self.alice)
        response = self.client.post(self.chat_url(chat), {"body": "   "}, follow=True)
        self.assertContains(response, "กรุณาพิมพ์ข้อความก่อนส่ง")
        self.assertFalse(PrivateChatMessage.objects.exists())

        response = self.client.post(
            self.chat_url(chat), {"body": ""}, HTTP_ACCEPT="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_too_long_message_is_rejected(self):
        chat = self.make_chat()
        with self.assertRaises(PrivateChatError):
            post_private_message(chat=chat, sender=self.alice, body="x" * 4001)
        self.assertFalse(PrivateChatMessage.objects.exists())

    def test_message_body_is_html_escaped(self):
        chat = self.make_chat()
        post_private_message(chat=chat, sender=self.bob, body="<script>alert(1)</script>")
        self.client.force_login(self.alice)
        response = self.client.get(self.chat_url(chat))
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")


class UnauthorizedAccessTests(PrivateChatTestBase):
    def test_non_participant_cannot_read_or_send(self):
        chat = self.make_chat()
        post_private_message(chat=chat, sender=self.alice, body="secret")
        for intruder in (self.ta, self.outsider, self.teacher):
            self.client.force_login(intruder)
            self.assertEqual(self.client.get(self.chat_url(chat)).status_code, 404)
            response = self.client.post(self.chat_url(chat), {"body": "intrude"})
            self.assertEqual(response.status_code, 404)
        self.assertEqual(PrivateChatMessage.objects.count(), 1)

    def test_room_is_not_reachable_through_another_course_url(self):
        chat = self.make_chat()
        self.client.force_login(self.alice)
        url = reverse("courses:private_chat", args=[self.other_course.id, chat.id])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_participant_loses_access_after_leaving_course(self):
        chat = self.make_chat()
        Enrollment.objects.filter(user=self.bob, course=self.course).delete()
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(self.chat_url(chat)).status_code, 404)
        with self.assertRaises(PrivateChatError):
            post_private_message(chat=chat, sender=self.alice, body="still there?")

    def test_service_rejects_non_participant_sender(self):
        chat = self.make_chat()
        with self.assertRaises(PrivateChatError):
            post_private_message(chat=chat, sender=self.ta, body="hello")

    def test_anonymous_user_is_redirected_to_login(self):
        chat = self.make_chat()
        response = self.client.get(self.chat_url(chat))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_non_participant_cannot_block_or_report(self):
        chat = self.make_chat()
        message = post_private_message(chat=chat, sender=self.alice, body="hello")
        self.client.force_login(self.ta)
        block_url = reverse("courses:block_private_chat_user", args=[self.course.id, chat.id])
        report_url = reverse(
            "courses:report_private_message", args=[self.course.id, chat.id, message.id]
        )
        self.assertEqual(self.client.post(block_url).status_code, 404)
        self.assertEqual(self.client.post(report_url, {"reason": "spam"}).status_code, 404)
        self.assertFalse(UserBlock.objects.exists())
        self.assertFalse(PrivateMessageReport.objects.exists())


class BlockTests(PrivateChatTestBase):
    def block(self, chat, user):
        self.client.force_login(user)
        return self.client.post(
            reverse("courses:block_private_chat_user", args=[self.course.id, chat.id])
        )

    def test_block_prevents_both_sides_from_sending(self):
        chat = self.make_chat()
        response = self.block(chat, self.alice)
        self.assertRedirects(response, self.chat_url(chat))
        self.assertTrue(UserBlock.objects.filter(blocker=self.alice, blocked=self.bob).exists())

        for sender in (self.alice, self.bob):
            self.client.force_login(sender)
            response = self.client.post(self.chat_url(chat), {"body": "hello"}, follow=True)
            self.assertContains(response, "มีการบล็อกระหว่างคุณกับผู้ใช้นี้")
        self.assertFalse(PrivateChatMessage.objects.exists())
        self.assertFalse(
            Notification.objects.filter(
                notification_type=Notification.Type.PRIVATE_CHAT_MESSAGE
            ).exists()
        )

    def test_block_status_is_shown_and_composer_disabled(self):
        chat = self.make_chat()
        self.block(chat, self.alice)
        response = self.client.get(self.chat_url(chat))
        self.assertContains(response, "คุณบล็อกผู้ใช้นี้อยู่")
        self.assertTrue(response.context["blocked_by_me"])
        self.assertFalse(response.context["can_send"])

        self.client.force_login(self.bob)
        response = self.client.get(self.chat_url(chat))
        self.assertContains(response, "ไม่สามารถส่งข้อความในห้องนี้ได้")
        self.assertFalse(response.context["can_send"])

    def test_block_applies_across_courses(self):
        chat = self.make_chat()
        self.block(chat, self.bob)
        for course in (self.other_course,):
            Enrollment.objects.create(user=self.alice, course=course, role=Enrollment.Role.STUDENT)
            Enrollment.objects.create(user=self.bob, course=course, role=Enrollment.Role.STUDENT)
        other_chat, _ = get_or_create_private_chat(
            course=self.other_course, user=self.alice, other=self.bob
        )
        with self.assertRaises(PrivateChatError):
            post_private_message(chat=other_chat, sender=self.alice, body="hi")

    def test_unblock_allows_messages_again(self):
        chat = self.make_chat()
        self.block(chat, self.alice)
        response = self.client.post(
            reverse("courses:unblock_private_chat_user", args=[self.course.id, chat.id])
        )
        self.assertRedirects(response, self.chat_url(chat))
        self.assertFalse(UserBlock.objects.exists())
        post_private_message(chat=chat, sender=self.bob, body="กลับมาคุยได้แล้ว")
        self.assertEqual(PrivateChatMessage.objects.count(), 1)

    def test_blocked_user_cannot_lift_block(self):
        chat = self.make_chat()
        self.block(chat, self.alice)
        self.client.force_login(self.bob)
        self.client.post(
            reverse("courses:unblock_private_chat_user", args=[self.course.id, chat.id])
        )
        self.assertTrue(UserBlock.objects.filter(blocker=self.alice, blocked=self.bob).exists())

    def test_block_is_idempotent_and_requires_post(self):
        chat = self.make_chat()
        self.block(chat, self.alice)
        self.block(chat, self.alice)
        self.assertEqual(UserBlock.objects.count(), 1)
        response = self.client.get(
            reverse("courses:block_private_chat_user", args=[self.course.id, chat.id])
        )
        self.assertEqual(response.status_code, 405)

    def test_database_rejects_self_block(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            UserBlock.objects.create(blocker=self.alice, blocked=self.alice)


class ReportTests(PrivateChatTestBase):
    def setUp(self):
        self.chat = self.make_chat()
        self.message = post_private_message(chat=self.chat, sender=self.bob, body="ข้อความไม่เหมาะสม")
        self.report_url = reverse(
            "courses:report_private_message",
            args=[self.course.id, self.chat.id, self.message.id],
        )

    def test_recipient_can_report_message_with_review_data(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            self.report_url, {"reason": "harassment", "details": "พูดจาไม่สุภาพ"}, follow=True
        )
        self.assertRedirects(response, self.chat_url(self.chat))
        self.assertContains(response, "ส่งรายงานข้อความแล้ว")
        self.assertContains(response, "รายงานแล้ว")

        report = PrivateMessageReport.objects.get()
        self.assertEqual(report.message, self.message)
        self.assertEqual(report.reporter, self.alice)
        self.assertEqual(report.reported_user, self.bob)
        self.assertEqual(report.course, self.course)
        self.assertEqual(report.reason, PrivateMessageReport.Reason.HARASSMENT)
        self.assertEqual(report.details, "พูดจาไม่สุภาพ")
        self.assertEqual(report.message_body, "ข้อความไม่เหมาะสม")
        self.assertEqual(report.message_sent_at, self.message.created_at)

    def test_report_keeps_evidence_after_message_is_deleted(self):
        report = report_message(message=self.message, reporter=self.alice, reason="spam")
        self.message.delete()
        report.refresh_from_db()
        self.assertIsNone(report.message)
        self.assertEqual(report.message_body, "ข้อความไม่เหมาะสม")

    def test_cannot_report_own_message(self):
        self.client.force_login(self.bob)
        response = self.client.post(self.report_url, {"reason": "spam"}, follow=True)
        self.assertContains(response, "ไม่สามารถรายงานข้อความของตัวเองได้")
        self.assertFalse(PrivateMessageReport.objects.exists())

    def test_report_requires_valid_reason(self):
        self.client.force_login(self.alice)
        response = self.client.post(self.report_url, {"reason": "bogus"}, follow=True)
        self.assertContains(response, "กรุณาเลือกเหตุผลในการรายงาน")
        self.assertFalse(PrivateMessageReport.objects.exists())

    def test_report_details_length_is_limited(self):
        with self.assertRaises(PrivateChatError):
            report_message(
                message=self.message, reporter=self.alice, reason="other", details="x" * 1001
            )

    def test_duplicate_report_is_rejected(self):
        self.client.force_login(self.alice)
        self.client.post(self.report_url, {"reason": "spam"})
        response = self.client.post(self.report_url, {"reason": "spam"}, follow=True)
        self.assertContains(response, "คุณรายงานข้อความนี้ไปแล้ว")
        self.assertEqual(PrivateMessageReport.objects.count(), 1)

    def test_report_is_allowed_while_blocked(self):
        UserBlock.objects.create(blocker=self.alice, blocked=self.bob)
        report_message(message=self.message, reporter=self.alice, reason="harassment")
        self.assertEqual(PrivateMessageReport.objects.count(), 1)

    def test_message_from_another_room_cannot_be_reported_through_this_room(self):
        other_chat = self.make_chat(self.alice, self.ta)
        url = reverse(
            "courses:report_private_message",
            args=[self.course.id, other_chat.id, self.message.id],
        )
        self.client.force_login(self.alice)
        self.assertEqual(self.client.post(url, {"reason": "spam"}).status_code, 404)


class PrivateChatWebsocketTests(TransactionTestCase):
    async def test_participants_receive_messages_and_outsiders_are_rejected(self):
        course_id, chat_id, alice, bob, intruder = await self.create_chat_data()
        path = f"/ws/courses/{course_id}/chats/{chat_id}/"
        url_route = {"kwargs": {"course_id": course_id, "chat_id": chat_id}}

        first = WebsocketCommunicator(PrivateChatConsumer.as_asgi(), path)
        second = WebsocketCommunicator(PrivateChatConsumer.as_asgi(), path)
        stranger = WebsocketCommunicator(PrivateChatConsumer.as_asgi(), path)
        first.scope.update(user=alice, url_route=url_route)
        second.scope.update(user=bob, url_route=url_route)
        stranger.scope.update(user=intruder, url_route=url_route)
        self.assertTrue((await first.connect())[0])
        self.assertTrue((await second.connect())[0])
        connected, code = await stranger.connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4403)
        for communicator in (first, second):
            state = await communicator.receive_json_from()
            self.assertEqual(state["type"], "block.state")
            self.assertTrue(state["can_send"])

        await first.send_json_to({"type": "message.send", "body": "Live private"})
        event1 = await first.receive_json_from()
        event2 = await second.receive_json_from()
        self.assertEqual(event1["type"], "message.new")
        self.assertEqual(event2["message"], event1["message"])
        self.assertEqual(event1["message"]["body"], "Live private")

        await first.send_json_to({"type": "bad"})
        self.assertEqual((await first.receive_json_from())["type"], "error")

        await sync_to_async(UserBlock.objects.create)(blocker=bob, blocked=alice)
        await first.send_json_to({"type": "message.send", "body": "blocked?"})
        error = await first.receive_json_from()
        self.assertEqual(error["type"], "error")
        self.assertIn("บล็อก", error["message"])
        self.assertEqual(await sync_to_async(PrivateChatMessage.objects.count)(), 1)

        await first.disconnect()
        await second.disconnect()

    @staticmethod
    @sync_to_async
    def create_chat_data():
        course = Course.objects.create(code="WS201", name="Private sockets")
        alice = make_user("ws-alice@example.com")
        bob = make_user("ws-bob@example.com")
        intruder = make_user("ws-intruder@example.com")
        for user in (alice, bob, intruder):
            Enrollment.objects.create(user=user, course=course, role=Enrollment.Role.STUDENT)
        chat, _ = get_or_create_private_chat(course=course, user=alice, other=bob)
        return course.id, chat.id, alice, bob, intruder


class HistoryPaginationTests(PrivateChatTestBase):
    TOTAL = PRIVATE_CHAT_PAGE_SIZE * 2 + 30

    def setUp(self):
        self.chat = self.make_chat()
        PrivateChatMessage.objects.bulk_create(
            PrivateChatMessage(
                chat=self.chat,
                sender=self.alice if i % 2 else self.bob,
                body=f"msg {i}",
            )
            for i in range(self.TOTAL)
        )
        # Many rows share one timestamp so ordering must fall back to the id.
        PrivateChatMessage.objects.filter(chat=self.chat).update(created_at=timezone.now())
        self.all_ids = list(
            PrivateChatMessage.objects.filter(chat=self.chat)
            .order_by("created_at", "id")
            .values_list("id", flat=True)
        )
        self.history_url = reverse(
            "courses:private_chat_history", args=[self.course.id, self.chat.id]
        )

    def history(self, before, user=None):
        self.client.force_login(user or self.alice)
        return self.client.get(self.history_url, {"before": before})

    def test_first_page_shows_latest_messages_in_order(self):
        self.client.force_login(self.alice)
        response = self.client.get(self.chat_url(self.chat))
        page_ids = [message.id for message in response.context["chat_messages"]]
        self.assertEqual(page_ids, self.all_ids[-PRIVATE_CHAT_PAGE_SIZE:])
        self.assertTrue(response.context["has_older_messages"])
        self.assertContains(response, "โหลดข้อความเก่า")

    def test_load_older_pages_in_order_without_duplicates(self):
        self.client.force_login(self.alice)
        first = self.client.get(self.chat_url(self.chat))
        loaded = [message.id for message in first.context["chat_messages"]]
        pages = 0
        has_more = True
        while has_more:
            data = self.history(loaded[0]).json()
            ids = [message["id"] for message in data["messages"]]
            self.assertLessEqual(len(ids), PRIVATE_CHAT_PAGE_SIZE)
            self.assertEqual(ids, sorted(ids, key=self.all_ids.index))
            loaded = ids + loaded
            has_more = data["has_more"]
            pages += 1
        self.assertEqual(pages, 2)
        self.assertEqual(loaded, self.all_ids)
        self.assertEqual(len(set(loaded)), len(loaded))

    def test_history_marks_messages_already_reported(self):
        target = PrivateChatMessage.objects.get(pk=self.all_ids[0])
        if target.sender == self.alice:
            target = PrivateChatMessage.objects.get(pk=self.all_ids[1])
        report_message(message=target, reporter=self.alice, reason="spam")
        data = self.history(self.all_ids[2]).json()
        flags = {message["id"]: message["reported"] for message in data["messages"]}
        self.assertTrue(flags[target.id])
        self.assertEqual(sum(flags.values()), 1)

    def test_new_message_during_history_load_is_not_duplicated_or_misordered(self):
        self.client.force_login(self.alice)
        first = self.client.get(self.chat_url(self.chat))
        oldest_loaded = first.context["chat_messages"][0].id
        newest_loaded = first.context["chat_messages"][-1].id
        # A message arrives over WebSocket while the user is loading history.
        new_message = post_private_message(chat=self.chat, sender=self.bob, body="ใหม่ล่าสุด")

        ids = [message["id"] for message in self.history(oldest_loaded).json()["messages"]]
        self.assertNotIn(new_message.id, ids)
        self.assertNotIn(newest_loaded, ids)
        oldest_index = self.all_ids.index(oldest_loaded)
        self.assertTrue(all(self.all_ids.index(i) < oldest_index for i in ids))

    def test_last_page_reports_no_more_history(self):
        data = self.history(self.all_ids[5]).json()
        self.assertEqual([message["id"] for message in data["messages"]], self.all_ids[:5])
        self.assertFalse(data["has_more"])

    def test_short_chat_shows_no_older_messages_state(self):
        chat = self.make_chat(self.alice, self.ta)
        post_private_message(chat=chat, sender=self.ta, body="hello")
        self.client.force_login(self.alice)
        response = self.client.get(self.chat_url(chat))
        self.assertFalse(response.context["has_older_messages"])
        self.assertContains(response, "ไม่มีข้อความเก่ากว่านี้แล้ว")

    def test_invalid_or_foreign_cursor_is_rejected(self):
        self.assertEqual(self.history("abc").status_code, 400)
        self.assertEqual(self.history("").status_code, 400)
        other_chat = self.make_chat(self.alice, self.ta)
        foreign = post_private_message(chat=other_chat, sender=self.ta, body="other room")
        response = self.history(foreign.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_non_participant_cannot_load_history(self):
        for intruder in (self.ta, self.outsider, self.teacher):
            response = self.history(self.all_ids[-1], user=intruder)
            self.assertEqual(response.status_code, 404)

    def test_participant_without_course_access_cannot_load_history(self):
        Enrollment.objects.filter(user=self.bob, course=self.course).delete()
        self.assertEqual(self.history(self.all_ids[-1]).status_code, 404)

    def test_history_through_another_course_url_is_rejected(self):
        self.client.force_login(self.alice)
        url = reverse("courses:private_chat_history", args=[self.other_course.id, self.chat.id])
        self.assertEqual(self.client.get(url, {"before": self.all_ids[-1]}).status_code, 404)

    def test_anonymous_user_cannot_load_history(self):
        response = self.client.get(self.history_url, {"before": self.all_ids[-1]})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_history_endpoint_is_read_only(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.post(self.history_url).status_code, 405)


class BlockStateWebsocketTests(TransactionTestCase):
    async def test_block_state_is_pushed_to_both_sides_and_follows_database(self):
        course_id, chat_id, alice, bob = await self.create_chat_data()
        alice_ws = await self.connect(course_id, chat_id, alice)
        bob_ws = await self.connect(course_id, chat_id, bob)

        # Alice blocks: both open pages are told they can no longer send.
        await self.post_as(alice, "courses:block_private_chat_user", course_id, chat_id)
        alice_state = await alice_ws.receive_json_from()
        bob_state = await bob_ws.receive_json_from()
        self.assertEqual(alice_state["type"], "block.state")
        self.assertEqual((alice_state["can_send"], alice_state["blocked_by_me"]), (False, True))
        self.assertEqual((bob_state["can_send"], bob_state["blocked_by_other"]), (False, True))

        # Neither side can send, even with a hand-crafted WebSocket event.
        for communicator in (alice_ws, bob_ws):
            await communicator.send_json_to({"type": "message.send", "body": "blocked?"})
            self.assertEqual((await communicator.receive_json_from())["type"], "error")

        # Bob also blocks, then Alice unblocks: Bob's block is still there.
        await self.post_as(bob, "courses:block_private_chat_user", course_id, chat_id)
        await alice_ws.receive_json_from()
        await bob_ws.receive_json_from()
        await self.post_as(alice, "courses:unblock_private_chat_user", course_id, chat_id)
        alice_state = await alice_ws.receive_json_from()
        bob_state = await bob_ws.receive_json_from()
        self.assertFalse(alice_state["can_send"])
        self.assertTrue(alice_state["blocked_by_other"])
        self.assertFalse(bob_state["can_send"])
        self.assertTrue(bob_state["blocked_by_me"])
        await alice_ws.send_json_to({"type": "message.send", "body": "still blocked"})
        self.assertEqual((await alice_ws.receive_json_from())["type"], "error")

        # Bob unblocks too: both may send again without reconnecting.
        await self.post_as(bob, "courses:unblock_private_chat_user", course_id, chat_id)
        for communicator in (alice_ws, bob_ws):
            state = await communicator.receive_json_from()
            self.assertTrue(state["can_send"])
        await bob_ws.send_json_to({"type": "message.send", "body": "back again"})
        for communicator in (alice_ws, bob_ws):
            event = await communicator.receive_json_from()
            self.assertEqual(event["type"], "message.new")
            self.assertEqual(event["message"]["body"], "back again")
        self.assertEqual(await sync_to_async(PrivateChatMessage.objects.count)(), 1)

        await alice_ws.disconnect()
        await bob_ws.disconnect()

    async def test_reconnect_receives_current_block_state(self):
        course_id, chat_id, alice, bob = await self.create_chat_data()
        bob_ws = await self.connect(course_id, chat_id, bob)
        await bob_ws.disconnect()
        # The block happens while Bob is offline, so he misses the broadcast.
        await sync_to_async(UserBlock.objects.create)(blocker=alice, blocked=bob)

        bob_ws = await self.connect(course_id, chat_id, bob, expect_can_send=False)
        await bob_ws.disconnect()

    async def connect(self, course_id, chat_id, user, expect_can_send=True):
        communicator = WebsocketCommunicator(
            PrivateChatConsumer.as_asgi(), f"/ws/courses/{course_id}/chats/{chat_id}/"
        )
        communicator.scope.update(
            user=user, url_route={"kwargs": {"course_id": course_id, "chat_id": chat_id}}
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        state = await communicator.receive_json_from()
        self.assertEqual(state["type"], "block.state")
        self.assertEqual(state["can_send"], expect_can_send)
        return communicator

    @staticmethod
    @sync_to_async
    def post_as(user, url_name, course_id, chat_id):
        client = Client()
        client.force_login(user)
        response = client.post(reverse(url_name, args=[course_id, chat_id]))
        assert response.status_code == 302, response.status_code

    @staticmethod
    @sync_to_async
    def create_chat_data():
        course = Course.objects.create(code="WS202", name="Block state")
        alice = make_user("bs-alice@example.com")
        bob = make_user("bs-bob@example.com")
        for user in (alice, bob):
            Enrollment.objects.create(user=user, course=course, role=Enrollment.Role.STUDENT)
        chat, _ = get_or_create_private_chat(course=course, user=alice, other=bob)
        return course.id, chat.id, alice, bob

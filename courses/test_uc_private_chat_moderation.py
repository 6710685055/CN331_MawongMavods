from datetime import timedelta
from unittest.mock import patch

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from courses.consumers import PrivateChatConsumer
from notifications.models import Notification

from .group_services import create_team, post_chat_message
from .models import (
    Course,
    Enrollment,
    PrivateChatIncident,
    PrivateChatMessage,
    PrivateChatModerationLog,
    PrivateChatSuspension,
    PrivateMessageReport,
    TeamChat,
    UserBlock,
)
from .private_chat_moderation import SUSPENSION_DURATION, decide_report, lift_suspension
from .private_chat_services import (
    PrivateChatError,
    get_or_create_private_chat,
    post_private_message,
    report_message,
)
from .test_uc_private_chat import PrivateChatTestBase, make_user

CONFIRMED = PrivateMessageReport.Status.CONFIRMED
REJECTED = PrivateMessageReport.Status.REJECTED


def make_reviewer(email):
    reviewer = make_user(email)
    reviewer.is_staff = True
    reviewer.save()
    reviewer.user_permissions.add(Permission.objects.get(codename="review_privatemessagereport"))
    return reviewer


class ModerationTestBase(PrivateChatTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.reviewer = make_reviewer("reviewer@example.com")
        cls.staff_without_permission = make_user("staff@example.com")
        cls.staff_without_permission.is_staff = True
        cls.staff_without_permission.save()

    def setUp(self):
        self.chat = self.make_chat()

    def offending_report(self, body="ข้อความไม่สุภาพ", sender=None, reporter=None):
        """`sender` (default Alice) sends a message that `reporter` (default Bob) reports."""
        sender = sender or self.alice
        reporter = reporter or self.bob
        message = post_private_message(chat=self.chat, sender=sender, body=body)
        return report_message(message=message, reporter=reporter, reason="harassment")

    def confirm(self, report, note="ละเมิดกติกา"):
        return decide_report(report_id=report.pk, reviewer=self.reviewer, decision=CONFIRMED, note=note)

    def reject(self, report, note="ไม่พบการละเมิด"):
        return decide_report(report_id=report.pk, reviewer=self.reviewer, decision=REJECTED, note=note)

    def report_change_url(self, report):
        return reverse("admin:courses_privatemessagereport_change", args=[report.pk])

    def notifications(self, user, notification_type):
        return Notification.objects.filter(recipient=user, notification_type=notification_type)

    def send_json(self, user, body="hello"):
        self.client.force_login(user)
        return self.client.post(
            self.chat_url(self.chat), {"body": body}, HTTP_ACCEPT="application/json"
        )


class ReportQueueTests(ModerationTestBase):
    def test_new_report_starts_pending_with_evidence_and_context(self):
        for i in range(5):
            post_private_message(chat=self.chat, sender=self.bob, body=f"ก่อนหน้า {i}")
        message = post_private_message(chat=self.chat, sender=self.alice, body="ข้อความที่ถูกรายงาน")
        post_private_message(chat=self.chat, sender=self.bob, body="หลังจากนั้น")

        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("courses:report_private_message", args=[self.course.id, self.chat.id, message.id]),
            {"reason": "harassment", "details": "หยาบคาย"},
            follow=True,
        )

        self.assertContains(response, "รอตรวจสอบ")
        report = PrivateMessageReport.objects.get()
        self.assertEqual(report.status, PrivateMessageReport.Status.PENDING)
        self.assertEqual(report.get_status_display(), "รอตรวจสอบ")
        self.assertEqual(
            (report.reporter, report.reported_user, report.course, report.reason),
            (self.bob, self.alice, self.course, "harassment"),
        )
        self.assertEqual(report.message_body, "ข้อความที่ถูกรายงาน")
        self.assertIsNotNone(report.message_sent_at)
        self.assertIsNotNone(report.created_at)
        # Only three messages on each side are copied, not the whole room.
        bodies = [item["body"] for item in report.context_snapshot]
        self.assertEqual(bodies, ["ก่อนหน้า 2", "ก่อนหน้า 3", "ก่อนหน้า 4", "ข้อความที่ถูกรายงาน", "หลังจากนั้น"])
        self.assertEqual([item["reported"] for item in report.context_snapshot].count(True), 1)

    def test_pending_report_appears_in_admin_queue_with_context(self):
        report = self.offending_report("<b>หลักฐาน</b>")
        self.client.force_login(self.reviewer)

        queue = self.client.get(reverse("admin:courses_privatemessagereport_changelist"))
        self.assertEqual(queue.status_code, 200)
        self.assertContains(queue, "รอตรวจสอบ")

        page = self.client.get(self.report_change_url(report))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "บริบทข้อความใกล้เคียง")
        self.assertContains(page, "ยืนยันรายงาน")
        self.assertContains(page, "&lt;b&gt;หลักฐาน&lt;/b&gt;")
        self.assertNotContains(page, "<b>หลักฐาน</b>")

    def test_regular_users_and_staff_without_permission_cannot_read_queue(self):
        report = self.offending_report()
        urls = [
            reverse("admin:courses_privatemessagereport_changelist"),
            self.report_change_url(report),
        ]
        for url in urls:
            self.client.force_login(self.bob)
            self.assertRedirects(self.client.get(url), f"{reverse('admin:login')}?next={url}")
            self.client.force_login(self.staff_without_permission)
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_context_snapshot_is_not_shown_to_chat_participants(self):
        post_private_message(chat=self.chat, sender=self.bob, body="บริบทลับ")
        report = self.offending_report()
        self.assertTrue(any(item["body"] == "บริบทลับ" for item in report.context_snapshot))
        for user in (self.alice, self.bob):
            self.client.force_login(user)
            page = self.client.get(self.chat_url(self.chat))
            self.assertNotIn("context_snapshot", page.content.decode())
            self.assertNotContains(page, "บริบทข้อความใกล้เคียง")

    def test_users_without_permission_cannot_decide_reports(self):
        report = self.offending_report()
        for user in (self.alice, self.bob, self.staff_without_permission, self.teacher):
            with self.assertRaises(PermissionDenied):
                decide_report(report_id=report.pk, reviewer=user, decision=CONFIRMED)

        self.client.force_login(self.staff_without_permission)
        response = self.client.post(
            self.report_change_url(report), {"decision": CONFIRMED, "review_note": "x"}
        )
        self.assertEqual(response.status_code, 403)
        report.refresh_from_db()
        self.assertEqual(report.status, PrivateMessageReport.Status.PENDING)
        self.assertFalse(PrivateChatIncident.objects.exists())


class ReviewDecisionTests(ModerationTestBase):
    def test_admin_confirm_records_reviewer_time_and_note(self):
        report = self.offending_report()
        self.client.force_login(self.reviewer)

        before = timezone.now()
        response = self.client.post(
            self.report_change_url(report),
            {"decision": CONFIRMED, "review_note": "ข้อความคุกคาม", "_save": "Save"},
        )

        self.assertRedirects(response, reverse("admin:courses_privatemessagereport_changelist"))
        report.refresh_from_db()
        self.assertEqual(report.status, CONFIRMED)
        self.assertEqual(report.reviewed_by, self.reviewer)
        self.assertGreaterEqual(report.reviewed_at, before)
        self.assertEqual(report.review_note, "ข้อความคุกคาม")
        self.assertIsNotNone(report.incident)
        log = PrivateChatModerationLog.objects.get(action=PrivateChatModerationLog.Action.REPORT_CONFIRMED)
        self.assertEqual((log.actor, log.target_user, log.note), (self.reviewer, self.alice, "ข้อความคุกคาม"))

    def test_admin_reject_records_reviewer_time_and_note(self):
        report = self.offending_report()
        self.client.force_login(self.reviewer)
        self.client.post(self.report_change_url(report), {"decision": REJECTED, "review_note": "ล้อเล่นกัน"})

        report.refresh_from_db()
        self.assertEqual(
            (report.status, report.reviewed_by, report.review_note),
            (REJECTED, self.reviewer, "ล้อเล่นกัน"),
        )
        self.assertIsNotNone(report.reviewed_at)
        self.assertTrue(
            PrivateChatModerationLog.objects.filter(
                action=PrivateChatModerationLog.Action.REPORT_REJECTED, report=report
            ).exists()
        )

    def test_admin_form_requires_a_decision(self):
        report = self.offending_report()
        self.client.force_login(self.reviewer)
        response = self.client.post(self.report_change_url(report), {"review_note": "ยังไม่ตัดสิน"})
        self.assertEqual(response.status_code, 200)
        report.refresh_from_db()
        self.assertEqual(report.status, PrivateMessageReport.Status.PENDING)

    def test_confirmed_message_is_hidden_from_both_sides_but_evidence_is_kept(self):
        post_private_message(chat=self.chat, sender=self.bob, body="ข้อความปกติ")
        report = self.offending_report("ข้อความต้องห้าม")
        self.confirm(report)

        for user in (self.alice, self.bob):
            self.client.force_login(user)
            page = self.client.get(self.chat_url(self.chat))
            self.assertNotContains(page, "ข้อความต้องห้าม")
            self.assertContains(page, "ข้อความปกติ")
            chat_list = self.client.get(reverse("courses:private_chats", args=[self.course.id]))
            self.assertNotContains(chat_list, "ข้อความต้องห้าม")

        message = PrivateChatMessage.objects.get(body="ข้อความต้องห้าม")
        self.assertIsNotNone(message.hidden_at)
        report.refresh_from_db()
        self.assertEqual(report.message_body, "ข้อความต้องห้าม")
        self.assertEqual(report.incident.message_body, "ข้อความต้องห้าม")

        # Hidden messages are not served by the history endpoint either.
        newer = post_private_message(chat=self.chat, sender=self.bob, body="ใหม่")
        self.client.force_login(self.bob)
        data = self.client.get(
            reverse("courses:private_chat_history", args=[self.course.id, self.chat.id]),
            {"before": newer.id},
        ).json()
        self.assertEqual([item["body"] for item in data["messages"]], ["ข้อความปกติ"])

    def test_hidden_message_cannot_be_reported_again(self):
        report = self.offending_report()
        self.confirm(report)
        message = PrivateChatMessage.objects.get(pk=report.message_id)
        with self.assertRaisesMessage(PrivateChatError, "ถูกซ่อน"):
            report_message(message=message, reporter=self.bob, reason="spam")

    def test_reject_keeps_message_visible_and_issues_no_warning(self):
        report = self.offending_report("ข้อความที่ไม่ผิด")
        self.reject(report)

        self.client.force_login(self.bob)
        self.assertContains(self.client.get(self.chat_url(self.chat)), "ข้อความที่ไม่ผิด")
        self.assertIsNone(PrivateChatMessage.objects.get(body="ข้อความที่ไม่ผิด").hidden_at)
        self.assertFalse(PrivateChatIncident.objects.exists())
        self.assertFalse(self.notifications(self.alice, Notification.Type.PRIVATE_CHAT_WARNING).exists())
        result = self.notifications(self.bob, Notification.Type.PRIVATE_REPORT_RESULT).get()
        self.assertIn("ไม่พบการละเมิด", result.message)

    def test_decided_report_cannot_be_decided_again(self):
        report = self.offending_report()
        self.reject(report)
        with self.assertRaisesMessage(PrivateChatError, "พิจารณาไปแล้ว"):
            self.confirm(report)
        report.refresh_from_db()
        self.assertEqual(report.status, REJECTED)
        self.assertFalse(PrivateChatIncident.objects.exists())

    def test_double_submit_in_admin_does_not_add_a_second_warning(self):
        report = self.offending_report()
        self.client.force_login(self.reviewer)
        data = {"decision": CONFIRMED, "review_note": "ซ้ำ"}
        self.client.post(self.report_change_url(report), data)
        second = self.client.post(self.report_change_url(report), data)

        self.assertEqual(second.status_code, 403)
        self.assertEqual(PrivateChatIncident.objects.count(), 1)
        self.assertEqual(self.notifications(self.alice, Notification.Type.PRIVATE_CHAT_WARNING).count(), 1)


class PenaltyLadderTests(ModerationTestBase):
    def confirm_incidents(self, count):
        # Reports are filed first: once suspended, the sender cannot post more messages.
        reports = [self.offending_report(f"ผิดครั้งที่ {i}") for i in range(1, count + 1)]
        return [self.confirm(report) for report in reports]

    def test_first_three_incidents_warn_and_fourth_suspends_for_24_hours(self):
        reports = self.confirm_incidents(3)

        incidents = [report.incident for report in reports]
        self.assertEqual([incident.sequence for incident in incidents], [1, 2, 3])
        self.assertTrue(all(i.action == PrivateChatIncident.Action.WARNING for i in incidents))
        warnings = self.notifications(self.alice, Notification.Type.PRIVATE_CHAT_WARNING)
        self.assertEqual(warnings.count(), 3)
        self.assertFalse(PrivateChatSuspension.objects.exists())
        self.assertEqual(self.send_json(self.alice).status_code, 201)

        fourth = self.confirm(self.offending_report("ผิดครั้งที่ 4")).incident
        self.assertEqual((fourth.sequence, fourth.action), (4, PrivateChatIncident.Action.SUSPENSION))
        suspension = fourth.suspension
        self.assertEqual((suspension.user, suspension.counterpart), (self.alice, self.bob))
        self.assertEqual(suspension.starts_at, fourth.confirmed_at)
        self.assertEqual(suspension.ends_at - suspension.starts_at, timedelta(hours=24))
        self.assertEqual(SUSPENSION_DURATION, timedelta(hours=24))
        self.assertEqual(self.notifications(self.alice, Notification.Type.PRIVATE_CHAT_SUSPENDED).count(), 1)
        self.assertEqual(
            PrivateChatModerationLog.objects.filter(action=PrivateChatModerationLog.Action.SUSPENDED).count(), 1
        )

    def test_fifth_incident_suspends_again_and_is_logged(self):
        self.confirm_incidents(5)
        actions = list(
            PrivateChatIncident.objects.order_by("sequence").values_list("action", flat=True)
        )
        self.assertEqual(actions, ["warning"] * 3 + ["suspension"] * 2)
        self.assertEqual(PrivateChatSuspension.objects.count(), 2)
        self.assertEqual(
            PrivateChatModerationLog.objects.filter(action=PrivateChatModerationLog.Action.SUSPENDED).count(), 2
        )

    def test_pending_and_rejected_reports_are_not_counted(self):
        for i in range(3):
            self.reject(self.offending_report(f"ไม่ผิด {i}"))
        self.offending_report("ยังรอตรวจ")
        incident = self.confirm(self.offending_report("ผิดจริง")).incident
        self.assertEqual((incident.sequence, incident.action), (1, PrivateChatIncident.Action.WARNING))

    def test_several_reports_of_one_message_count_as_one_incident(self):
        first = self.offending_report()
        # A second reporter of the same message (e.g. filed before the first was decided).
        second = PrivateMessageReport.objects.create(
            message=first.message,
            reporter=self.ta,
            reported_user=self.alice,
            course=self.course,
            reason="spam",
            message_body=first.message_body,
            message_sent_at=first.message_sent_at,
        )
        self.confirm(first)
        self.confirm(second)

        self.assertEqual(PrivateChatIncident.objects.count(), 1)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.incident, second.incident)
        self.assertEqual(self.notifications(self.alice, Notification.Type.PRIVATE_CHAT_WARNING).count(), 1)
        # Each reporter still hears the outcome of their own report.
        for reporter in (self.bob, self.ta):
            self.assertEqual(self.notifications(reporter, Notification.Type.PRIVATE_REPORT_RESULT).count(), 1)

    def test_notifications_go_to_the_right_people_without_naming_the_reporter(self):
        reports = [self.offending_report(f"ผิด {i}") for i in range(4)]
        for report in reports:
            self.confirm(report)

        to_reporter = self.notifications(self.bob, Notification.Type.PRIVATE_REPORT_RESULT)
        self.assertEqual(to_reporter.count(), 4)
        self.assertTrue(all("ยืนยัน" in n.message for n in to_reporter))
        offender_notes = Notification.objects.filter(
            recipient=self.alice,
            notification_type__in=[
                Notification.Type.PRIVATE_CHAT_WARNING,
                Notification.Type.PRIVATE_CHAT_SUSPENDED,
            ],
        )
        self.assertEqual(offender_notes.count(), 4)
        for note in offender_notes:
            self.assertNotIn(self.bob.full_name, note.message)
            self.assertNotIn(self.bob.email, note.message)
            self.assertIsNone(note.actor)
            self.assertEqual(note.target_url, "")
        # Nobody else is told about the decision.
        self.assertFalse(
            Notification.objects.filter(
                notification_type__startswith="private_", recipient__in=[self.ta, self.reviewer]
            ).exists()
        )


class SuspensionEnforcementTests(ModerationTestBase):
    def setUp(self):
        super().setUp()
        for i in range(4):
            self.confirm(self.offending_report(f"ผิด {i}"))
        self.suspension = PrivateChatSuspension.objects.get()

    def test_suspended_sender_cannot_post_over_http(self):
        response = self.send_json(self.alice, "ขอส่งหน่อย")
        self.assertEqual(response.status_code, 400)
        self.assertIn("ระงับ", response.json()["error"])
        self.client.force_login(self.alice)
        self.client.post(self.chat_url(self.chat), {"body": "ฟอร์มปกติ"})
        self.assertFalse(PrivateChatMessage.objects.filter(body__in=["ขอส่งหน่อย", "ฟอร์มปกติ"]).exists())

    def test_chat_page_shows_suspension_and_history_stays_readable(self):
        post_private_message(chat=self.chat, sender=self.bob, body="อ่านได้")
        self.client.force_login(self.alice)
        page = self.client.get(self.chat_url(self.chat))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "อ่านได้")
        self.assertContains(page, "คุณถูกระงับการส่งข้อความในแชทนี้จนถึง")
        self.assertFalse(page.context["can_send"])

    def test_suspension_only_covers_the_reported_pair(self):
        # Bob (the reporter) can still message Alice.
        self.assertEqual(self.send_json(self.bob, "ถึงอลิซ").status_code, 201)
        # Alice can still message someone else.
        other_chat, _ = get_or_create_private_chat(course=self.course, user=self.alice, other=self.ta)
        post_private_message(chat=other_chat, sender=self.alice, body="ถึง TA")
        self.assertFalse(UserBlock.objects.exists())

    def test_suspension_does_not_affect_uc9_group_chat(self):
        team = create_team(user=self.alice, course=self.course, name="ทีม A")
        chat, _ = TeamChat.objects.get_or_create(team=team)
        message = post_chat_message(chat=chat, sender=self.alice, body="ข้อความกลุ่ม")
        self.assertEqual(message.body, "ข้อความกลุ่ม")

    def test_sending_works_again_once_ends_at_has_passed(self):
        later = self.suspension.ends_at + timedelta(seconds=1)
        with patch("django.utils.timezone.now", return_value=later):
            self.assertEqual(self.send_json(self.alice, "ครบเวลาแล้ว").status_code, 201)
            self.client.force_login(self.alice)
            self.assertTrue(self.client.get(self.chat_url(self.chat)).context["can_send"])

    def test_admin_can_lift_suspension_early_with_reason(self):
        self.client.force_login(self.reviewer)
        url = reverse("admin:courses_privatechatsuspension_change", args=[self.suspension.pk])
        self.assertEqual(self.client.get(url).status_code, 200)

        no_reason = self.client.post(url, {"lift_reason": "  "})
        self.assertEqual(no_reason.status_code, 200)
        self.suspension.refresh_from_db()
        self.assertIsNone(self.suspension.lifted_at)

        self.client.post(url, {"lift_reason": "ตรวจสอบแล้วเป็นความเข้าใจผิด"})
        self.suspension.refresh_from_db()
        self.assertEqual(self.suspension.lifted_by, self.reviewer)
        self.assertIsNotNone(self.suspension.lifted_at)
        self.assertEqual(self.suspension.lift_reason, "ตรวจสอบแล้วเป็นความเข้าใจผิด")
        self.assertEqual(self.send_json(self.alice, "กลับมาแล้ว").status_code, 201)
        self.assertEqual(
            self.notifications(self.alice, Notification.Type.PRIVATE_CHAT_UNSUSPENDED).count(), 1
        )
        log = PrivateChatModerationLog.objects.get(action=PrivateChatModerationLog.Action.SUSPENSION_LIFTED)
        self.assertEqual((log.actor, log.suspension, log.target_user), (self.reviewer, self.suspension, self.alice))

        # Lifting twice is refused and does not notify again.
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.post(url, {"lift_reason": "อีกครั้ง"}).status_code, 403)
        with self.assertRaisesMessage(PrivateChatError, "ถูกยกเลิกไปแล้ว"):
            lift_suspension(suspension_id=self.suspension.pk, actor=self.reviewer, reason="อีกครั้ง")
        self.assertEqual(
            self.notifications(self.alice, Notification.Type.PRIVATE_CHAT_UNSUSPENDED).count(), 1
        )

    def test_only_reviewers_can_lift_suspension(self):
        for user in (self.alice, self.bob, self.staff_without_permission):
            with self.assertRaises(PermissionDenied):
                lift_suspension(suspension_id=self.suspension.pk, actor=user, reason="ขอยกเลิก")
        self.client.force_login(self.staff_without_permission)
        url = reverse("admin:courses_privatechatsuspension_change", args=[self.suspension.pk])
        self.assertEqual(self.client.post(url, {"lift_reason": "ขอยกเลิก"}).status_code, 403)
        self.suspension.refresh_from_db()
        self.assertIsNone(self.suspension.lifted_at)

    def test_audit_records_are_read_only_in_admin(self):
        self.client.force_login(self.reviewer)
        for name in ("privatechatincident", "privatechatmoderationlog"):
            self.assertEqual(self.client.get(reverse(f"admin:courses_{name}_changelist")).status_code, 200)
        incident = PrivateChatIncident.objects.first()
        delete_url = reverse("admin:courses_privatechatincident_delete", args=[incident.pk])
        self.assertEqual(self.client.post(delete_url, {"post": "yes"}).status_code, 403)
        self.assertEqual(PrivateChatIncident.objects.count(), 4)


class ModerationWebsocketTests(TransactionTestCase):
    async def test_confirm_hides_message_and_suspension_blocks_websocket_send(self):
        course_id, chat_id, alice, bob, reviewer = await self.create_data()
        alice_ws = await self.connect(course_id, chat_id, alice)
        bob_ws = await self.connect(course_id, chat_id, bob)

        message_ids = []
        for i in range(4):
            await alice_ws.send_json_to({"type": "message.send", "body": f"ผิด {i}"})
            for communicator in (alice_ws, bob_ws):
                event = await communicator.receive_json_from()
                self.assertEqual(event["type"], "message.new")
            message_ids.append(event["message"]["id"])

        for index, message_id in enumerate(message_ids):
            await self.report_and_confirm(message_id, bob, reviewer)
            for communicator in (alice_ws, bob_ws):
                event = await communicator.receive_json_from()
                self.assertEqual(event, {"type": "message.hidden", "message_id": message_id})

        # The fourth confirmation also pushes the new send state to both pages.
        alice_state = await alice_ws.receive_json_from()
        bob_state = await bob_ws.receive_json_from()
        self.assertEqual(alice_state["type"], "block.state")
        self.assertFalse(alice_state["can_send"])
        self.assertIsNotNone(alice_state["suspended_until"])
        self.assertTrue(bob_state["can_send"])

        # A hand-crafted send from the suspended user is refused by the server.
        await alice_ws.send_json_to({"type": "message.send", "body": "ส่งได้ไหม"})
        error = await alice_ws.receive_json_from()
        self.assertEqual(error["type"], "error")
        self.assertIn("ระงับ", error["message"])
        self.assertTrue(await bob_ws.receive_nothing())

        # After an admin lifts it, both pages are told and Alice can send again.
        await sync_to_async(self.lift)(reviewer)
        self.assertTrue((await alice_ws.receive_json_from())["can_send"])
        await bob_ws.receive_json_from()
        await alice_ws.send_json_to({"type": "message.send", "body": "กลับมาแล้ว"})
        self.assertEqual((await bob_ws.receive_json_from())["message"]["body"], "กลับมาแล้ว")

        await alice_ws.disconnect()
        await bob_ws.disconnect()

    async def connect(self, course_id, chat_id, user):
        communicator = WebsocketCommunicator(
            PrivateChatConsumer.as_asgi(), f"/ws/courses/{course_id}/chats/{chat_id}/"
        )
        communicator.scope.update(
            user=user, url_route={"kwargs": {"course_id": course_id, "chat_id": chat_id}}
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        self.assertEqual((await communicator.receive_json_from())["type"], "block.state")
        return communicator

    @staticmethod
    @sync_to_async
    def report_and_confirm(message_id, reporter, reviewer):
        message = PrivateChatMessage.objects.select_related("chat__course", "sender").get(pk=message_id)
        report = report_message(message=message, reporter=reporter, reason="harassment")
        decide_report(report_id=report.pk, reviewer=reviewer, decision=CONFIRMED)

    @staticmethod
    def lift(reviewer):
        suspension = PrivateChatSuspension.objects.get()
        lift_suspension(suspension_id=suspension.pk, actor=reviewer, reason="ยกเลิกเพื่อทดสอบ")

    @staticmethod
    @sync_to_async
    def create_data():
        course = Course.objects.create(code="MOD101", name="Moderation")
        alice = make_user("mod-alice@example.com")
        bob = make_user("mod-bob@example.com")
        for user in (alice, bob):
            Enrollment.objects.create(user=user, course=course, role=Enrollment.Role.STUDENT)
        reviewer = make_reviewer("mod-reviewer@example.com")
        chat, _ = get_or_create_private_chat(course=course, user=alice, other=bob)
        return course.id, chat.id, alice, bob, reviewer

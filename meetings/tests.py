from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO

from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from courses.group_services import leave_team
from courses.models import Course, Enrollment, Team, TeamMembership
from notifications.models import Notification

from .group_access import TeamAccess
from .models import Meeting
from .services import (
    create_meeting,
    get_group_access,
    reschedule_meeting,
    send_due_reminders,
)

PW = "Str0ng-pass-2026"


def make_user(email, **extra):
    return User.objects.create_user(
        email,
        PW,
        email_verified=True,
        role=User.Role.STUDENT,
        first_name=email.split("@")[0],
        **extra,
    )


def form_time(value):
    return timezone.localtime(value).strftime("%Y-%m-%dT%H:%M")


class MeetingTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.course = Course.objects.create(code="CN331", name="Software Engineering")
        cls.alice = make_user("alice@example.com")
        cls.bob = make_user("bob@example.com")
        cls.carol = make_user("carol@example.com")
        cls.outsider = make_user("outsider@example.com")
        for user in (cls.alice, cls.bob, cls.carol, cls.outsider):
            Enrollment.objects.create(
                user=user, course=cls.course, role=Enrollment.Role.STUDENT
            )
        cls.team = Team.objects.create(
            course=cls.course, name="ทีมแมว", created_by=cls.alice
        )
        for user in (cls.alice, cls.bob, cls.carol):
            TeamMembership.objects.create(team=cls.team, course=cls.course, user=user)
        cls.other_team = Team.objects.create(
            course=cls.course, name="ทีมหมา", created_by=cls.outsider
        )
        TeamMembership.objects.create(
            team=cls.other_team, course=cls.course, user=cls.outsider
        )

    def setUp(self):
        self.starts_at = (timezone.now() + timedelta(days=1)).replace(
            second=0, microsecond=0
        )

    def make_meeting(self, actor=None, starts_at=None, title="ทบทวน Sprint"):
        return create_meeting(
            group=self.team,
            actor=actor or self.alice,
            title=title,
            meeting_url="https://meet.example.com/abc",
            starts_at=starts_at or self.starts_at,
        )

    def group_url(self, team=None):
        return reverse("meetings:group", args=[(team or self.team).pk])

    def notifications(self, notification_type, user=None):
        queryset = Notification.objects.filter(notification_type=notification_type)
        return queryset.filter(recipient=user) if user else queryset


class TeamAdapterTests(MeetingTestBase):
    def test_team_adapter_is_the_default(self):
        self.assertIs(get_group_access(), TeamAccess)

    def test_members_are_active_team_members_only(self):
        self.bob.is_active = False
        self.bob.save()
        self.assertEqual(list(TeamAccess.members(self.team)), [self.alice, self.carol])
        self.assertFalse(TeamAccess.is_member(self.bob, self.team))
        self.assertFalse(TeamAccess.is_member(self.outsider, self.team))

    def test_django_group_is_never_treated_as_a_team(self):
        group = Group.objects.create(name="legacy")
        self.alice.groups.add(group)
        self.assertFalse(TeamAccess.is_member(self.alice, group))
        self.assertEqual(list(TeamAccess.members(group)), [])


class MeetingVisibilityTests(MeetingTestBase):
    def test_member_creates_meeting_and_teammate_sees_it(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("meetings:create", args=[self.team.pk]),
            {
                "title": "ประชุมเริ่มโปรเจกต์",
                "meeting_url": "https://meet.example.com/kickoff",
                "starts_at": form_time(self.starts_at),
            },
        )
        self.assertRedirects(response, self.group_url())
        meeting = Meeting.objects.get()
        self.assertEqual(meeting.group, self.team)

        self.client.force_login(self.bob)
        self.assertContains(self.client.get(self.group_url()), "ประชุมเริ่มโปรเจกต์")
        index = self.client.get(reverse("meetings:index"))
        self.assertContains(index, "ประชุมเริ่มโปรเจกต์")
        self.assertContains(index, str(self.team))

    def test_teammate_can_edit_and_reschedule(self):
        meeting = self.make_meeting(actor=self.alice)
        new_time = self.starts_at + timedelta(hours=3)
        self.client.force_login(self.bob)
        url = reverse("meetings:edit", args=[meeting.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(
            url,
            {
                "title": "ทบทวน Sprint (เลื่อน)",
                "meeting_url": meeting.meeting_url,
                "starts_at": form_time(new_time),
            },
        )
        self.assertRedirects(response, self.group_url())
        meeting.refresh_from_db()
        self.assertEqual(
            (meeting.title, meeting.starts_at), ("ทบทวน Sprint (เลื่อน)", new_time)
        )

    def test_non_member_is_refused_even_with_direct_urls(self):
        meeting = self.make_meeting()
        self.client.force_login(self.outsider)
        urls = [
            self.group_url(),
            reverse("meetings:create", args=[self.team.pk]),
            reverse("meetings:edit", args=[meeting.pk]),
        ]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403)
        post = self.client.post(
            reverse("meetings:create", args=[self.team.pk]),
            {
                "title": "แอบสร้าง",
                "meeting_url": "https://x.example.com",
                "starts_at": form_time(self.starts_at),
            },
        )
        self.assertEqual(post.status_code, 403)
        edit = self.client.post(
            reverse("meetings:edit", args=[meeting.pk]),
            {
                "title": "แอบแก้",
                "meeting_url": meeting.meeting_url,
                "starts_at": form_time(self.starts_at),
            },
        )
        self.assertEqual(edit.status_code, 403)
        self.assertEqual(Meeting.objects.count(), 1)
        meeting.refresh_from_db()
        self.assertEqual(meeting.title, "ทบทวน Sprint")
        self.assertNotContains(
            self.client.get(reverse("meetings:index")), "ทบทวน Sprint"
        )

    def test_unknown_team_and_anonymous_user_are_refused(self):
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.get(reverse("meetings:group", args=[9999])).status_code, 403
        )
        self.client.logout()
        response = self.client.get(self.group_url())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_member_who_leaves_no_longer_sees_meetings(self):
        meeting = self.make_meeting()
        leave_team(team_id=self.team.pk, user=self.bob)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(self.group_url()).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("meetings:edit", args=[meeting.pk])).status_code,
            403,
        )
        self.assertNotContains(
            self.client.get(reverse("meetings:index")), meeting.title
        )

    def assert_lost_access(self, user, meeting):
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.group_url()).status_code, 403)
        self.assertEqual(
            self.client.get(
                reverse("meetings:create", args=[self.team.pk])
            ).status_code,
            403,
        )
        edit = self.client.post(
            reverse("meetings:edit", args=[meeting.pk]),
            {
                "title": "แอบแก้",
                "meeting_url": meeting.meeting_url,
                "starts_at": form_time(meeting.starts_at),
            },
        )
        self.assertEqual(edit.status_code, 403)
        self.assertNotContains(
            self.client.get(reverse("meetings:index")), meeting.title
        )
        self.assertNotIn(user, TeamAccess.members(self.team))

    def test_student_removed_from_course_loses_team_meetings(self):
        meeting = self.make_meeting()
        Enrollment.objects.filter(user=self.bob, course=self.course).delete()
        # The team membership row is still there; the enrollment check alone removes access.
        self.assertTrue(
            TeamMembership.objects.filter(team=self.team, user=self.bob).exists()
        )
        self.assert_lost_access(self.bob, meeting)
        meeting.refresh_from_db()
        self.assertEqual(meeting.title, "ทบทวน Sprint")

    def test_student_whose_enrollment_is_no_longer_student_loses_team_meetings(self):
        meeting = self.make_meeting()
        Enrollment.objects.filter(user=self.bob, course=self.course).update(
            role=Enrollment.Role.STUDENT_PENDING
        )
        self.assert_lost_access(self.bob, meeting)

    def test_student_removed_from_course_gets_no_meeting_notifications(self):
        Enrollment.objects.filter(user=self.bob, course=self.course).delete()
        meeting = self.make_meeting(actor=self.alice)
        reschedule_meeting(
            meeting=meeting,
            actor=self.carol,
            title=meeting.title,
            meeting_url=meeting.meeting_url,
            starts_at=meeting.starts_at + timedelta(hours=1),
        )
        send_due_reminders(
            now=meeting.starts_at + timedelta(hours=1) - timedelta(minutes=5)
        )
        self.assertFalse(Notification.objects.filter(recipient=self.bob).exists())
        # Enrolled teammates are still notified as before.
        self.assertTrue(Notification.objects.filter(recipient=self.carol).exists())

    def test_enrollment_in_another_course_does_not_grant_access(self):
        meeting = self.make_meeting()
        other_course = Course.objects.create(code="CN332", name="Other")
        Enrollment.objects.filter(user=self.bob, course=self.course).delete()
        Enrollment.objects.create(
            user=self.bob, course=other_course, role=Enrollment.Role.STUDENT
        )
        self.assert_lost_access(self.bob, meeting)

    def test_team_dashboard_links_to_meetings_and_lists_upcoming(self):
        self.make_meeting(title="นัดคุยงาน")
        self.client.force_login(self.bob)
        response = self.client.get(reverse("courses:groups", args=[self.course.pk]))
        self.assertContains(response, self.group_url())
        self.assertContains(response, "นัดคุยงาน")

    def test_team_dashboard_shows_empty_state(self):
        self.client.force_login(self.bob)
        response = self.client.get(reverse("courses:groups", args=[self.course.pk]))
        self.assertContains(response, "ยังไม่มีนัดหมาย")


class LegacyGroupMeetingTests(MeetingTestBase):
    """Meetings still linked to a Django Group are left in place but never surface."""

    def setUp(self):
        super().setUp()
        # Same id as the team on purpose: matching by id alone would leak it.
        self.group = Group.objects.create(pk=self.team.pk, name="agile g")
        self.alice.groups.add(self.group)
        self.legacy = Meeting.objects.create(
            group_content_type=ContentType.objects.get_for_model(Group),
            group_object_id=self.group.pk,
            created_by=self.alice,
            title="นัดเก่าจาก Group",
            meeting_url="https://meet.example.com/old",
            starts_at=timezone.now() + timedelta(minutes=10),
        )

    def test_legacy_meeting_is_not_shown_in_any_team(self):
        for user in (self.alice, self.bob):
            self.client.force_login(user)
            self.assertNotContains(
                self.client.get(self.group_url()), "นัดเก่าจาก Group"
            )
            self.assertNotContains(
                self.client.get(reverse("meetings:index")), "นัดเก่าจาก Group"
            )
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.get(
                reverse("meetings:edit", args=[self.legacy.pk])
            ).status_code,
            403,
        )

    def test_reminder_command_skips_legacy_meeting_without_error(self):
        out = StringIO()
        call_command("send_meeting_reminders", stdout=out)
        self.assertIn("0", out.getvalue())
        self.assertFalse(Notification.objects.exists())
        self.legacy.refresh_from_db()
        self.assertIsNone(self.legacy.reminder_sent_at)

    def test_legacy_data_is_not_deleted_or_changed(self):
        self.client.force_login(self.alice)
        self.client.get(reverse("meetings:index"))
        send_due_reminders()
        self.legacy.refresh_from_db()
        self.assertEqual(self.legacy.group, self.group)
        self.assertTrue(Group.objects.filter(pk=self.group.pk).exists())


class MeetingNotificationTests(MeetingTestBase):
    def test_create_notifies_everyone_except_creator(self):
        self.make_meeting(actor=self.alice)
        created = self.notifications(Notification.Type.MEETING_CREATED)
        self.assertEqual(
            sorted(n.recipient_id for n in created),
            sorted([self.bob.pk, self.carol.pk]),
        )
        self.assertFalse(created.filter(recipient=self.outsider).exists())
        note = created.first()
        self.assertEqual(note.target_url, self.group_url())
        self.assertIn(
            timezone.localtime(self.starts_at).strftime("%d/%m/%Y %H:%M"), note.message
        )

    def test_reschedule_notifies_everyone_except_editor_and_resets_reminder(self):
        meeting = self.make_meeting(actor=self.alice)
        Meeting.objects.filter(pk=meeting.pk).update(reminder_sent_at=timezone.now())
        new_time = self.starts_at + timedelta(hours=2)

        reschedule_meeting(
            meeting=meeting,
            actor=self.bob,
            title=meeting.title,
            meeting_url=meeting.meeting_url,
            starts_at=new_time,
        )

        updated = self.notifications(Notification.Type.MEETING_UPDATED)
        self.assertEqual(
            sorted(n.recipient_id for n in updated),
            sorted([self.alice.pk, self.carol.pk]),
        )
        self.assertIn("เลื่อน", updated.first().message)
        self.assertIn(
            timezone.localtime(new_time).strftime("%d/%m/%Y %H:%M"),
            updated.first().message,
        )
        meeting.refresh_from_db()
        self.assertIsNone(meeting.reminder_sent_at)

    def test_title_or_link_change_notifies_but_keeps_reminder_state(self):
        meeting = self.make_meeting(actor=self.alice)
        sent_at = timezone.now()
        Meeting.objects.filter(pk=meeting.pk).update(reminder_sent_at=sent_at)

        reschedule_meeting(
            meeting=meeting,
            actor=self.carol,
            title="หัวข้อใหม่",
            meeting_url="https://meet.example.com/new",
            starts_at=meeting.starts_at,
        )

        updated = self.notifications(Notification.Type.MEETING_UPDATED)
        self.assertEqual(
            sorted(n.recipient_id for n in updated),
            sorted([self.alice.pk, self.bob.pk]),
        )
        self.assertIn("แก้ไขรายละเอียด", updated.first().message)
        meeting.refresh_from_db()
        self.assertEqual(meeting.reminder_sent_at, sent_at)

    def test_saving_without_changes_sends_nothing(self):
        meeting = self.make_meeting()
        changed = reschedule_meeting(
            meeting=meeting,
            actor=self.bob,
            title=meeting.title,
            meeting_url=meeting.meeting_url,
            starts_at=meeting.starts_at,
        )
        self.assertFalse(changed)
        self.assertFalse(self.notifications(Notification.Type.MEETING_UPDATED).exists())

    def test_reminder_goes_to_every_member_once(self):
        meeting = self.make_meeting(actor=self.alice)
        before_start = meeting.starts_at - timedelta(minutes=10)

        self.assertEqual(send_due_reminders(now=before_start), 1)
        self.assertEqual(send_due_reminders(now=before_start + timedelta(minutes=1)), 0)

        reminders = self.notifications(Notification.Type.MEETING_REMINDER)
        self.assertEqual(
            sorted(n.recipient_id for n in reminders),
            sorted([self.alice.pk, self.bob.pk, self.carol.pk]),
        )
        # In the normal case the creator hears about their own meeting only once.
        self.assertEqual(Notification.objects.filter(recipient=self.alice).count(), 1)

    def test_reminder_waits_until_fifteen_minutes_before(self):
        meeting = self.make_meeting()
        self.assertEqual(
            send_due_reminders(now=meeting.starts_at - timedelta(minutes=16)), 0
        )
        self.assertEqual(
            send_due_reminders(now=meeting.starts_at - timedelta(minutes=15)), 1
        )

    def test_rescheduled_meeting_is_reminded_again_for_new_time(self):
        meeting = self.make_meeting()
        send_due_reminders(now=meeting.starts_at - timedelta(minutes=5))
        new_time = meeting.starts_at + timedelta(hours=1)
        reschedule_meeting(
            meeting=meeting,
            actor=self.bob,
            title=meeting.title,
            meeting_url=meeting.meeting_url,
            starts_at=new_time,
        )
        self.assertEqual(send_due_reminders(now=new_time - timedelta(minutes=5)), 1)
        self.assertEqual(
            self.notifications(Notification.Type.MEETING_REMINDER, self.alice).count(),
            2,
        )

    def test_meeting_starting_within_fifteen_minutes_gets_both_notices(self):
        soon = timezone.now() + timedelta(minutes=5)
        self.make_meeting(actor=self.alice, starts_at=soon)
        self.assertEqual(send_due_reminders(), 1)
        self.assertEqual(
            self.notifications(Notification.Type.MEETING_CREATED, self.bob).count(), 1
        )
        self.assertEqual(
            self.notifications(Notification.Type.MEETING_REMINDER, self.bob).count(), 1
        )

    @override_settings(TIME_ZONE="UTC")
    def test_notification_times_are_bangkok_time(self):
        starts_at = datetime(2030, 1, 1, 3, 0, tzinfo=dt_timezone.utc)
        self.make_meeting(actor=self.alice, starts_at=starts_at)
        send_due_reminders(now=starts_at - timedelta(minutes=5))
        for notification_type in (
            Notification.Type.MEETING_CREATED,
            Notification.Type.MEETING_REMINDER,
        ):
            self.assertIn(
                "01/01/2030 10:00",
                self.notifications(notification_type).first().message,
            )

    def test_reminder_skips_meetings_of_dissolved_team(self):
        meeting = self.make_meeting()
        for user in (self.alice, self.bob, self.carol):
            leave_team(team_id=self.team.pk, user=user)
        self.assertFalse(Team.objects.filter(pk=self.team.pk).exists())
        Notification.objects.all().delete()
        self.assertEqual(
            send_due_reminders(now=meeting.starts_at - timedelta(minutes=5)), 0
        )
        self.assertFalse(Notification.objects.exists())


class MigrationTests(TestCase):
    def test_models_and_migrations_are_in_sync(self):
        call_command("makemigrations", "--check", "--dry-run", stdout=StringIO())

    def test_meeting_created_notification_type_is_stored(self):
        user = make_user("store@example.com")
        notification = Notification.objects.create(
            recipient=user,
            title="t",
            message="m",
            notification_type=Notification.Type.MEETING_CREATED,
        )
        notification.full_clean()

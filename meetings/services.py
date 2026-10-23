from datetime import timedelta

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from notifications.models import Notification
from notifications.services import send_notification

from .models import Meeting


def get_group_access():
    adapter_path = getattr(
        settings,
        "MEETINGS_GROUP_ACCESS_ADAPTER",
        "meetings.group_access.AuthGroupAccess",
    )
    return import_string(adapter_path)


def create_meeting(*, group, actor, title, meeting_url, starts_at):
    content_type = ContentType.objects.get_for_model(group, for_concrete_model=False)
    return Meeting.objects.create(
        group_content_type=content_type,
        group_object_id=group.pk,
        created_by=actor,
        title=title,
        meeting_url=meeting_url,
        starts_at=starts_at,
    )


@transaction.atomic
def reschedule_meeting(*, meeting, actor, title, meeting_url, starts_at):
    # ModelForm validation copies submitted values onto its `instance` before
    # this service is called. Reload the persisted row so change detection
    # compares the submitted values with what was actually saved before.
    meeting = Meeting.objects.select_for_update().get(pk=meeting.pk)
    time_changed = meeting.starts_at != starts_at
    changed = any(
        (
            meeting.title != title,
            meeting.meeting_url != meeting_url,
            meeting.starts_at != starts_at,
        )
    )
    if not changed:
        return False

    meeting.title = title
    meeting.meeting_url = meeting_url
    meeting.starts_at = starts_at
    update_fields = ["title", "meeting_url", "starts_at", "updated_at"]
    if time_changed:
        meeting.reminder_sent_at = None
        update_fields.append("reminder_sent_at")
    meeting.save(update_fields=update_fields)

    group_access = get_group_access()
    target_url = f"/meetings/groups/{meeting.group_object_id}/"
    for recipient in group_access.members(meeting.group):
        send_notification(
            recipient=recipient,
            actor=actor,
            title="มีการเปลี่ยนแปลงนัดหมายประชุม",
            message=f"{title} ถูกแก้ไข เวลาใหม่ {timezone.localtime(starts_at):%d/%m/%Y %H:%M}",
            notification_type=Notification.Type.MEETING_UPDATED,
            target_url=target_url,
        )
    return True


@transaction.atomic
def send_due_reminders(*, now=None, reminder_minutes=None):
    now = now or timezone.now()
    reminder_minutes = reminder_minutes or getattr(settings, "MEETING_REMINDER_MINUTES", 15)
    window_end = now + timedelta(minutes=reminder_minutes)
    due = (
        Meeting.objects.select_for_update()
        .filter(starts_at__gt=now, starts_at__lte=window_end, reminder_sent_at__isnull=True)
        .order_by("starts_at", "pk")
    )
    sent = 0
    group_access = get_group_access()
    for meeting in due:
        group = meeting.group
        if group is None:
            continue
        target_url = f"/meetings/groups/{meeting.group_object_id}/"
        for recipient in group_access.members(group):
            send_notification(
                recipient=recipient,
                actor=meeting.created_by,
                title="ใกล้ถึงเวลาประชุมกลุ่ม",
                message=f"{meeting.title} จะเริ่มเวลา {timezone.localtime(meeting.starts_at):%H:%M}",
                notification_type=Notification.Type.MEETING_REMINDER,
                target_url=target_url,
            )
        meeting.reminder_sent_at = now
        meeting.save(update_fields=["reminder_sent_at"])
        sent += 1
    return sent

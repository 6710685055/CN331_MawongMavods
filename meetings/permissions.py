from django.contrib.contenttypes.models import ContentType

from .models import Meeting


def can_access_group(user, group, group_access):
    return bool(user.is_authenticated and group_access.is_member(user, group))


def can_access_meeting(user, meeting, group_access):
    group = meeting.group
    return bool(group and can_access_group(user, group, group_access))


def meetings_for_group(group):
    content_type = ContentType.objects.get_for_model(group, for_concrete_model=False)
    return Meeting.objects.filter(
        group_content_type=content_type,
        group_object_id=group.pk,
    )

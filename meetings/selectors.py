from django.db.models import Q
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from .models import Meeting


def upcoming_for_group(group):
    content_type = ContentType.objects.get_for_model(group, for_concrete_model=False)
    return (
        Meeting.objects.filter(
            group_content_type=content_type,
            group_object_id=group.pk,
            starts_at__gte=timezone.now(),
        )
        .select_related("created_by", "group_content_type")
        .order_by("starts_at", "pk")
    )


def upcoming_for_user(user, group_access):
    group_filter = Q(pk__in=[])
    for group in group_access.groups_for_user(user):
        group_filter |= Q(
            group_content_type=ContentType.objects.get_for_model(group, for_concrete_model=False),
            group_object_id=group.pk,
        )
    return (
        Meeting.objects.filter(group_filter, starts_at__gte=timezone.now())
        .select_related("created_by", "group_content_type")
        .order_by("starts_at", "pk")
    )

from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.prefetch import GenericPrefetch
from django.utils import timezone

from .models import Meeting


def group_content_type(model_or_group):
    return ContentType.objects.get_for_model(model_or_group, for_concrete_model=False)


def upcoming_for_group(group):
    return (
        Meeting.objects.filter(
            group_content_type=group_content_type(group),
            group_object_id=group.pk,
            starts_at__gte=timezone.now(),
        )
        .select_related("created_by", "group_content_type")
        .order_by("starts_at", "pk")
    )


def upcoming_for_user(user, group_access):
    """Upcoming meetings of every group the user belongs to under the active adapter.

    Only meetings linked to the adapter's model are considered, so a meeting that
    points at another model (e.g. an old Django `Group`) never matches a team by id.
    """
    groups = group_access.groups_for_user(user)
    return (
        Meeting.objects.filter(
            group_content_type=group_content_type(group_access.model),
            group_object_id__in=[group.pk for group in groups],
            starts_at__gte=timezone.now(),
        )
        .select_related("created_by", "group_content_type")
        .prefetch_related(GenericPrefetch("group", [groups]))
        .order_by("starts_at", "pk")
    )

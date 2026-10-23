"""Group access adapter for UC2.

The current project has no project-team model yet. The default adapter uses
Django auth groups for local end-to-end use. UC1 can replace this adapter with
its team model without changing the meeting schema or services.
"""

from django.contrib.auth.models import Group


class AuthGroupAccess:
    """Temporary adapter backed by Django's built-in groups."""

    @staticmethod
    def groups_for_user(user):
        return user.groups.all().order_by("name")

    @staticmethod
    def get_group_for_user(user, group_id):
        return Group.objects.filter(pk=group_id, user=user).first()

    @staticmethod
    def is_member(user, group):
        return group.user_set.filter(pk=user.pk).exists()

    @staticmethod
    def members(group):
        return group.user_set.filter(is_active=True).order_by("pk")

"""Group access adapters for UC2.

`TeamAccess` is the default: meetings belong to a `courses.Team` and its members
come from `TeamMembership`. `AuthGroupAccess` is the earlier adapter backed by
Django auth groups, kept so the setting can still point at it.

Each adapter exposes `model`, the group model its meetings are linked to.
Meetings linked to any other model are ignored rather than matched by id.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from courses.models import Enrollment, Team


class TeamAccess:
    """Meetings belong to a project team; membership is `TeamMembership`.

    A member also needs a Student enrollment in the team's course, so a student
    removed from the course loses the team's meetings even if the membership row
    is still there.
    """

    model = Team

    @staticmethod
    def _teams_of(user):
        # One filter() call so the membership and the enrollment belong to the same user.
        return Team.objects.filter(
            memberships__user=user,
            course__enrollments__user=user,
            course__enrollments__role=Enrollment.Role.STUDENT,
        )

    @classmethod
    def groups_for_user(cls, user):
        return (
            cls._teams_of(user)
            .select_related("course")
            .order_by("course__code", "name", "pk")
        )

    @classmethod
    def get_group_for_user(cls, user, group_id):
        return cls._teams_of(user).filter(pk=group_id).select_related("course").first()

    @classmethod
    def is_member(cls, user, group):
        return bool(
            isinstance(group, Team)
            and user.is_active
            and cls._teams_of(user).filter(pk=group.pk).exists()
        )

    @staticmethod
    def members(group):
        if not isinstance(group, Team):
            return get_user_model().objects.none()
        return get_user_model().objects.filter(
            team_memberships__team=group,
            enrollments__course_id=group.course_id,
            enrollments__role=Enrollment.Role.STUDENT,
            is_active=True,
        ).order_by("pk")


class AuthGroupAccess:
    """Earlier adapter backed by Django's built-in groups."""

    model = Group

    @staticmethod
    def groups_for_user(user):
        return user.groups.all().order_by("name")

    @staticmethod
    def get_group_for_user(user, group_id):
        return Group.objects.filter(pk=group_id, user=user).first()

    @staticmethod
    def is_member(user, group):
        return isinstance(group, Group) and group.user_set.filter(pk=user.pk).exists()

    @staticmethod
    def members(group):
        if not isinstance(group, Group):
            return get_user_model().objects.none()
        return group.user_set.filter(is_active=True).order_by("pk")

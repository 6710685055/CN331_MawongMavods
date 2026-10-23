from accounts.models import User

from .models import Enrollment


def get_enrollment(user, course):
    """Return the Enrollment instance for (user, course), or None if not enrolled."""
    if not user or not getattr(user, "is_authenticated", False):
        return None
    return Enrollment.objects.filter(user=user, course=course).first()


def is_course_member(user, course) -> bool:
    """True if the user is logged in and enrolled in the course (any role)."""
    return get_enrollment(user, course) is not None


def is_course_ta(user, course) -> bool:
    """True only if the user is an approved TA (Enrollment.Role.TA) in the course."""
    enrollment = get_enrollment(user, course)
    return bool(enrollment and enrollment.role == Enrollment.Role.TA)


def is_course_teacher(user, course) -> bool:
    """True only if the user is an approved Teacher enrolled as TEACHER in the course."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "teacher_status", None) != User.TeacherStatus.APPROVED:
        return False
    enrollment = get_enrollment(user, course)
    return bool(enrollment and enrollment.role == Enrollment.Role.TEACHER)


def is_course_staff(user, course) -> bool:
    """True if the user is an approved TA or an approved Teacher of the course."""
    return is_course_ta(user, course) or is_course_teacher(user, course)

from django.db import IntegrityError, transaction

from accounts.models import User

from .models import Enrollment


class EnrollmentError(Exception):
    """Raised with a user-facing (Thai) message."""


def enroll(user, course):
    if user.role == User.Role.ADMIN:
        raise EnrollmentError("บัญชี Admin ไม่สามารถลงทะเบียนรายวิชาได้")

    if user.role == User.Role.TEACHER:
        if user.teacher_status != User.TeacherStatus.APPROVED:
            raise EnrollmentError("บัญชีอาจารย์ของคุณยังรออนุมัติจาก Admin จึงยังลงทะเบียนเป็นผู้สอนไม่ได้")
        role = Enrollment.Role.TEACHER
    elif user.role == User.Role.TA:
        # Enrolled, but no TA powers until the course's teacher approves (UC16).
        role = Enrollment.Role.TA_PENDING
    else:
        role = Enrollment.Role.STUDENT_PENDING

    try:
        with transaction.atomic():
            return Enrollment.objects.create(user=user, course=course, role=role)
    except IntegrityError:
        raise EnrollmentError("คุณลงทะเบียนวิชานี้แล้ว")

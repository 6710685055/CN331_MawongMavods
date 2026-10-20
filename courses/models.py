from django.conf import settings
from django.db import models


class Course(models.Model):
    code = models.CharField("รหัสวิชา", max_length=20, unique=True)
    name = models.CharField("ชื่อวิชา", max_length=200)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"


class Enrollment(models.Model):
    class Role(models.TextChoices):
        STUDENT = "student", "นักศึกษา"
        TA_PENDING = "ta_pending", "TA (รออาจารย์อนุมัติ)"  # promoted to TA by UC16
        TA = "ta", "TA"
        TEACHER = "teacher", "อาจารย์"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollments"
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="enrollments")
    role = models.CharField(max_length=12, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "course"], name="unique_user_course")
        ]

    def __str__(self):
        return f"{self.user} -> {self.course} ({self.role})"

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", "admin")
        extra.setdefault("email_verified", True)
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    """Any email is accepted (multi-university). Login is by email."""

    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        TA = "ta", "TA"
        TEACHER = "teacher", "Teacher"
        ADMIN = "admin", "Admin"

    class TeacherStatus(models.TextChoices):
        NONE = "none", "-"
        PENDING = "pending", "รออนุมัติ"
        APPROVED = "approved", "อนุมัติแล้ว"
        REJECTED = "rejected", "ถูกปฏิเสธ"

    username = None
    email = models.EmailField("อีเมล", unique=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)
    teacher_status = models.CharField(
        max_length=10, choices=TeacherStatus.choices, default=TeacherStatus.NONE
    )
    email_verified = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UserManager()

    def __str__(self):
        return self.email

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email

from django.conf import settings
from django.db import models
from django.db.models import Q


MAX_TEAM_MEMBERS = 5


class Course(models.Model):
    code = models.CharField("รหัสวิชา", max_length=20, unique=True)
    name = models.CharField("ชื่อวิชา", max_length=200)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_courses",
        verbose_name="เจ้าของวิชา",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"


class Enrollment(models.Model):
    class Role(models.TextChoices):
        STUDENT_PENDING = "stu_pending", "นักศึกษา (รออนุมัติ)"
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


class Team(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField("ชื่อกลุ่ม", max_length=100)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_teams",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return f"{self.course.code}: {self.name}"

    @property
    def member_count(self):
        return self.memberships.count()

    @property
    def available_slots(self):
        reserved = self.invitations.filter(status=TeamInvitation.Status.PENDING).count()
        return max(0, MAX_TEAM_MEMBERS - self.member_count - reserved)


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="team_memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="team_memberships",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["joined_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "course"], name="unique_user_team_course"),
            models.UniqueConstraint(fields=["team", "user"], name="unique_team_user"),
        ]

    def __str__(self):
        return f"{self.user} -> {self.team}"


class TeamInvitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "รอตอบรับ"
        ACCEPTED = "accepted", "ตอบรับแล้ว"
        DECLINED = "declined", "ปฏิเสธแล้ว"
        CANCELLED = "cancelled", "ยกเลิกแล้ว"

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="invitations")
    inviter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_team_invitations",
    )
    invitee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_team_invitations",
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "invitee"],
                condition=Q(status="pending"),
                name="unique_pending_team_invitation",
            )
        ]

    def __str__(self):
        return f"{self.inviter} -> {self.invitee} ({self.team})"


class TeamChat(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, related_name="chat")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Chat: {self.team}"


class TeamChatMessage(models.Model):
    chat = models.ForeignKey(TeamChat, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="team_chat_messages",
    )
    body = models.TextField("ข้อความ")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.sender}: {self.body[:40]}"

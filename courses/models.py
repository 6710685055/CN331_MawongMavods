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
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="enrollments"
    )
    role = models.CharField(max_length=12, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "course"], name="unique_user_course"
            )
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
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="team_memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="team_memberships",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["joined_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "course"], name="unique_user_team_course"
            ),
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
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
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
    chat = models.ForeignKey(
        TeamChat, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="team_chat_messages",
    )
    body = models.TextField("ข้อความ")
    attachment = models.FileField(
        "ไฟล์แนบ",
        upload_to="team_chat/%Y/%m/",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.sender}: {self.body[:40]}"


class PrivateChat(models.Model):
    """UC8: one private room per pair of users per course.

    The pair is stored in a canonical order (user_low.id < user_high.id) so the
    unique constraint blocks duplicate rooms even when both users open it at once.
    """

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="private_chats"
    )
    user_low = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )
    user_high = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "user_low", "user_high"],
                name="unique_private_chat_pair_course",
            ),
            models.CheckConstraint(
                condition=Q(user_low__lt=models.F("user_high")),
                name="private_chat_pair_ordered",
            ),
        ]

    def __str__(self):
        return f"{self.course.code}: {self.user_low} <-> {self.user_high}"

    def has_participant(self, user):
        return user.pk in (self.user_low_id, self.user_high_id)

    def other_participant(self, user):
        return self.user_high if user.pk == self.user_low_id else self.user_low


class PrivateChatMessage(models.Model):
    chat = models.ForeignKey(
        PrivateChat, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="private_chat_messages",
    )
    body = models.TextField("ข้อความ")
    created_at = models.DateTimeField(auto_now_add=True)
    # Set when a moderator confirms a report; the row is kept as evidence.
    hidden_at = models.DateTimeField("ซ่อนเมื่อ", null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.sender}: {self.body[:40]}"


class UserBlock(models.Model):
    """A block applies in both directions: neither user can message the other."""

    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocks_made",
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocks_received",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["blocker", "blocked"], name="unique_user_block"
            ),
            models.CheckConstraint(
                condition=~Q(blocker=models.F("blocked")),
                name="user_block_not_self",
            ),
        ]

    def __str__(self):
        return f"{self.blocker} blocked {self.blocked}"


class PrivateMessageReport(models.Model):
    """Report record kept for later review in Django admin.

    The message body and sender are copied at report time so the evidence stays
    readable even if the message or room is removed later.
    """

    class Reason(models.TextChoices):
        SPAM = "spam", "สแปมหรือโฆษณา"
        HARASSMENT = "harassment", "คุกคามหรือกลั่นแกล้ง"
        INAPPROPRIATE = "inappropriate", "เนื้อหาไม่เหมาะสม"
        OTHER = "other", "อื่น ๆ"

    message = models.ForeignKey(
        PrivateChatMessage,
        on_delete=models.SET_NULL,
        null=True,
        related_name="reports",
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="private_message_reports",
    )
    reported_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )

    class Status(models.TextChoices):
        PENDING = "pending", "รอตรวจสอบ"
        CONFIRMED = "confirmed", "ยืนยันรายงาน"
        REJECTED = "rejected", "ปฏิเสธรายงาน"

    reason = models.CharField("เหตุผล", max_length=20, choices=Reason.choices)
    details = models.TextField("รายละเอียดเพิ่มเติม", blank=True)
    message_body = models.TextField("ข้อความที่ถูกรายงาน")
    message_sent_at = models.DateTimeField("เวลาที่ส่งข้อความ")
    # A few neighbouring messages copied at report time, shown only to moderators.
    context_snapshot = models.JSONField(
        "บริบทข้อความใกล้เคียง", default=list, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(
        "สถานะ", max_length=20, choices=Status.choices, default=Status.PENDING
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="ผู้ตรวจ",
    )
    reviewed_at = models.DateTimeField("ตรวจเมื่อ", null=True, blank=True)
    review_note = models.TextField("หมายเหตุการตัดสิน", blank=True)
    incident = models.ForeignKey(
        "PrivateChatIncident",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
        verbose_name="เหตุการณ์ที่ยืนยัน",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["message", "reporter"],
                name="unique_private_message_report",
            )
        ]
        permissions = [
            (
                "review_privatemessagereport",
                "พิจารณารายงานข้อความส่วนตัวและยกเลิกการระงับ",
            )
        ]

    def __str__(self):
        return f"{self.reporter} reported {self.reported_user} ({self.reason})"


class PrivateChatIncident(models.Model):
    """One confirmed violation per message, however many reports point at it.

    `sequence` is the sender's running count of confirmed incidents; the unique
    constraint stops two concurrent confirmations from sharing a number.
    """

    class Action(models.TextChoices):
        WARNING = "warning", "คำเตือน"
        SUSPENSION = "suspension", "ระงับการส่งข้อความ 24 ชั่วโมง"

    message = models.ForeignKey(
        PrivateChatMessage,
        on_delete=models.SET_NULL,
        null=True,
        related_name="incidents",
    )
    offender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="private_chat_incidents",
        verbose_name="ผู้ส่งข้อความ",
    )
    course = models.ForeignKey(
        Course, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    message_body = models.TextField("ข้อความที่ยืนยัน")
    sequence = models.PositiveIntegerField("ครั้งที่")
    action = models.CharField("การดำเนินการ", max_length=20, choices=Action.choices)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        verbose_name="ผู้ยืนยัน",
    )
    confirmed_at = models.DateTimeField("ยืนยันเมื่อ")

    class Meta:
        ordering = ["-confirmed_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["message"], name="unique_incident_per_message"
            ),
            models.UniqueConstraint(
                fields=["offender", "sequence"], name="unique_incident_sequence"
            ),
        ]

    def __str__(self):
        return f"{self.offender} #{self.sequence} ({self.get_action_display()})"


class PrivateChatSuspension(models.Model):
    """`user` may not send private messages to `counterpart` until `ends_at`.

    Expiry is read from `ends_at` on every send; nothing in memory tracks it.
    """

    incident = models.OneToOneField(
        PrivateChatIncident, on_delete=models.CASCADE, related_name="suspension"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="private_chat_suspensions",
        verbose_name="ผู้ถูกระงับ",
    )
    counterpart = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name="คู่สนทนา",
    )
    starts_at = models.DateTimeField("เริ่มระงับ")
    ends_at = models.DateTimeField("สิ้นสุดการระงับ")
    lifted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="ผู้ยกเลิก",
    )
    lifted_at = models.DateTimeField("ยกเลิกเมื่อ", null=True, blank=True)
    lift_reason = models.TextField("เหตุผลการยกเลิก", blank=True)

    class Meta:
        ordering = ["-starts_at", "-id"]

    def __str__(self):
        return f"{self.user} -> {self.counterpart} until {self.ends_at:%Y-%m-%d %H:%M}"

    def is_active(self, now):
        return self.lifted_at is None and self.starts_at <= now < self.ends_at


class PrivateChatModerationLog(models.Model):
    """Append-only audit trail of moderation decisions."""

    class Action(models.TextChoices):
        REPORT_CONFIRMED = "report_confirmed", "ยืนยันรายงาน"
        REPORT_REJECTED = "report_rejected", "ปฏิเสธรายงาน"
        WARNING_ISSUED = "warning_issued", "ออกคำเตือน"
        SUSPENDED = "suspended", "ระงับการส่งข้อความ"
        SUSPENSION_LIFTED = "suspension_lifted", "ยกเลิกการระงับ"

    action = models.CharField("การดำเนินการ", max_length=30, choices=Action.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        verbose_name="ผู้ดำเนินการ",
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        verbose_name="ผู้ได้รับผล",
    )
    report = models.ForeignKey(
        PrivateMessageReport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    incident = models.ForeignKey(
        PrivateChatIncident,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    suspension = models.ForeignKey(
        PrivateChatSuspension,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    note = models.TextField("หมายเหตุ", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_action_display()} by {self.actor}"

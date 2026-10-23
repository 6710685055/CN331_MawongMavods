from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.validators import MinLengthValidator
from django.db import models


class Meeting(models.Model):
    """A group meeting linked through a generic reference to keep UC1 swappable."""

    group_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="group_meetings",
    )
    group_object_id = models.PositiveBigIntegerField()
    group = GenericForeignKey("group_content_type", "group_object_id")

    title = models.CharField("หัวข้อการประชุม", max_length=160, validators=[MinLengthValidator(3)])
    meeting_url = models.URLField("ลิงก์ประชุม", max_length=500)
    starts_at = models.DateTimeField("วันและเวลาประชุม")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_meetings",
        verbose_name="ผู้สร้างนัดหมาย",
    )
    created_at = models.DateTimeField("สร้างเมื่อ", auto_now_add=True)
    updated_at = models.DateTimeField("แก้ไขล่าสุด", auto_now=True)
    reminder_sent_at = models.DateTimeField("ส่งแจ้งเตือนแล้วเมื่อ", null=True, blank=True)

    class Meta:
        ordering = ["starts_at", "pk"]
        indexes = [models.Index(fields=["starts_at", "reminder_sent_at"])]

    def __str__(self):
        return f"{self.title} ({self.starts_at:%Y-%m-%d %H:%M})"

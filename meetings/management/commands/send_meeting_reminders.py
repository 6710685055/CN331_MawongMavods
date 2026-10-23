from django.core.management.base import BaseCommand

from meetings.services import send_due_reminders


class Command(BaseCommand):
    help = "Send in-app notifications for meetings approaching their start time."

    def handle(self, *args, **options):
        count = send_due_reminders()
        self.stdout.write(self.style.SUCCESS(f"ส่งการแจ้งเตือนล่วงหน้าสำเร็จ {count} นัดหมาย"))

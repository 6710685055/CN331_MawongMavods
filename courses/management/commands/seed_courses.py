from django.core.management.base import BaseCommand

from courses.models import Course

SAMPLE = [
    ("CN331", "Software Engineering"),
    ("CN240", "Introduction to Computer Programming"),
    ("CN201", "Data Structures"),
    ("CN202", "Operating Systems"),
    ("CN310", "Database Systems"),
]


class Command(BaseCommand):
    help = "Create a few sample courses for local development."

    def handle(self, *args, **options):
        for code, name in SAMPLE:
            _, created = Course.objects.get_or_create(code=code, defaults={"name": name})
            self.stdout.write(f"{'created' if created else 'exists '} {code}")

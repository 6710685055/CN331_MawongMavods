import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User

EMAIL_VAR = "DJANGO_SUPERUSER_EMAIL"
REQUIRED_VARS = (
    "DJANGO_SUPERUSER_PASSWORD",
    "DJANGO_SUPERUSER_FIRST_NAME",
    "DJANGO_SUPERUSER_LAST_NAME",
)


class Command(BaseCommand):
    help = (
        "Create the admin account from DJANGO_SUPERUSER_* env vars if it does not "
        "exist yet. Used by build.sh because Render's free plan has no shell."
    )

    def handle(self, *args, **options):
        email = os.environ.get(EMAIL_VAR, "").strip().lower()
        if not email:
            self.stdout.write(f"{EMAIL_VAR} is not set; skipping superuser.")
            return

        if User.objects.filter(email__iexact=email).exists():
            self.stdout.write(f"Superuser {email} already exists; skipping.")
            return

        missing = [name for name in REQUIRED_VARS if not os.environ.get(name, "")]
        if missing:
            raise CommandError(f"Missing environment variables: {', '.join(missing)}")

        password = os.environ["DJANGO_SUPERUSER_PASSWORD"]
        user = User(
            email=email,
            first_name=os.environ["DJANGO_SUPERUSER_FIRST_NAME"],
            last_name=os.environ["DJANGO_SUPERUSER_LAST_NAME"],
        )
        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            raise CommandError(
                "DJANGO_SUPERUSER_PASSWORD is too weak: " + " ".join(exc.messages)
            ) from exc

        User.objects.create_superuser(
            email=email,
            password=password,
            first_name=user.first_name,
            last_name=user.last_name,
        )
        self.stdout.write(self.style.SUCCESS(f"Created superuser {email}."))

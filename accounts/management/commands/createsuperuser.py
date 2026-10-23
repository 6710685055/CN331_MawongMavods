from contextlib import contextmanager

from django.contrib.auth.management.commands import createsuperuser as django_command
from django.utils import translation


class Command(django_command.Command):
    """Use the project's preferred English labels for superuser prompts."""

    def _get_input_message(self, field, default=None):
        labels = {
            "email": "email",
            "first_name": "Name",
            "last_name": "Surname",
        }
        label = labels.get(field.name)
        if label is None:
            return super()._get_input_message(field, default)
        return "%s%s: " % (
            label,
            " (leave blank to use '%s')" % default if default else "",
        )

    def handle(self, *args, **options):
        original_getpass = django_command.getpass.getpass

        @contextmanager
        def english_prompts():
            def getpass(prompt="Password: ", stream=None):
                if prompt == "Password (again): ":
                    prompt = "Password (confirmed): "
                return original_getpass(prompt, stream)

            django_command.getpass.getpass = getpass
            try:
                yield
            finally:
                django_command.getpass.getpass = original_getpass

        with translation.override("en"), english_prompts():
            return super().handle(*args, **options)

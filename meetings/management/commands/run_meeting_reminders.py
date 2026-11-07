import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from meetings.services import send_due_reminders

logger = logging.getLogger("meetings.reminders")


class Command(BaseCommand):
    help = (
        "Keep sending meeting reminders every --interval seconds. Used on hosts "
        "without a scheduler (Render free plan); start.sh runs it next to Daphne."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=int,
            default=60,
            help="Seconds to wait between runs (default: 60).",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run a single pass and exit.",
        )

    def handle(self, *args, interval, once, **options):
        logger.info("Meeting reminder loop started (interval=%ss)", interval)
        while True:
            self.run_once()
            if once:
                return
            time.sleep(interval)

    def run_once(self):
        # The loop outlives any single query, so drop stale connections around
        # each pass instead of keeping one open forever.
        close_old_connections()
        try:
            sent = send_due_reminders()
        except Exception:
            # Keep the loop alive; the next pass retries the same meetings
            # because reminder_sent_at was not saved.
            logger.exception("Sending meeting reminders failed")
            sent = 0
        finally:
            close_old_connections()
        if sent:
            logger.info("Sent reminders for %s meeting(s)", sent)
        return sent

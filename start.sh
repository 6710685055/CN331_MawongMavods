#!/usr/bin/env bash
# Render start command (see render.yaml).
set -o errexit

# Render's free plan has no cron, so meeting reminders run as a loop beside the
# web server. The loop stops while the free instance sleeps.
if [ "${ENABLE_MEETING_REMINDER_LOOP:-0}" = "1" ]; then
  python manage.py run_meeting_reminders &
fi

exec daphne -b 0.0.0.0 -p "${PORT:-8000}" config.asgi:application

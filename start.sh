#!/usr/bin/env bash
# Render start command (see render.yaml).
set -o errexit

# Render's free plan has no cron, so meeting reminders run as a loop beside the
# web server. If the loop process dies it is restarted after 10 seconds. The
# loop stops while the free instance sleeps.
if [ "${ENABLE_MEETING_REMINDER_LOOP:-0}" = "1" ]; then
  (
    while true; do
      python manage.py run_meeting_reminders \
        || echo "Meeting reminder loop exited with status $?; restarting in 10s."
      sleep 10
    done
  ) &
fi

exec daphne -b 0.0.0.0 -p "${PORT:-8000}" config.asgi:application

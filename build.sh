#!/usr/bin/env bash
# Render build command (see render.yaml). Exit on the first error.
set -o errexit

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input
python manage.py seed_courses

# The free plan has no shell, so the admin account comes from env vars:
# DJANGO_SUPERUSER_EMAIL, DJANGO_SUPERUSER_PASSWORD,
# DJANGO_SUPERUSER_FIRST_NAME, DJANGO_SUPERUSER_LAST_NAME.
if [ -n "${DJANGO_SUPERUSER_EMAIL:-}" ]; then
  python manage.py createsuperuser --no-input \
    || echo "Superuser ${DJANGO_SUPERUSER_EMAIL} already exists; skipping."
fi

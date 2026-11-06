# UC2: Group Meeting & Notification

## Scope

Members of a project team (`courses.Team`) can create a meeting with a title, URL and future date/time, view upcoming meetings in their team's meeting page (and on the team dashboard), and edit or reschedule it. Members are notified when a meeting is created or changed, and everyone is reminded 15 minutes before it starts.

## Design

- `Meeting` stores meeting data and a generic reference to its group (`group_content_type`, `group_object_id`).
- `meetings.group_access.TeamAccess` is the default adapter (`MEETINGS_GROUP_ACCESS_ADAPTER` in `config/settings.py`). Membership comes from `TeamMembership`; a member must be an active user with a Student enrollment in the team's course, so a student removed from the course loses access even if the membership row remains. `AuthGroupAccess` (Django auth groups) is kept but no longer used.
- Each adapter declares the group `model` its meetings belong to. Pages, edits and reminders only consider meetings linked to that model, so a meeting linked to another model is never matched to a team just because the ids are equal.
- URLs use the team id: `/meetings/teams/<team_id>/` and `/meetings/teams/<team_id>/create/`. Every view checks team membership on the server and returns 403 to non-members, including direct URL access and unknown team ids.
- `meetings.services` handles creation, rescheduling and reminder delivery; `meetings.selectors` reads upcoming meetings; `meetings.permissions` checks group access.
- All notifications go through the shared `notifications.services.send_notification`.

## Notification rules

| Event | Recipients | Notes |
| --- | --- | --- |
| Meeting created | Every team member except the creator | Type `meeting_created` |
| Start time changed | Every team member except the editor | Type `meeting_updated`; clears `reminder_sent_at` so the new time gets its own reminder |
| Only title or link changed | Every team member except the editor | Type `meeting_updated`; reminder state is kept |
| 15 minutes before start | Every team member, creator included | Type `meeting_reminder`; sent once per start time (`reminder_sent_at`) |

- Times in notification text are always Thai time (`Asia/Bangkok`, `dd/mm/yyyy HH:MM`).
- A meeting created or moved to start within 15 minutes gets the create/update notice and then the reminder on the next reminder run, close together. This is accepted.
- Notifications are in-app and appear on the next page load; there is no real-time push in UC2.

## Existing meetings linked to Django `Group`

Nothing has been deployed yet, so meetings linked to a Django `Group` are local test data. They are not migrated or deleted: a `Group` cannot be matched to a `Team` reliably (names and members differ, and equal ids are a coincidence). These meetings stay in the database untouched and are ignored by every page and by `send_meeting_reminders`. To clear them locally, delete them in Django Admin, or delete `db.sqlite3` and run `python manage.py migrate` again.

## Acceptance criteria mapping

| Acceptance criterion | Implementation |
| --- | --- |
| Team members create meetings | `meetings/views.py`, `meetings/group_access.py` |
| Title, meeting URL, date and time | `meetings/forms.py`, `meetings/models.py` |
| Upcoming meetings shown first, linked from the team page | `meetings/selectors.py`, `templates/meetings/group_meetings.html`, `templates/courses/group_dashboard.html` |
| Members edit or reschedule | `meetings/views.py`, `meetings/services.py` |
| Notify members on create and change | `meetings/services.py`, `notifications` app |
| Reminder before start | `meetings/management/commands/send_meeting_reminders.py`, `meetings/services.py` |

## Running the reminder command

The Django web server does not run reminders by itself. Something must call this command once per minute:

```bash
python manage.py send_meeting_reminders
```

Running it more often or twice in a row is safe: a meeting is only reminded once per start time.

### Local development

Run the command manually, or use Windows Task Scheduler to run it every minute from the project directory with the project's virtual environment.

### Render

Use a Render **Cron Job** service built from the same repository and environment as the web service:

- **Schedule:** `* * * * *` (every minute, UTC; the command itself works in Thai time)
- **Build command:** the same as the web service, e.g. `pip install -r requirements.txt`
- **Command:** `python manage.py send_meeting_reminders`
- **Environment:** the same variables as the web service (for example `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS`, and the database connection). Set the values in the Render dashboard or an environment group; never commit them.

Important: a Cron Job runs as a separate service with its own disk. With the current `config/settings.py`, which always uses SQLite (`db.sqlite3`), the cron job would read a different, empty database and send nothing. The reminder schedule only works on Render once the project uses a shared database such as Render PostgreSQL. That change is outside UC2 and needs a team decision.

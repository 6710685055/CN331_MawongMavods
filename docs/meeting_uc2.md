# UC2: Group Meeting & Notification

## Scope

Members can create a meeting with a title, URL and future date/time, view upcoming meetings at the top of their group workspace, and edit or reschedule it. Changes notify the group's members. A reminder command creates in-app notifications up to 15 minutes before the start time.

## Design

- `Meeting` stores meeting data and a generic reference to its group. This avoids a foreign key to a group model that is not present on this branch.
- `meetings.group_access.AuthGroupAccess` is the temporary adapter for the current branch. It uses Django auth groups so UC2 can be demonstrated now. When US-01 introduces the project-team model, replace this adapter and set `MEETINGS_GROUP_ACCESS_ADAPTER` in `config/settings.py`.
- `meetings.services` handles creation, rescheduling and reminder delivery; `meetings.selectors` reads upcoming meetings; `meetings.permissions` checks group access.
- Reminders use the existing in-app `notifications` app. Configure a scheduler to invoke `send_meeting_reminders` every minute.

## Acceptance criteria mapping

| Acceptance criterion | Implementation |
| --- | --- |
| Group members create meetings | `meetings/views.py`, `meetings/group_access.py` |
| Title, meeting URL, date and time | `meetings/forms.py`, `meetings/models.py` |
| Upcoming meetings shown first | `meetings/selectors.py`, `templates/meetings/group_meetings.html` |
| Reminder before start | `meetings/management/commands/send_meeting_reminders.py`, `meetings/services.py` |
| Members edit or reschedule | `meetings/views.py`, `meetings/services.py` |
| Notify members after changes | `meetings/services.py`, existing `notifications` app |

## Local reminder setup

The reminder command needs an external scheduler; the Django web server does not run it automatically. For development, run this command manually or configure Windows Task Scheduler to run it once per minute from the project directory:

```cmd
python manage.py send_meeting_reminders
```

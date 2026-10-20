# CN331_MawongMavods — US-07 Registration, Login & Course Enrollment (UC7)

Django 5 implementation of US-07.

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py makemigrations accounts courses   # commit the generated migrations
python manage.py migrate
python manage.py seed_courses                      # sample courses
python manage.py createsuperuser                   # Admin (email + password)
python manage.py runserver
python manage.py test                              # run the tests
```

Emails (verification, password reset) print in the terminal running `runserver`.
Teacher accounts are approved in `/admin/` → Users → action "อนุมัติบัญชีอาจารย์ที่เลือก".

## Acceptance Criteria → where it is done

| AC | Where |
|---|---|
| Register with any email, choose Student/TA/Teacher | `accounts/forms.py: RegisterForm` |
| Duplicate email not allowed | `RegisterForm.clean_email` (case-insensitive) |
| Verification email; login only after verifying | `accounts/views.py`, `tokens.py`, `EmailLoginForm.confirm_login_allowed` |
| Student usable right after verifying | `User.email_verified` |
| TA has no TA rights until the teacher approves | `Enrollment.Role.TA_PENDING` (promotion = UC16) |
| Teacher is "pending" until Admin approves | `User.teacher_status`, `accounts/admin.py` |
| Search and enroll in courses | `courses/views.py`, `courses/services.py` |
| Reset password by email | `accounts/urls.py` (Django built-in views) |

## Out of scope (other stories)
- UC15 full Admin approval screen/notification (only a Django-admin action here)
- UC16 teacher approving TA requests (the `TA_PENDING` → `TA` change)
- Teacher↔course ownership (who teaches which course)

## DoD notes
- Server-side permission checks: enrollment rules live in `services.enroll`, not in the template; enroll is POST-only + CSRF; `next` redirect is validated.
- Not run yet: this was written without Django installed, so run `python manage.py test` once before opening the PR.

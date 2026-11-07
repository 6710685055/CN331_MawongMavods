import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Base Directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env
load_dotenv(BASE_DIR / ".env")

# Render sets RENDER=true on its instances. Production-only settings key off
# this flag rather than DEBUG, because the test runner forces DEBUG=False.
IS_RENDER = os.environ.get("RENDER") == "true"

# Security Settings
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if IS_RENDER:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set on Render.")
    SECRET_KEY = "dev-only-change-me"
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = []

RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

if IS_RENDER:
    # Render terminates TLS at its proxy and forwards plain HTTP.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "3600"))

# Installed Applications
INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "accounts",
    "courses",
    "documents",
    "notifications",
    "meetings",
]

# UC2 meetings belong to project teams (courses.Team / TeamMembership).
MEETINGS_GROUP_ACCESS_ADAPTER = "meetings.group_access.TeamAccess"
MEETING_REMINDER_MINUTES = 15

# Middleware
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# URL Configuration
ROOT_URLCONF = "config.urls"

# Templates
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "notifications.context_processors.unread_notifications",
            ],
        },
    },
]

# WSGI
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

redis_url = os.environ.get("CHANNEL_REDIS_URL")
if redis_url:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [redis_url]},
        }
    }
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# Database: DATABASE_URL (Render PostgreSQL) when set, local SQLite otherwise.
# conn_max_age stays 0 because Daphne serves requests under ASGI, where
# persistent connections are not reused safely.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=0,
    )
}

# Custom User Model
AUTH_USER_MODEL = "accounts.User"

# Password Validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "th"
TIME_ZONE = "Asia/Bangkok"
USE_I18N = True
USE_TZ = True

# Static Files (served by WhiteNoise)
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # The manifest storage needs collectstatic first, which build.sh runs on
        # Render. Local runs and tests keep the plain storage.
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if IS_RENDER
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    },
}
# Uploaded files live on the local disk. Render's free plan has no persistent
# disk, so uploads are lost on every redeploy or restart there.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Document Upload Configuration (UC3)
DOCUMENT_MAX_FILE_SIZE_MB = 50
DOCUMENT_MAX_FILE_SIZE_BYTES = DOCUMENT_MAX_FILE_SIZE_MB * 1024 * 1024
DOCUMENT_ALLOWED_EXTENSIONS = (".pdf", ".docx", ".pptx", ".png", ".jpg")

# Document Feedback Configuration (UC10)
DOCUMENT_REPORT_HIDE_THRESHOLD = 5  # distinct reporters with an open report
DOCUMENT_REPORT_DETAIL_MAX_LENGTH = 1000

# Reported Document Review Configuration (UC14)
DOCUMENT_REPORT_DECISION_REASON_MAX_LENGTH = 1000
TEAM_CHAT_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
TEAM_CHAT_ALLOWED_EXTENSIONS = (".pdf", ".docx", ".pptx", ".png", ".jpg", ".jpeg")

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "courses:my"
LOGOUT_REDIRECT_URL = "accounts:login"

# Email Configuration
# Render's free plan blocks outbound SMTP, so production sends through the
# Brevo HTTPS API when BREVO_API_KEY is set. Local runs keep Gmail SMTP.
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
if BREVO_API_KEY:
    EMAIL_BACKEND = "anymail.backends.brevo.EmailBackend"
    ANYMAIL = {"BREVO_API_KEY": BREVO_API_KEY}
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_USE_SSL = False

EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")

# With Brevo the sender must be an address verified in the Brevo account.
DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL") or (
    f"Student Community <{EMAIL_HOST_USER}>"
    if EMAIL_HOST_USER
    else "Student Community <webmaster@localhost>"
)

# Email Verification Token Expiration (24 hours)
EMAIL_VERIFY_MAX_AGE = 60 * 60 * 24

# Logging: send errors and the meeting reminder loop to the console so they
# show up in Render's log stream.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO"},
        "meetings": {"handlers": ["console"], "level": "INFO"},
    },
}

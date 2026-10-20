from django.conf import settings
from django.core import signing

_SALT = "accounts.email-verification"


def make_token(user):
    return signing.dumps({"uid": user.pk, "email": user.email}, salt=_SALT)


def read_token(token):
    """Return the payload dict, or None if invalid/expired."""
    try:
        return signing.loads(token, salt=_SALT, max_age=settings.EMAIL_VERIFY_MAX_AGE)
    except signing.BadSignature:  # SignatureExpired is a subclass
        return None

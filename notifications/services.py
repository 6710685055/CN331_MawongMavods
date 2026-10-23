from .models import Notification


def send_notification(
    *,
    recipient,
    title: str,
    message: str,
    notification_type: str = Notification.Type.GENERAL,
    actor=None,
    target_url: str = "",
) -> Notification:
    """Create an in-app notification for the recipient (<<include>> Send Notification)."""
    return Notification.objects.create(
        recipient=recipient,
        actor=actor,
        notification_type=notification_type,
        title=title,
        message=message,
        target_url=target_url,
    )

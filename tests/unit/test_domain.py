from uuid import uuid4

from notification_service.domain import (
    Channel,
    Notification,
    NotificationError,
    NotificationStatus,
    TemplateNotFound,
)


def test_channel_values():
    assert Channel.SMS.value == "sms"
    assert Channel.EMAIL.value == "email"


def test_status_values():
    assert {s.value for s in NotificationStatus} == {"pending", "sent", "failed"}


def test_template_not_found_is_notification_error():
    assert issubclass(TemplateNotFound, NotificationError)


def test_notification_defaults():
    n = Notification(
        id=uuid4(),
        channel=Channel.SMS,
        template_key="appointment_reminder",
        recipient="+15551234567",
        variables={"member_name": "Sam"},
        body="Hi Sam",
        status=NotificationStatus.PENDING,
    )
    assert n.subject is None
    assert n.provider_message_id is None
    assert n.sent_at is None

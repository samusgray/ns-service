import uuid

from notification_service.domain import Channel, Notification, NotificationStatus
from notification_service.repository import SqlNotificationRepository


def _make(status=NotificationStatus.SENT):
    return Notification(
        id=uuid.uuid4(),
        channel=Channel.SMS,
        template_key="appointment_reminder",
        recipient="+15551234567",
        variables={"member_name": "Sam"},
        body="Hi Sam",
        status=status,
        provider_message_id="stub-abc",
    )


def test_add_then_get_roundtrips(session):
    repo = SqlNotificationRepository(session)
    n = _make()
    saved = repo.add(n)
    assert saved.created_at is not None

    fetched = repo.get(n.id)
    assert fetched is not None
    assert fetched.channel == Channel.SMS
    assert fetched.status == NotificationStatus.SENT
    assert fetched.provider_message_id == "stub-abc"
    assert fetched.variables == {"member_name": "Sam"}


def test_get_unknown_returns_none(session):
    repo = SqlNotificationRepository(session)
    assert repo.get(uuid.uuid4()) is None

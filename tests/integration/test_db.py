import uuid

from notification_service.db import NotificationRow


def test_can_insert_and_read_notification_row(session):
    row = NotificationRow(
        id=uuid.uuid4(),
        template_key="appointment_reminder",
        channel="sms",
        recipient="+15551234567",
        variables={"member_name": "Sam"},
        body="Hi Sam",
        status="sent",
        provider_message_id="stub-abc",
    )
    session.add(row)
    session.commit()

    fetched = session.get(NotificationRow, row.id)
    assert fetched is not None
    assert fetched.channel == "sms"
    assert fetched.created_at is not None

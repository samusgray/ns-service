from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from .db import NotificationRow
from .domain import Channel, Notification, NotificationStatus


def _to_domain(row: NotificationRow) -> Notification:
    return Notification(
        id=row.id,
        channel=Channel(row.channel),
        template_key=row.template_key,
        recipient=row.recipient,
        variables=row.variables,
        body=row.body,
        status=NotificationStatus(row.status),
        subject=row.subject,
        provider_message_id=row.provider_message_id,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        sent_at=row.sent_at,
    )


class NotificationRepository(Protocol):
    def add(self, notification: Notification) -> Notification: ...
    def get(self, notification_id: UUID) -> Notification | None: ...


class SqlNotificationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, notification: Notification) -> Notification:
        row = NotificationRow(
            id=notification.id,
            template_key=notification.template_key,
            channel=notification.channel.value,
            recipient=notification.recipient,
            variables=notification.variables,
            subject=notification.subject,
            body=notification.body,
            status=notification.status.value,
            provider_message_id=notification.provider_message_id,
            error=notification.error,
            sent_at=notification.sent_at,
        )
        self._session.add(row)
        self._session.commit()
        self._session.refresh(row)
        return _to_domain(row)

    def get(self, notification_id: UUID) -> Notification | None:
        row = self._session.get(NotificationRow, notification_id)
        return _to_domain(row) if row is not None else None

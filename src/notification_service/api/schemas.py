from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from ..domain import Channel, Notification, NotificationStatus


class CreateNotificationRequest(BaseModel):
    channel: Channel
    template_key: str
    recipient: str
    variables: dict[str, str] = {}


class NotificationResponse(BaseModel):
    id: UUID
    channel: Channel
    template_key: str
    recipient: str
    status: NotificationStatus
    provider_message_id: str | None
    created_at: datetime | None
    sent_at: datetime | None

    @classmethod
    def from_domain(cls, n: Notification) -> "NotificationResponse":
        return cls(
            id=n.id,
            channel=n.channel,
            template_key=n.template_key,
            recipient=n.recipient,
            status=n.status,
            provider_message_id=n.provider_message_id,
            created_at=n.created_at,
            sent_at=n.sent_at,
        )

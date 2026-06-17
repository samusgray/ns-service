import enum
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class Channel(enum.StrEnum):
    SMS = "sms"
    EMAIL = "email"


class NotificationStatus(enum.StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class NotificationError(Exception):
    """Base class for domain errors."""


class TemplateNotFound(NotificationError):
    """No template file exists for the given channel/key."""


class InvalidVariables(NotificationError):
    """Supplied variables don't match the template's required variables."""


class SendError(NotificationError):
    """The provider failed to accept the message."""


@dataclass
class Notification:
    id: UUID
    channel: Channel
    template_key: str
    recipient: str
    variables: dict[str, str]
    body: str
    status: NotificationStatus
    subject: str | None = None
    provider_message_id: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    sent_at: datetime | None = None

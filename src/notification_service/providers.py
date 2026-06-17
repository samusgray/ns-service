import uuid
from typing import Protocol

from .domain import Channel


class NotificationSender(Protocol):
    def send(self, channel: Channel, recipient: str, subject: str | None, body: str) -> str: ...


class StubSender:
    """Pretends to send and returns a fake provider message id."""

    def send(self, channel: Channel, recipient: str, subject: str | None, body: str) -> str:
        return f"stub-{uuid.uuid4().hex[:12]}"

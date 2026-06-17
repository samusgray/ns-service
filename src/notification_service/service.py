from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from .domain import Channel, Notification, NotificationStatus, SendError
from .providers import NotificationSender
from .repository import NotificationRepository
from .templating import DEFAULT_TEMPLATES_DIR, load_template, render


class NotificationService:
    def __init__(
        self,
        repository: NotificationRepository,
        sender: NotificationSender,
        templates_dir: Path = DEFAULT_TEMPLATES_DIR,
    ) -> None:
        self._repository = repository
        self._sender = sender
        self._templates_dir = templates_dir

    def get(self, notification_id: UUID) -> Notification | None:
        return self._repository.get(notification_id)

    def send(
        self,
        channel: Channel,
        template_key: str,
        recipient: str,
        variables: dict[str, str],
    ) -> Notification:
        template = load_template(channel, template_key, self._templates_dir)
        subject, body = render(template, variables)

        notification = Notification(
            id=uuid4(),
            channel=channel,
            template_key=template_key,
            recipient=recipient,
            variables=variables,
            subject=subject,
            body=body,
            status=NotificationStatus.PENDING,
        )

        try:
            provider_message_id = self._sender.send(channel, recipient, subject, body)
        except SendError as exc:
            notification.status = NotificationStatus.FAILED
            notification.error = str(exc)
            return self._repository.add(notification)

        notification.status = NotificationStatus.SENT
        notification.provider_message_id = provider_message_id
        notification.sent_at = datetime.now(UTC)
        return self._repository.add(notification)

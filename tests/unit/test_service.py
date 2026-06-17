from pathlib import Path
from uuid import UUID

import pytest

from notification_service.domain import (
    Channel,
    InvalidVariables,
    Notification,
    NotificationStatus,
    SendError,
    TemplateNotFound,
)
from notification_service.service import NotificationService


class FakeRepo:
    def __init__(self):
        self.saved: list[Notification] = []

    def add(self, notification):
        self.saved.append(notification)
        return notification

    def get(self, notification_id):
        for n in self.saved:
            if n.id == notification_id:
                return n
        return None


class FakeSender:
    def __init__(self, pid="stub-123", raise_error=False):
        self.pid = pid
        self.raise_error = raise_error

    def send(self, channel, recipient, subject, body):
        if self.raise_error:
            raise SendError("boom")
        return self.pid


@pytest.fixture
def templates_dir(tmp_path) -> Path:
    d = tmp_path / "sms"
    d.mkdir(parents=True)
    (d / "appointment_reminder.yaml").write_text(
        'required_variables: [member_name]\nbody: "Hi {member_name}"\n'
    )
    return tmp_path


def test_send_success_persists_sent_notification(templates_dir):
    repo, sender = FakeRepo(), FakeSender(pid="stub-xyz")
    svc = NotificationService(repo, sender, templates_dir=templates_dir)

    result = svc.send(Channel.SMS, "appointment_reminder", "+1555", {"member_name": "Sam"})

    assert isinstance(result.id, UUID)
    assert result.status == NotificationStatus.SENT
    assert result.provider_message_id == "stub-xyz"
    assert result.body == "Hi Sam"
    assert result.sent_at is not None
    assert repo.saved == [result]


def test_send_unknown_template_raises(templates_dir):
    svc = NotificationService(FakeRepo(), FakeSender(), templates_dir=templates_dir)
    with pytest.raises(TemplateNotFound):
        svc.send(Channel.SMS, "nope", "+1555", {})


def test_send_bad_variables_raises(templates_dir):
    svc = NotificationService(FakeRepo(), FakeSender(), templates_dir=templates_dir)
    with pytest.raises(InvalidVariables):
        svc.send(Channel.SMS, "appointment_reminder", "+1555", {})


def test_send_provider_failure_persists_failed(templates_dir):
    repo = FakeRepo()
    svc = NotificationService(repo, FakeSender(raise_error=True), templates_dir=templates_dir)

    result = svc.send(Channel.SMS, "appointment_reminder", "+1555", {"member_name": "Sam"})

    assert result.status == NotificationStatus.FAILED
    assert result.error == "boom"
    assert result.provider_message_id is None
    assert repo.saved == [result]

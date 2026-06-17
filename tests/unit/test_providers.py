from notification_service.domain import Channel
from notification_service.providers import StubSender


def test_stub_sender_returns_provider_id():
    pid = StubSender().send(Channel.SMS, "+15551234567", None, "Hi Sam")
    assert pid.startswith("stub-")
    assert len(pid) == len("stub-") + 12


def test_stub_sender_ids_are_unique():
    sender = StubSender()
    a = sender.send(Channel.SMS, "+1", None, "a")
    b = sender.send(Channel.SMS, "+1", None, "b")
    assert a != b

import uuid

from fastapi.testclient import TestClient

from notification_service.api.app import app
from notification_service.api.dependencies import get_session


def _client(session):
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def test_post_creates_and_get_reads_back(session):
    client = _client(session)
    try:
        resp = client.post(
            "/notifications",
            json={
                "channel": "sms",
                "template_key": "appointment_reminder",
                "recipient": "+15551234567",
                "variables": {
                    "member_name": "Sam",
                    "appointment_location": "Austin Clinic",
                },
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "sent"
        assert body["provider_message_id"].startswith("stub-")
        notification_id = body["id"]

        got = client.get(f"/notifications/{notification_id}")
        assert got.status_code == 200
        assert got.json()["id"] == notification_id
    finally:
        app.dependency_overrides.clear()


def test_post_unknown_template_returns_422(session):
    client = _client(session)
    try:
        resp = client.post(
            "/notifications",
            json={"channel": "sms", "template_key": "nope", "recipient": "+1", "variables": {}},
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_post_missing_variable_returns_422(session):
    client = _client(session)
    try:
        resp = client.post(
            "/notifications",
            json={
                "channel": "sms",
                "template_key": "appointment_reminder",
                "recipient": "+1",
                "variables": {"member_name": "Sam"},
            },
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_get_unknown_id_returns_404(session):
    client = _client(session)
    try:
        resp = client.get(f"/notifications/{uuid.uuid4()}")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()

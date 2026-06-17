from fastapi.testclient import TestClient

from notification_service.api.app import app
from notification_service.api.dependencies import get_session


def test_health_ok(session):
    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
    finally:
        app.dependency_overrides.clear()

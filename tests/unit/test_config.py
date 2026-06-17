from notification_service.config import Settings


def test_settings_reads_database_url_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    settings = Settings()
    assert settings.database_url == "postgresql+psycopg://u:p@localhost/db"

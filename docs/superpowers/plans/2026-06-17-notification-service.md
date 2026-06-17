# Notification Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up an internal HTTP service that renders in-repo templates and records SMS/email notifications in Postgres, with delivery stubbed — delivering a runnable `/health` then a full `POST /notifications` → `GET /notifications/{id}` vertical slice.

**Architecture:** Layered, transport-agnostic core. FastAPI (transport) → `NotificationService` (orchestration) → templating + stub provider + Postgres repository. Templates are YAML files under `templates/{channel}/{key}.yaml`; the directory encodes the channel. Synchronous SQLAlchemy throughout (async deferred).

**Tech Stack:** Python ≥3.12, uv, FastAPI, SQLAlchemy 2.x (sync) + psycopg, Alembic, pydantic-settings, PyYAML, pytest (+pytest-cov, httpx), Ruff, ty.

## Global Constraints

- **Always `uv run …`** — never bare `python`/`pytest`/`ruff`/`ty`. All deps via `uv add` / `uv add --dev`; config in `pyproject.toml`. Commit `uv.lock`.
- **Python:** `>=3.12`.
- **TDD:** failing test first → watch it fail → minimal code → refactor. One logical change per commit (Conventional Commits).
- **Layering:** the service core (`service.py`, `templating.py`, `providers.py`, `domain.py`) must not import FastAPI or SQLAlchemy session/request types beyond what the repository abstraction needs. Only `api/app.py` knows HTTP.
- **Package layout:** src layout, import root `notification_service` (`src/notification_service/…`).
- **Channels** are exactly `sms` and `email`; **statuses** exactly `pending`, `sent`, `failed` (verbatim strings, lower-case).
- **No recipient-format validation** in this plan (deferred). Recipient is stored as supplied.
- **Postgres prerequisite:** a local Postgres must be reachable for DB tasks. If you don't have one: `docker run --rm -d --name pg-notif -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16`. Test DB and dev DB are separate databases; never touch dev/prod data.
- **Connection URLs (used by manual verification):**
  - Dev: `postgresql+psycopg://postgres:postgres@localhost:5432/notification_service`
  - Test: `postgresql+psycopg://postgres:postgres@localhost:5432/notification_service_test`

---

### Task 1: Project scaffold + configuration

**Files:**
- Create: `pyproject.toml` (via `uv init`), `src/notification_service/__init__.py`, `src/notification_service/config.py`
- Create: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/unit/test_config.py`
- Create: `.env.example`

**Interfaces:**
- Produces: `notification_service.config.Settings` (pydantic-settings) with field `database_url: str`; `get_settings() -> Settings` (cached).

- [ ] **Step 1: Initialise the uv project (src layout) and add deps**

```bash
cd /Users/sg/code/curative
uv init --package --name notification-service --python 3.12 .
uv add fastapi "uvicorn[standard]" sqlalchemy "psycopg[binary]" alembic pydantic-settings pyyaml
uv add --dev pytest pytest-cov httpx
uv add --dev ruff ty
```
Then add tool config to `pyproject.toml`:
```toml
[tool.pytest.ini_options]
addopts = "--cov=notification_service --cov-report=term-missing"
testpaths = ["tests"]

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 2: Write the failing test**

`tests/unit/test_config.py`:
```python
from notification_service.config import Settings


def test_settings_reads_database_url_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    settings = Settings()
    assert settings.database_url == "postgresql+psycopg://u:p@localhost/db"
```

- [ ] **Step 3: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_config.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'notification_service.config'`.

- [ ] **Step 4: Implement `config.py`**

`src/notification_service/config.py`:
```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str  # ty: ignore[missing-argument]  # populated from env / .env


@lru_cache
def get_settings() -> Settings:
    return Settings()  # ty: ignore[missing-argument]  # env-populated
```
Create `.env.example`:
```
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/notification_service
```

- [ ] **Step 5: Run it and watch it pass**

Run: `uv run pytest tests/unit/test_config.py -v --no-cov`
Expected: PASS (1 passed).

- [ ] **Step 6: Manual Verification**

Run:
```bash
uv run python -c "import os; os.environ['DATABASE_URL']='x'; from notification_service.config import Settings; print(Settings().database_url)"
uv run ruff check .
```
Expected: prints `x`, and `ruff check` reports `All checks passed!`.

- [ ] **Step 7: Commit**

```bash
git checkout -b feat/notification-service
git add -A
git commit -m "chore: scaffold uv project and settings"
```

---

### Task 2: Domain models and errors

**Files:**
- Create: `src/notification_service/domain.py`
- Create: `tests/unit/test_domain.py`

**Interfaces:**
- Produces:
  - `Channel(str, Enum)`: `SMS = "sms"`, `EMAIL = "email"`.
  - `NotificationStatus(str, Enum)`: `PENDING = "pending"`, `SENT = "sent"`, `FAILED = "failed"`.
  - Exceptions: `NotificationError(Exception)`, `TemplateNotFound(NotificationError)`, `InvalidVariables(NotificationError)`, `SendError(NotificationError)`.
  - `@dataclass Notification` with fields: `id: UUID`, `channel: Channel`, `template_key: str`, `recipient: str`, `variables: dict[str, str]`, `body: str`, `status: NotificationStatus`, `subject: str | None = None`, `provider_message_id: str | None = None`, `error: str | None = None`, `created_at: datetime | None = None`, `updated_at: datetime | None = None`, `sent_at: datetime | None = None`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_domain.py`:
```python
from uuid import uuid4

from notification_service.domain import (
    Channel,
    Notification,
    NotificationStatus,
    TemplateNotFound,
    NotificationError,
)


def test_channel_values():
    assert Channel.SMS.value == "sms"
    assert Channel.EMAIL.value == "email"


def test_status_values():
    assert {s.value for s in NotificationStatus} == {"pending", "sent", "failed"}


def test_template_not_found_is_notification_error():
    assert issubclass(TemplateNotFound, NotificationError)


def test_notification_defaults():
    n = Notification(
        id=uuid4(),
        channel=Channel.SMS,
        template_key="appointment_reminder",
        recipient="+15551234567",
        variables={"member_name": "Sam"},
        body="Hi Sam",
        status=NotificationStatus.PENDING,
    )
    assert n.subject is None
    assert n.provider_message_id is None
    assert n.sent_at is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_domain.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'notification_service.domain'`.

- [ ] **Step 3: Implement `domain.py`**

`src/notification_service/domain.py`:
```python
import enum
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class Channel(str, enum.Enum):
    SMS = "sms"
    EMAIL = "email"


class NotificationStatus(str, enum.Enum):
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
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest tests/unit/test_domain.py -v --no-cov`
Expected: PASS (4 passed).

- [ ] **Step 5: Manual Verification**

Run:
```bash
uv run python -c "from notification_service.domain import Channel, NotificationStatus; print([c.value for c in Channel], [s.value for s in NotificationStatus])"
```
Expected: `['sms', 'email'] ['pending', 'sent', 'failed']`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add domain models and errors"
```

---

### Task 3: Templating engine (load + strict render) and first template

**Files:**
- Create: `src/notification_service/templating.py`
- Create: `templates/sms/appointment_reminder.yaml`
- Create: `tests/unit/test_templating.py`

**Interfaces:**
- Consumes: `Channel`, `TemplateNotFound`, `InvalidVariables` from `domain`.
- Produces:
  - `@dataclass(frozen=True) Template`: `channel: Channel`, `key: str`, `body: str`, `required_variables: list[str]`, `subject: str | None = None`.
  - `DEFAULT_TEMPLATES_DIR: Path` (repo-root `templates/`).
  - `load_template(channel: Channel, key: str, templates_dir: Path = DEFAULT_TEMPLATES_DIR) -> Template` — raises `TemplateNotFound`.
  - `render(template: Template, variables: dict[str, str]) -> tuple[str | None, str]` — returns `(subject, body)`; raises `InvalidVariables` on any missing or unexpected variable.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_templating.py`:
```python
import textwrap

import pytest

from notification_service.domain import Channel, InvalidVariables, TemplateNotFound
from notification_service.templating import Template, load_template, render


def _write(tmp_path, channel, key, content):
    d = tmp_path / channel
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{key}.yaml").write_text(textwrap.dedent(content))
    return tmp_path


def test_load_sms_template(tmp_path):
    root = _write(
        tmp_path,
        "sms",
        "appointment_reminder",
        """
        required_variables: [member_name, appointment_location]
        body: "Hi {member_name}, your appointment is at {appointment_location}."
        """,
    )
    t = load_template(Channel.SMS, "appointment_reminder", root)
    assert t.required_variables == ["member_name", "appointment_location"]
    assert t.subject is None


def test_load_missing_template_raises(tmp_path):
    with pytest.raises(TemplateNotFound):
        load_template(Channel.SMS, "nope", tmp_path)


def test_render_substitutes_variables():
    t = Template(
        channel=Channel.SMS,
        key="appointment_reminder",
        body="Hi {member_name}, see you at {appointment_location}.",
        required_variables=["member_name", "appointment_location"],
    )
    subject, body = render(t, {"member_name": "Sam", "appointment_location": "Austin"})
    assert subject is None
    assert body == "Hi Sam, see you at Austin."


def test_render_missing_variable_raises():
    t = Template(channel=Channel.SMS, key="k", body="Hi {member_name}", required_variables=["member_name"])
    with pytest.raises(InvalidVariables):
        render(t, {})


def test_render_unexpected_variable_raises():
    t = Template(channel=Channel.SMS, key="k", body="Hi {member_name}", required_variables=["member_name"])
    with pytest.raises(InvalidVariables):
        render(t, {"member_name": "Sam", "extra": "x"})


def test_render_email_subject():
    t = Template(
        channel=Channel.EMAIL,
        key="k",
        body="Body for {name}",
        required_variables=["name"],
        subject="Hello {name}",
    )
    subject, body = render(t, {"name": "Sam"})
    assert subject == "Hello Sam"
    assert body == "Body for Sam"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_templating.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'notification_service.templating'`.

- [ ] **Step 3: Implement `templating.py` and the template file**

`src/notification_service/templating.py`:
```python
from dataclasses import dataclass
from pathlib import Path

import yaml

from .domain import Channel, InvalidVariables, TemplateNotFound

DEFAULT_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"


@dataclass(frozen=True)
class Template:
    channel: Channel
    key: str
    body: str
    required_variables: list[str]
    subject: str | None = None


def load_template(
    channel: Channel, key: str, templates_dir: Path = DEFAULT_TEMPLATES_DIR
) -> Template:
    path = templates_dir / channel.value / f"{key}.yaml"
    if not path.is_file():
        raise TemplateNotFound(f"no template '{key}' for channel '{channel.value}'")
    data = yaml.safe_load(path.read_text()) or {}
    return Template(
        channel=channel,
        key=key,
        body=data["body"],
        required_variables=list(data.get("required_variables", [])),
        subject=data.get("subject"),
    )


def render(template: Template, variables: dict[str, str]) -> tuple[str | None, str]:
    provided = set(variables)
    required = set(template.required_variables)
    missing = required - provided
    unexpected = provided - required
    if missing:
        raise InvalidVariables(f"missing variables: {sorted(missing)}")
    if unexpected:
        raise InvalidVariables(f"unexpected variables: {sorted(unexpected)}")
    body = template.body.format(**variables)
    subject = template.subject.format(**variables) if template.subject else None
    return subject, body
```
`templates/sms/appointment_reminder.yaml`:
```yaml
required_variables: [member_name, appointment_location]
body: "Hi {member_name}, this is a reminder of your appointment at {appointment_location}."
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest tests/unit/test_templating.py -v --no-cov`
Expected: PASS (6 passed).

- [ ] **Step 5: Manual Verification**

Run:
```bash
uv run python -c "from notification_service.domain import Channel; from notification_service.templating import load_template, render; t=load_template(Channel.SMS,'appointment_reminder'); print(render(t, {'member_name':'Sam','appointment_location':'Austin Clinic'}))"
```
Expected: `(None, 'Hi Sam, this is a reminder of your appointment at Austin Clinic.')`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add templating engine and appointment_reminder template"
```

---

### Task 4: Provider port and stub sender

**Files:**
- Create: `src/notification_service/providers.py`
- Create: `tests/unit/test_providers.py`

**Interfaces:**
- Consumes: `Channel` from `domain`.
- Produces:
  - `NotificationSender(Protocol)` with `send(self, channel: Channel, recipient: str, subject: str | None, body: str) -> str`.
  - `StubSender` implementing it; returns a provider message id of the form `stub-<12 hex chars>`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_providers.py`:
```python
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
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_providers.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'notification_service.providers'`.

- [ ] **Step 3: Implement `providers.py`**

`src/notification_service/providers.py`:
```python
import uuid
from typing import Protocol

from .domain import Channel


class NotificationSender(Protocol):
    def send(self, channel: Channel, recipient: str, subject: str | None, body: str) -> str: ...


class StubSender:
    """Pretends to send and returns a fake provider message id."""

    def send(self, channel: Channel, recipient: str, subject: str | None, body: str) -> str:
        return f"stub-{uuid.uuid4().hex[:12]}"
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest tests/unit/test_providers.py -v --no-cov`
Expected: PASS (2 passed).

- [ ] **Step 5: Manual Verification**

Run:
```bash
uv run python -c "from notification_service.domain import Channel; from notification_service.providers import StubSender; print(StubSender().send(Channel.SMS,'+1',None,'hi'))"
```
Expected: a value like `stub-1a2b3c4d5e6f`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add notification sender port and stub implementation"
```

---

### Task 5: Database engine, ORM model, and Alembic migration

**Files:**
- Create: `src/notification_service/db.py`
- Create: `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/0001_create_notifications.py`
- Create: `tests/integration/__init__.py`, `tests/integration/conftest.py`, `tests/integration/test_db.py`

**Interfaces:**
- Consumes: `get_settings` from `config`.
- Produces:
  - `Base` (SQLAlchemy `DeclarativeBase`).
  - `NotificationRow` ORM model mapped to table `notifications` (columns per the spec data model; CHECK constraints `ck_notifications_channel`, `ck_notifications_status`).
  - `make_engine(database_url: str) -> Engine`.
  - `make_session_factory(engine: Engine) -> sessionmaker[Session]`.

- [ ] **Step 1: Write the failing test**

`tests/integration/conftest.py`:
```python
import os

import pytest
from sqlalchemy import text

from notification_service.db import Base, make_engine, make_session_factory

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/notification_service_test",
)


@pytest.fixture(scope="session")
def engine():
    eng = make_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    factory = make_session_factory(engine)
    s = factory()
    s.execute(text("TRUNCATE notifications"))
    s.commit()
    try:
        yield s
    finally:
        s.close()
```
`tests/integration/test_db.py`:
```python
import uuid

from notification_service.db import NotificationRow


def test_can_insert_and_read_notification_row(session):
    row = NotificationRow(
        id=uuid.uuid4(),
        template_key="appointment_reminder",
        channel="sms",
        recipient="+15551234567",
        variables={"member_name": "Sam"},
        body="Hi Sam",
        status="sent",
        provider_message_id="stub-abc",
    )
    session.add(row)
    session.commit()

    fetched = session.get(NotificationRow, row.id)
    assert fetched is not None
    assert fetched.channel == "sms"
    assert fetched.created_at is not None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/integration/test_db.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'notification_service.db'`.

- [ ] **Step 3: Implement `db.py`**

`src/notification_service/db.py`:
```python
import datetime
import uuid

from sqlalchemy import CheckConstraint, DateTime, Engine, Text, create_engine, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class NotificationRow(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    template_key: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    recipient: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("channel in ('sms', 'email')", name="ck_notifications_channel"),
        CheckConstraint(
            "status in ('pending', 'sent', 'failed')", name="ck_notifications_status"
        ),
    )


def make_engine(database_url: str) -> Engine:
    return create_engine(database_url, future=True)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
```

- [ ] **Step 4: Run it and watch it pass**

First ensure the test DB exists:
```bash
createdb -h localhost -U postgres notification_service_test 2>/dev/null || PGPASSWORD=postgres psql -h localhost -U postgres -c "CREATE DATABASE notification_service_test" 2>/dev/null || true
```
Run: `uv run pytest tests/integration/test_db.py -v --no-cov`
Expected: PASS (1 passed). (The session fixture creates tables from `Base.metadata`.)

- [ ] **Step 5: Add the Alembic migration (production schema path)**

Initialise Alembic (creates `alembic.ini`, `migrations/`):
```bash
uv run alembic init migrations
```
In `migrations/env.py`, wire the URL and metadata — replace the `run_migrations_offline/online` URL handling so it uses our settings and `Base.metadata`:
```python
# near the top of migrations/env.py, after `config = context.config`
from notification_service.config import get_settings
from notification_service.db import Base

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata
```
Create `migrations/versions/0001_create_notifications.py`:
```python
"""create notifications table"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("template_key", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("recipient", sa.Text(), nullable=False),
        sa.Column("variables", postgresql.JSONB(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("channel in ('sms', 'email')", name="ck_notifications_channel"),
        sa.CheckConstraint("status in ('pending', 'sent', 'failed')", name="ck_notifications_status"),
    )


def downgrade() -> None:
    op.drop_table("notifications")
```

- [ ] **Step 6: Manual Verification**

Create the dev DB and run the migration against it:
```bash
PGPASSWORD=postgres psql -h localhost -U postgres -c "CREATE DATABASE notification_service" 2>/dev/null || true
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/notification_service uv run alembic upgrade head
PGPASSWORD=postgres psql -h localhost -U postgres -d notification_service -c "\d notifications"
```
Expected: `alembic` prints `Running upgrade  -> 0001, create notifications table`, and `\d notifications` lists all 13 columns plus the two check constraints.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: add notifications table, ORM model, and migration"
```

---

### Task 6: `/health` endpoint (first runnable app — end of Milestone 1)

**Files:**
- Create: `src/notification_service/api/__init__.py`, `src/notification_service/api/app.py`
- Create: `src/notification_service/api/dependencies.py`
- Create: `tests/integration/test_health.py`

**Interfaces:**
- Consumes: `get_settings`, `make_engine`, `make_session_factory`.
- Produces:
  - `notification_service.api.dependencies`: module-level `engine`, `SessionFactory`, and `get_session()` generator dependency yielding a `Session`.
  - `notification_service.api.app.create_app() -> FastAPI` and module-level `app = create_app()`.
  - `GET /health` → `200 {"status": "ok"}` when `SELECT 1` succeeds, else `503 {"status": "unavailable"}`.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_health.py`:
```python
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
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/integration/test_health.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'notification_service.api'`.

- [ ] **Step 3: Implement the dependencies and app**

`src/notification_service/api/dependencies.py`:
```python
from collections.abc import Iterator

from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import make_engine, make_session_factory

engine = make_engine(get_settings().database_url)
SessionFactory = make_session_factory(engine)


def get_session() -> Iterator[Session]:
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()
```
`src/notification_service/api/app.py`:
```python
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .dependencies import get_session


def create_app() -> FastAPI:
    app = FastAPI(title="notification-service")

    @app.get("/health")
    def health(session: Session = Depends(get_session)) -> JSONResponse:
        try:
            session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return JSONResponse(status_code=200, content={"status": "ok"})

    return app


app = create_app()
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest tests/integration/test_health.py -v --no-cov`
Expected: PASS (1 passed).

- [ ] **Step 5: Manual Verification (run the real app)**

In one terminal:
```bash
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/notification_service uv run uvicorn notification_service.api.app:app --port 8000
```
In another:
```bash
curl -s localhost:8000/health
```
Expected: `{"status":"ok"}`. (Stop the server with Ctrl-C afterwards.)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add /health endpoint and FastAPI app"
```

---

### Task 7: Notification repository (Postgres)

**Files:**
- Create: `src/notification_service/repository.py`
- Create: `tests/integration/test_repository.py`

**Interfaces:**
- Consumes: `Notification`, `Channel`, `NotificationStatus` from `domain`; `NotificationRow` from `db`; `Session`.
- Produces:
  - `NotificationRepository(Protocol)`: `add(self, notification: Notification) -> Notification`, `get(self, notification_id: UUID) -> Notification | None`.
  - `SqlNotificationRepository(session: Session)` implementing it. `add` persists and returns the domain object with DB-populated `created_at`/`updated_at`; `get` returns the domain object or `None`.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_repository.py`:
```python
import uuid

from notification_service.domain import Channel, Notification, NotificationStatus
from notification_service.repository import SqlNotificationRepository


def _make(status=NotificationStatus.SENT):
    return Notification(
        id=uuid.uuid4(),
        channel=Channel.SMS,
        template_key="appointment_reminder",
        recipient="+15551234567",
        variables={"member_name": "Sam"},
        body="Hi Sam",
        status=status,
        provider_message_id="stub-abc",
    )


def test_add_then_get_roundtrips(session):
    repo = SqlNotificationRepository(session)
    n = _make()
    saved = repo.add(n)
    assert saved.created_at is not None

    fetched = repo.get(n.id)
    assert fetched is not None
    assert fetched.channel == Channel.SMS
    assert fetched.status == NotificationStatus.SENT
    assert fetched.provider_message_id == "stub-abc"
    assert fetched.variables == {"member_name": "Sam"}


def test_get_unknown_returns_none(session):
    repo = SqlNotificationRepository(session)
    assert repo.get(uuid.uuid4()) is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/integration/test_repository.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'notification_service.repository'`.

- [ ] **Step 3: Implement `repository.py`**

`src/notification_service/repository.py`:
```python
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
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest tests/integration/test_repository.py -v --no-cov`
Expected: PASS (2 passed).

- [ ] **Step 5: Manual Verification**

Run: `uv run pytest tests/integration -v --no-cov`
Expected: all integration tests pass (db + health + repository).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add Postgres notification repository"
```

---

### Task 8: NotificationService orchestration

**Files:**
- Create: `src/notification_service/service.py`
- Create: `tests/unit/test_service.py`

**Interfaces:**
- Consumes: `load_template`, `render`, `DEFAULT_TEMPLATES_DIR` from `templating`; `NotificationSender` from `providers`; `NotificationRepository` from `repository`; domain models/errors.
- Produces:
  - `NotificationService(repository: NotificationRepository, sender: NotificationSender, templates_dir: Path = DEFAULT_TEMPLATES_DIR)`.
  - `get(self, notification_id: UUID) -> Notification | None` — passthrough to `repository.get` (used by the GET endpoint in Task 9).
  - `send(self, channel: Channel, template_key: str, recipient: str, variables: dict[str, str]) -> Notification`. Flow: load template (`TemplateNotFound` propagates) → render (`InvalidVariables` propagates) → build `Notification(status=PENDING)` → call sender; on success set `status=SENT`, `provider_message_id`, `sent_at=now(UTC)`; on `SendError` set `status=FAILED`, `error`; persist once via `repository.add` and return the result. (Single terminal-state write — an intentional simplification of the spec's transient `pending` row, valid because the stub sends synchronously in-process.)

- [ ] **Step 1: Write the failing test**

`tests/unit/test_service.py`:
```python
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
        "required_variables: [member_name]\nbody: \"Hi {member_name}\"\n"
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
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/unit/test_service.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'notification_service.service'`.

- [ ] **Step 3: Implement `service.py`**

`src/notification_service/service.py`:
```python
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
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest tests/unit/test_service.py -v --no-cov`
Expected: PASS (4 passed).

- [ ] **Step 5: Manual Verification**

Run: `uv run pytest tests/unit -v --no-cov`
Expected: all unit tests pass (config, domain, templating, providers, service).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add NotificationService orchestration"
```

---

### Task 9: `POST /notifications` + `GET /notifications/{id}` (Milestone 2 complete)

**Files:**
- Create: `src/notification_service/api/schemas.py`
- Modify: `src/notification_service/api/dependencies.py` (add `get_service`)
- Modify: `src/notification_service/api/app.py` (add routes + error handlers)
- Create: `tests/integration/test_notifications_api.py`

**Interfaces:**
- Consumes: `NotificationService`, `SqlNotificationRepository`, `StubSender`, `get_session`, domain errors.
- Produces:
  - `schemas.CreateNotificationRequest`: `channel: Channel`, `template_key: str`, `recipient: str`, `variables: dict[str, str] = {}`.
  - `schemas.NotificationResponse` with `from_domain(n: Notification) -> NotificationResponse`; fields `id, channel, template_key, recipient, status, provider_message_id, created_at, sent_at`.
  - `dependencies.get_service(session=Depends(get_session)) -> NotificationService`.
  - `POST /notifications` → `201 NotificationResponse`; `TemplateNotFound`/`InvalidVariables` → `422 {"detail": <msg>}`.
  - `GET /notifications/{notification_id}` → `200 NotificationResponse` or `404`.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_notifications_api.py`:
```python
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
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/integration/test_notifications_api.py -v --no-cov`
Expected: FAIL — `404` on `POST /notifications` (route not defined) so the first assertion fails.

- [ ] **Step 3: Implement schemas, `get_service`, routes, and error handlers**

`src/notification_service/api/schemas.py`:
```python
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
```
Append to `src/notification_service/api/dependencies.py`:
```python
from fastapi import Depends  # add to imports

from ..providers import StubSender
from ..repository import SqlNotificationRepository
from ..service import NotificationService


def get_service(session: Session = Depends(get_session)) -> NotificationService:
    return NotificationService(SqlNotificationRepository(session), StubSender())
```
Replace `src/notification_service/api/app.py` with routes + handlers:
```python
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..domain import InvalidVariables, NotificationError, TemplateNotFound
from .dependencies import get_service, get_session
from .schemas import CreateNotificationRequest, NotificationResponse
from ..service import NotificationService


def create_app() -> FastAPI:
    app = FastAPI(title="notification-service")

    @app.exception_handler(TemplateNotFound)
    @app.exception_handler(InvalidVariables)
    async def _domain_422(request, exc: NotificationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/health")
    def health(session: Session = Depends(get_session)) -> JSONResponse:
        try:
            session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return JSONResponse(status_code=200, content={"status": "ok"})

    @app.post("/notifications", response_model=NotificationResponse, status_code=201)
    def create_notification(
        payload: CreateNotificationRequest,
        service: NotificationService = Depends(get_service),
    ) -> NotificationResponse:
        notification = service.send(
            payload.channel, payload.template_key, payload.recipient, payload.variables
        )
        return NotificationResponse.from_domain(notification)

    @app.get("/notifications/{notification_id}", response_model=NotificationResponse)
    def get_notification(
        notification_id: UUID,
        service: NotificationService = Depends(get_service),
    ) -> NotificationResponse:
        notification = service.get(notification_id)
        if notification is None:
            raise HTTPException(status_code=404, detail="notification not found")
        return NotificationResponse.from_domain(notification)

    return app


app = create_app()
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest tests/integration/test_notifications_api.py -v --no-cov`
Expected: PASS (4 passed).

- [ ] **Step 5: Manual Verification (full end-to-end against Postgres)**

Start the app:
```bash
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/notification_service uv run uvicorn notification_service.api.app:app --port 8000
```
Then:
```bash
curl -s -X POST localhost:8000/notifications \
  -H 'content-type: application/json' \
  -d '{"channel":"sms","template_key":"appointment_reminder","recipient":"+15551234567","variables":{"member_name":"Sam","appointment_location":"Austin Clinic"}}'
```
Expected: `201`-status JSON with `"status":"sent"`, a `"provider_message_id":"stub-…"`, and an `"id"`. Copy that `id`, then:
```bash
curl -s localhost:8000/notifications/<paste-id-here>
```
Expected: the same record echoed back. Confirm persistence:
```bash
PGPASSWORD=postgres psql -h localhost -U postgres -d notification_service -c "select channel, template_key, status, provider_message_id from notifications;"
```
Expected: one row with `sms | appointment_reminder | sent | stub-…`.

- [ ] **Step 6: Run full gates and commit**

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check
```
Expected: tests pass with coverage reported; ruff/format/ty clean (fix any findings before committing).
```bash
git add -A
git commit -m "feat: add POST and GET notifications endpoints"
```

---

## Future work (not in this plan)

- Recipient format validation (email shape, SMS E.164) → `422`.
- Real provider adapter (Mailgun/SendGrid) behind `NotificationSender`.
- Async I/O (async SQLAlchemy + async endpoints).
- More templates and the email channel end-to-end.
- Pre-commit hook wiring (ruff + ty + fast unit tests).

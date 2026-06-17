# Notification Service — Design

**Date:** 2026-06-17
**Status:** Approved (pending spec review)

## Purpose

An internal HTTP service that other microservices call to send SMS and email
notifications. This repo owns the **templates** that are the source of truth for all
outgoing notifications. Actual delivery is **stubbed** for now: when the service would
send, it pretends to and returns a provider message id (a real Mailgun/SendGrid adapter
comes later behind the same interface).

## Scope

### In scope (now)
- Template-driven SMS and email notifications, templates authored as files in this repo.
- HTTP/JSON transport via FastAPI.
- Persistence of every notification (request + outcome) in Postgres.
- Stubbed provider that returns a fake provider message id.
- Endpoints: `POST /notifications`, `GET /notifications/{id}`, `GET /health`.

### Out of scope (now) — documented for later
- **Recipient format validation** (email shape, SMS E.164). Important, but added after we
  have working software. Until then, the recipient is stored as supplied.
- Real provider integration (Mailgun/SendGrid).
- Async I/O. We start **synchronous** (SQLAlchemy + FastAPI); async can come later.
- A second transport (e.g. gRPC). The service layer is kept transport-agnostic so this is
  *possible* later, but no gRPC scaffolding is built now.

## Transport decision: HTTP/JSON (FastAPI)

Chosen over gRPC for this internal service: trivial manual verification (`curl`), zero
caller setup, and a typed contract via Pydantic/OpenAPI. The throughput/streaming
advantages of gRPC are not what this service is bottlenecked on. The service core is
transport-agnostic, so a gRPC adapter could be added later without touching the core.

## Templates

- Authored as **YAML** files, one per template, organized by channel:
  ```
  templates/
    sms/
      appointment_reminder.yaml      # required_variables, body
      password_reset.yaml
    email/
      appointment_reminder.yaml      # required_variables, subject, body
      provider_office_notice.yaml
  ```
- Lookup path = `templates/{channel}/{template_key}.yaml`. The **directory encodes the
  channel** — the service never introspects a template to learn its type.
- A template file declares only its content fields:
  - SMS: `required_variables` (list), `body` (string with `{placeholder}` slots)
  - Email: `required_variables` (list), `subject` (string), `body` (string)
- **Rendering** does plain `{placeholder}` substitution and is **strict**: it errors if any
  required variable is missing, or if an unexpected variable is supplied.

## API

### `POST /notifications` — create + send
Request:
```json
{
  "channel": "sms",
  "template_key": "appointment_reminder",
  "recipient": "+15551234567",
  "variables": { "member_name": "Sam", "appointment_location": "Curative Clinic, Austin" }
}
```
`channel` is **explicit** at the call site (clearer for readers; the service does not infer
channel from the template).

`201` response — the stored notification record:
```json
{
  "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "channel": "sms",
  "template_key": "appointment_reminder",
  "recipient": "+15551234567",
  "status": "sent",
  "provider_message_id": "stub-abc123",
  "created_at": "2026-06-17T18:00:00Z",
  "sent_at": "2026-06-17T18:00:00Z"
}
```

### `GET /notifications/{id}` — read one
`200` with the record, `404` if the id is unknown.

### `GET /health` — liveness
Checks DB connectivity. `200 {"status": "ok"}`, or `503` if the DB is unreachable.

### Error mapping
- `422 Unprocessable Entity`: unknown `template_key` for the given channel; missing or
  unexpected `variables`.
- `404 Not Found`: `GET /notifications/{id}` for an unknown id.
- `503 Service Unavailable`: `/health` when the DB is unreachable.
- (Recipient-format `422` is deferred — see Out of scope.)

## Data model

Single table; templates stay file-based (no templates table).

### `notifications`
| column | type | notes |
|---|---|---|
| `id` | `uuid` PK | app-generated (uuid4) |
| `template_key` | `text` not null | which template was used |
| `channel` | `text` not null | `'sms'` \| `'email'`; CHECK constraint + Python enum |
| `recipient` | `text` not null | phone number or email |
| `variables` | `jsonb` not null | input variable values (audit / reproduction) |
| `subject` | `text` null | rendered subject; email only |
| `body` | `text` not null | rendered body that was "sent" |
| `status` | `text` not null | `'pending'` \| `'sent'` \| `'failed'`; CHECK + Python enum |
| `provider_message_id` | `text` null | id returned by the stub provider; null until sent |
| `error` | `text` null | failure reason when `status='failed'` |
| `created_at` | `timestamptz` not null default `now()` | |
| `updated_at` | `timestamptz` not null default `now()` | bump on status change |
| `sent_at` | `timestamptz` null | set when status → `sent` |

`status` models the real lifecycle (`pending → sent/failed`) even though the stub always
succeeds, so the column is future-proof for a real/async sender.

## Architecture (layered, service core transport-agnostic)

- **Transport — FastAPI** (`api/`): routers + Pydantic request/response schemas; maps
  domain errors → HTTP status codes. The only layer that knows about HTTP.
- **Service** (`services/`): `NotificationService.send(channel, template_key, recipient,
  variables)` orchestrates the flow and returns a domain object. Knows nothing about HTTP
  or SQL.
- **Templates** (`templates_engine/`): loads `templates/{channel}/{key}.yaml`, parses to a
  `Template`, and `render()`s it strictly.
- **Provider port** (`providers/`): `NotificationSender` interface + `StubSender`
  returning a fake `provider_message_id`.
- **Persistence** (`db/`, `repositories/`): `NotificationRepository` port + Postgres
  implementation (SQLAlchemy + Alembic migration).
- **Domain** (`domain/`): models + typed errors (`TemplateNotFound`, `InvalidVariables`,
  …). **Config** via pydantic-settings (DB URL).

### Data flow for `POST /notifications`
1. FastAPI validates request shape (Pydantic): `channel` enum, non-empty `template_key`,
   `recipient`, `variables` dict.
2. Router calls `NotificationService.send(...)`.
3. Load template for `(channel, template_key)` → `TemplateNotFound` → `422`.
4. Render + validate variables → `InvalidVariables` → `422`.
5. Insert `notifications` row with `status='pending'`.
6. `StubSender.send(...)` → `provider_message_id`.
7. Update row → `status='sent'`, `provider_message_id`, `sent_at` (sender failure →
   `status='failed'` + `error`).
8. Serialize the record → `201`.

## Testing (TDD)

- `tests/unit/` — fast, no I/O:
  - template load/render: success, missing-variable error, unexpected-variable error.
  - service orchestration with a fake repository + stub sender.
- `tests/integration/` — against a **dedicated test Postgres DB** (never dev/prod):
  - `POST`/`GET`/`health` endpoints end-to-end.
  - repository against real Postgres.

## Milestones

1. **Database setup** — Postgres connection/config, SQLAlchemy model + Alembic migration
   for `notifications`, test-DB wiring, `/health` checking connectivity.
2. **`POST /notifications` vertical slice** — templates engine + strict render, stub
   sender, `NotificationService`, repository, the `POST` endpoint, and `GET
   /notifications/{id}` to read it back. One real template
   (`templates/sms/appointment_reminder.yaml`) working end-to-end against Postgres.

Later: recipient validation, real provider adapter, async, more templates/channels.

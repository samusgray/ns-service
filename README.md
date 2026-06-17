# notification-service

An internal HTTP service that other microservices call to send SMS and email
notifications. This repository owns the **notification templates** as the source of truth and
records every send (request + outcome) in Postgres. Actual delivery is **stubbed** — when the
service would hand a message to a vendor (Mailgun/SendGrid/Twilio), it pretends to and returns
a fake provider message id. The real provider adapter is deliberately out of scope (see
[What we would change](#what-we-would-change)).

The full design discussion is captured in
[`docs/superpowers/specs/2026-06-17-notification-service-design.md`](docs/superpowers/specs/2026-06-17-notification-service-design.md);
the task-by-task build plan is in
[`docs/superpowers/plans/2026-06-17-notification-service.md`](docs/superpowers/plans/2026-06-17-notification-service.md).

---

## What was built

A thin, end-to-end vertical slice that is genuinely runnable, not a skeleton:

- **`GET /health`** — returns `200 {"status":"ok"}` when Postgres is reachable, `503` otherwise.
- **`POST /notifications`** — renders a template, "sends" it via the stub provider, persists the
  record, and returns `201` with the stored notification.
- **`GET /notifications/{id}`** — reads a notification back (`404` if unknown).

### Request / response

```jsonc
// POST /notifications
{
  "channel": "sms",                       
  "template_key": "appointment_reminder",
  "recipient": "+15551234567",
  "variables": { "member_name": "Sam", "appointment_location": "Austin Clinic" }
}
// 201
{
  "id": "ab00608c-...",
  "channel": "sms",
  "template_key": "appointment_reminder",
  "recipient": "+15551234567",
  "status": "sent",
  "provider_message_id": "stub-07d808ed8551",
  "created_at": "2026-06-17T16:29:48-06:00",
  "sent_at": "2026-06-17T16:29:48-06:00"
}
```

### Architecture

Layered, with the service core kept transport- and storage-agnostic so a second transport
(e.g. gRPC) or a real provider can be added without touching the orchestration logic.

```
api/  (FastAPI)        the only layer that knows HTTP; maps domain errors → status codes
  └── service.py       NotificationService: load template → render → "send" → persist
        ├── templating.py    load templates/{channel}/{key}.yaml + strict variable render
        ├── providers.py     NotificationSender port + StubSender
        ├── repository.py    NotificationRepository port + Postgres implementation
        └── domain.py        enums, typed errors, the Notification dataclass
db.py / migrations/    SQLAlchemy model + Alembic migration for the notifications table
config.py              pydantic-settings (DATABASE_URL)
templates/sms/appointment_reminder.yaml    the one real template in the slice
```

Data flow for a create: validate request → load template (`422` if missing) → render and
**strictly** validate variables, rejecting both missing *and* unexpected variables (`422`) →
build a `Notification` → call the sender → persist the terminal state → serialize.

### Data model

A single `notifications` table (templates stay in the filesystem). Columns:
`id, template_key, channel, recipient, variables (jsonb), subject, body, status,
provider_message_id, error, created_at, updated_at, sent_at`. `channel` and `status` are `text`
with CHECK constraints (`sms|email`, `pending|sent|failed`) mapped to Python `StrEnum`s. The
rendered `body`/`subject` and input `variables` are stored for audit and reproduction.

### Quality evidence

Built test-first, one commit per step. Current state:

- **25 tests** (17 unit with no I/O, 8 integration against Postgres), **97% coverage**.
- `ruff check`, `ruff format --check`, and `ty check` all clean.

```bash
uv run pytest            # full suite + coverage
uv run ruff check .      # lint
uv run ty check          # type check
```

### Running it

Requires a reachable Postgres. Create the databases and apply the migration:

```bash
createdb notification_service
createdb notification_service_test
DATABASE_URL=postgresql+psycopg://<user>@localhost:5432/notification_service uv run alembic upgrade head
```

Run the service and exercise it:

```bash
DATABASE_URL=postgresql+psycopg://<user>@localhost:5432/notification_service \
  uv run uvicorn notification_service.api.app:app --port 8000

curl -s -X POST localhost:8000/notifications \
  -H 'content-type: application/json' \
  -d '{"channel":"sms","template_key":"appointment_reminder","recipient":"+15551234567",
       "variables":{"member_name":"Sam","appointment_location":"Austin Clinic"}}'
```

---

## Key design decisions

- **HTTP/JSON via FastAPI**, not gRPC — trivial to call and verify, with a typed contract via
  Pydantic/OpenAPI. gRPC's throughput/streaming strengths aren't the bottleneck for an internal
  notification service. The core stays transport-agnostic so gRPC could be added later.
- **`channel` is explicit in the request**, not inferred from the template — clearer at the
  call site, and the template lookup path (`templates/{channel}/{key}.yaml`) encodes the channel
  so the service never introspects a template to learn its type.
- **Templates are YAML files in the repo** with declared `required_variables`, rendered by
  strict substitution. Declared variables make validation a real, testable behavior rather than
  a best-effort.
- **Synchronous** SQLAlchemy/FastAPI for the slice; async deferred until there's a reason.
- **Status models the full `pending → sent/failed` lifecycle** in the schema even though the
  stub always succeeds, so the column is ready for a real, asynchronous sender. The service
  currently writes the **terminal state in one insert** (the transient `pending` row has no
  observable value while sending is synchronous and in-process) — an intentional simplification
  that the deferred async/outbox work below makes real.

---

## What was deferred (and why)

Cut deliberately to ship a working slice; each is a known next step, not an oversight.

- **Real provider adapter** (Mailgun/SendGrid/Twilio) — the `NotificationSender` port exists and
  `StubSender` satisfies it; a real adapter drops in behind the same interface.
- **Recipient format validation** (email shape, SMS E.164) — important, but adds nothing to the
  core flow; recipient is currently stored as supplied.
- **Async / queued delivery** — synchronous send is fine for the slice and far simpler to test.
- **The email channel end-to-end** — modeled throughout (subject column, email template shape),
  but only the SMS path has a real template in the slice.
- **Pre-commit hooks** — the gates (`ruff`, `ty`, fast tests) all run; wiring them into
  `pre-commit` is mechanical.

---

## What we would change

The decisions above are right for a thin slice. These are what a production version needs, in
the order I'd tackle them. The first three matter most because this is a **healthcare** product.

### 1. PII / PHI handling is the headline concern
The service persists rendered `body` and input `variables` — member names, appointment
locations, plausibly PHI — in plaintext and indefinitely, and `body` is one careless log line
away from leaking. A production version needs: encryption at rest, a retention/purge policy,
PII redaction in logs, and access auditing — and a hard look at whether the full rendered body
should be stored at all versus re-rendered on demand from `template_key` + `variables`.

### 2. Idempotency keys
Callers are other services, and they will retry. Without an idempotency key, a retried
"appointment reminder" double-texts a patient. Accept a client-supplied key, dedupe, and return
the original record on replay.

### 3. Asynchronous delivery via a transactional outbox
Decouple accepting a request from delivering it: persist `pending` and an outbox row in one
transaction → a worker delivers with retries/backoff → status is updated. This is exactly why
`pending` already exists in the schema, and it turns the current single terminal-state write into
the real lifecycle.

**Tolerating provider outages** (a vendor — Twilio for SMS, Mailgun for email — down for a while,
then back). The same machinery handles every channel; the provider is just a different adapter
behind the breaker:

- **Durability before acknowledgement.** The outbox commit means a vendor outage never fails or
  drops a `POST` — the API returns `202 Accepted` and the intent survives; delivery happens out of
  band.
- **Worker pool, not inline calls.** Workers claim due jobs (`SELECT … FOR UPDATE SKIP LOCKED`)
  under a **lease** so a crashed worker's job is reclaimed, not stranded.
- **Capped exponential backoff + jitter** on retryable failures (timeouts, `5xx`, `429`); permanent
  `4xx` (invalid number/address) fail fast without retrying. Jitter prevents a synchronized retry
  stampede.
- **Per-provider circuit breaker.** After sustained failures the breaker **opens** and workers stop
  hammering that vendor; after a cooldown a **half-open** probe detects recovery and **closes** it.
  This is what gracefully handles both the outage *and* the comeback, per provider — Twilio can be
  open while Mailgun is healthy.
- **Provider idempotency key** so a retry after an ambiguous send (vendor accepted, response lost)
  doesn't double-send — no duplicate texts or emails.
- **Rate-limited backlog drain** on recovery (concurrency cap honoring vendor limits) so the queue
  empties steadily instead of triggering a second outage.
- **Deadlines + dead-letter.** Time-sensitive jobs past their `not_after` expire rather than deliver
  late (a reminder for a past appointment is worse than none); jobs past `max_attempts` are
  dead-lettered to `failed` and alerted on.
- **Signals + failover.** Queue depth and oldest-pending age are the truest "vendor is down" alerts;
  because delivery sits behind the `NotificationSender` port, an open breaker can optionally route a
  channel to a secondary provider (SES/SendGrid, a backup SMS carrier).

### 4. Status modeling: canonical lifecycle + event log + per-provider adapters
A single overwritten `status` column can't represent the reality that **Twilio and Mailgun speak
different status vocabularies** (Twilio: `queued/sent/delivered/undelivered/failed` + error
codes; Mailgun: `accepted/delivered/bounced/complained/opened/clicked/...`). The model:

- a **small, provider-agnostic canonical status** on the record
  (`pending → sent → delivered`, terminal `failed/bounced/undelivered`) — the only thing other
  services branch on;
- an append-only **`notification_events`** table holding the raw provider status, mapped
  canonical status, error code, and the full webhook `payload` (with `provider_event_id` for
  webhook-retry idempotency);
- a **per-provider adapter** that maps native → canonical, with **guarded lifecycle transitions**
  (a late `sent` webhook must not clobber `delivered`) rather than last-write-wins, and treating
  engagement signals like `opened`/`clicked` as events distinct from the delivery lifecycle.

Notably, this argues for **keeping one `notifications` table** plus an events table — *not*
splitting by channel. Divergent statuses are a *provider* concern (two SMS providers could
disagree too), resolved by adapters and an event log, not by channel-specific tables. Per-channel
or joined-table inheritance only earns its keep once email grows genuinely different structure
(HTML bodies, cc/bcc, attachments); a `payload jsonb` column is the cheaper intermediate step.

### 5. Everything else on the radar
- **Template versioning** — store the template version/hash on each notification so a record is
  reproducible after the file changes; add a CI check that every template's placeholders are a
  subset of its declared `required_variables`.
- **AuthN/AuthZ + quotas** — authenticate callers (mTLS / service tokens), authorize which
  service may send which template, and rate-limit so one buggy caller can't spam patients.
- **Observability** — structured logs, per-channel/provider/template metrics, and a correlation
  id propagated from the calling service.
- **Scheduling** — appointment reminders are inherently "send at time T"; delayed/scheduled
  sends are a likely near-term requirement.
- **Multi-provider + failover** — provider chosen by config per channel, with failover and
  provider-error → domain-error mapping.
- **Hermetic test infrastructure** — the suite currently shares a local `*_test` database and
  truncates per test; testcontainers would make it isolated and parallel-safe.

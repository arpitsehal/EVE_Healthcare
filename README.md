# EVE Healthcare Diagnostic Booking API

A small FastAPI service for diagnostic-centre discovery, test bookings, JWT authentication, and simulated payments. It uses SQLAlchemy 2, PostgreSQL in Docker Compose, and SQLite for a zero-service local run and isolated tests. No real payment provider is connected.

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:JWT_SECRET_KEY = "replace-with-a-long-random-secret"
$env:WEBHOOK_SECRET = "replace-with-a-separate-random-secret"
python -m uvicorn app.main:app --reload
```

If `uvicorn` isn't installed as a standalone script on your `PATH`, run it via `python -m uvicorn` as above; this works as long as the package is installed, regardless of `PATH`.

Without `DATABASE_URL`, the service creates `eve_healthcare.db` in the current directory. Tables are created on startup. Open `http://127.0.0.1:8000/docs` for interactive OpenAPI docs; `/health` is the health check.

For PostgreSQL, copy `.env.example` to `.env`, replace both secrets, then run:

```powershell
docker compose up --build
```

The compose file starts PostgreSQL 16 and the API. Docker must be installed and running. Database migrations are intentionally not included in this small assignment; `create_all` initializes a fresh database, while production schema changes should use Alembic.

## API

All protected routes use `Authorization: Bearer <access_token>`. Signup accepts a valid email and a password of at least 8 characters. Login returns a signed JWT. The token lifetime is controlled by `JWT_EXPIRE_MINUTES` (default 60).

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `POST` | `/auth/signup` | No | Register a patient/catalogue owner |
| `POST` | `/auth/login` | No | Get a JWT |
| `GET` | `/centres` | No | List active centres with active tests; supports `offset` and `limit` |
| `GET` | `/centres/{centre_id}` | No | Read a centre and its active tests |
| `POST` | `/centres` | Yes | Create a centre owned by the caller |
| `PATCH` / `DELETE` | `/centres/{centre_id}` | Owner | Update or deactivate a centre |
| `GET` / `POST` | `/centres/{centre_id}/tests` | Read / owner | List tests or add a test |
| `PATCH` / `DELETE` | `/tests/{test_id}` | Owner | Update or deactivate a test |
| `POST` | `/bookings` | Yes | Book a future appointment for a test at its centre |
| `GET` | `/bookings` | Yes | List only the caller's bookings; supports `offset` and `limit` |
| `GET` | `/bookings/{booking_id}` | Yes | Read the caller's booking |
| `POST` | `/bookings/{booking_id}/cancel` | Yes | Cancel a pending booking |
| `POST` | `/payments/` | Yes | Run a deterministic mock payment and update booking status |
| `POST` | `/payments/webhook/` | `X-Webhook-Secret` | Apply an authenticated, idempotent payment event |

### Example flow

Register, then login:

```http
POST /auth/signup
Content-Type: application/json

{"name":"Avery Patient","email":"avery@example.com","password":"correct-horse-123"}
```

```http
POST /auth/login
Content-Type: application/json

{"email":"avery@example.com","password":"correct-horse-123"}
```

Use the returned access token as a Bearer token to create a centre and a priced test:

```http
POST /centres
Authorization: Bearer <access_token>
Content-Type: application/json

{"name":"North Lab","location":"Seattle"}
```

```http
POST /centres/1/tests
Authorization: Bearer <access_token>
Content-Type: application/json

{"name":"Complete Blood Count","description":"CBC","price":"42.50"}
```

Create a booking with an ISO 8601 future timestamp including a timezone, then simulate payment:

```http
POST /bookings
Authorization: Bearer <access_token>
Content-Type: application/json

{"centre_id":1,"test_id":1,"appointment_at":"2030-06-01T09:00:00Z"}
```

```http
POST /payments/
Authorization: Bearer <access_token>
Content-Type: application/json

{"booking_id":1,"idempotency_key":"avery-booking-1-attempt-1","simulate_status":"SUCCESS"}
```

`simulate_status` accepts `SUCCESS` or `FAILED` and exists solely to make the mock provider and its failure path reproducible. Repeating a payment request with the same user and idempotency key returns the original payment; reusing the key for another booking returns `409`.

Example provider callback (configure the secret with `WEBHOOK_SECRET`):

```http
POST /payments/webhook/
X-Webhook-Secret: <webhook_secret>
Content-Type: application/json

{"event_id":"provider-event-123","payment_id":1,"status":"SUCCESS"}
```

An identical event replay returns `duplicate: true` without changing data. Reusing an event ID with a different payment/status returns `409`. A failed payment may be reconciled to success by a new provider event; a successful payment cannot be downgraded. Cancelled bookings cannot be paid or updated by a webhook.

## Data model

- `users`: normalized unique email and Argon2 password hash; never returns the password hash.
- `diagnostic_centres`: owner, name, location, and active flag.
- `diagnostic_tests`: centre, name, optional description, decimal price, and active flag.
- `bookings`: patient, test, centre, timezone-aware appointment, price snapshot, and `PENDING`, `CONFIRMED`, `FAILED`, or `CANCELLED` status.
- `payments`: booking, patient, price snapshot, unique per-user idempotency key, and payment status.
- `webhook_events`: unique provider event ID, payment, and status for transactional replay detection.

Centres and tests are deactivated rather than physically deleted, preserving booking history. Booking creation verifies that the selected test belongs to the selected centre and snapshots its current price. A patient can only read, pay for, or cancel their own booking. Only a centre's creator can manage it and its tests.

## Tests

```powershell
python -m pytest -q
```

The integration tests use a fresh in-memory SQLite database and exercise authentication, validation, catalogue ownership, booking ownership, price snapshots, successful/failed payments, idempotent payment keys and webhook events, conflicting replays, cancellation, and historical records.

## Assessment cross-check

| Assessment area | Weight | Implemented / verified in |
| --- | ---: | --- |
| Code quality and maintainability | 20% | Layered `app` modules, typed schemas, environment configuration, and focused tests |
| API/backend design | 20% | REST routes, validation, pagination, ownership checks, OpenAPI docs |
| Database design | 15% | Relational SQLAlchemy models, foreign keys, unique constraints, price snapshots |
| Edge-case handling | 15% | Invalid IDs/input, ownership, duplicate/conflicting idempotency keys, terminal state checks |
| Tests | 10% | `tests/test_api.py`, run with `python -m pytest -q` |
| Git/README/documentation | 10% | This README, runnable setup, endpoint examples, schema, assumptions, improvement notes |
| Bonus engineering | 10% | PostgreSQL Docker Compose, Swagger, pagination, JWT, Argon2, webhook idempotency |

## Assumptions and next improvements

- This is an assessment-sized mock service, not a production medical-record system. It stores no diagnostic results or sensitive clinical data.
- Any registered user may create a centre; only that user can edit/deactivate it. A production service would add verified-provider and staff roles.
- Payment outcomes are simulated from the request for deterministic demonstrations. A real provider would own the outcome and verify signed callbacks.
- The webhook shared secret is a compact stand-in for provider signatures. Production would use provider-specific signature verification, timestamp validation, and secret rotation.
- For production I would add Alembic migrations, stronger role/tenant policy, audit logs, rate limiting, observability, appointment-slot concurrency protection, and provider retries/outbox processing.
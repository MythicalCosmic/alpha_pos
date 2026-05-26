# alpha_pos

Django backend for a multi-surface point-of-sale system (admin back-office,
cashier app, waiter tablet, customer/kitchen displays). SQLite by default for
local work, PostgreSQL + Redis in production. A Postman collection
(`postman_collection.json`) ships with the repo as the working API reference.

## Apps

| App             | Surface / purpose                                                        |
| --------------- | ------------------------------------------------------------------------ |
| `admins`        | Back-office: users, catalog, orders, places/tables, shifts, inkassa.     |
| `customers`     | Cashier app + `client_display`/`chef_display` kitchen/lobby screens.     |
| `waiters`       | Waiter tablet flow (tables, orders, items).                              |
| `stock`         | Inventory, suppliers, recipes, production, transfers, counts, AI assist. |
| `hr`            | Employees, attendance, leave, documents, salary.                         |
| `discounts`     | Discount rules and order-level application.                              |
| `notifications` | Telegram channel notifications + message templates.                      |
| `base`          | Shared models, security/auth, repositories, sync engine.                 |

## Running locally

### Easiest: single-PC install (Windows / Mac / Linux)

For deploying onto a single restaurant PC where one cashier app talks
to one local backend, you don't need Postgres, Redis, Docker, or any
external service — only Python 3.11+ on the PATH.

**Windows.** Double-click `install.bat` once (creates a virtualenv,
installs deps, runs migrations, creates the admin). Write down the
admin email + password printed at the end. After that, every time
the PC boots, double-click `start.bat` to launch the server on
http://127.0.0.1:8000.

**Mac / Linux.** Run `bash install.sh` once, then `bash start.sh` to
launch.

Both paths use SQLite at `db.sqlite3` and an in-process cache — no
Redis, no Postgres. Move to `DB_ENGINE` + `USE_REDIS` only when you
need multi-worker or multi-branch.

### Manual / developer install

```bash
# Python 3.14 + virtualenv
pip install -r requirements.txt -r requirements-dev.txt

# SQLite (default if DB_ENGINE is unset)
python manage.py migrate
python manage.py runserver
```

Or via Docker Compose (PostgreSQL + Redis + web):

```bash
docker compose up --build
```

## Environment variables

| Var                       | Purpose                                                            |
| ------------------------- | ------------------------------------------------------------------ |
| `DEBUG`                   | `True` in dev only. When false, `SECRET_KEY` is required.          |
| `SECRET_KEY`              | Django secret key. Required in production.                         |
| `ALLOWED_HOSTS`           | Comma-separated hostnames. Defaults to `localhost,127.0.0.1`.      |
| `DB_ENGINE` / `DB_*`      | Postgres connection. Unset → SQLite at `db.sqlite3`.               |
| `REDIS_URL` / `USE_REDIS` | Redis cache. Falls back to in-memory if unset.                     |
| `CORS_ALLOWED_ORIGINS`    | Comma-separated origins for the Electron renderer / web client.    |
| `MEDIA_ROOT`              | Where HR documents live. Files are never served by the static URL. |
| `LOG_DIR` / `LOG_LEVEL`   | Rotating file logs in production; console only in DEBUG.           |
| `GEMINI_API_KEY`          | Optional. Enables `/api/admins/stock/ai/query`.                    |
| `SECURE_SSL_REDIRECT`     | Opt-in HTTPS redirect (off by default to avoid proxy loops).       |
| `TRUST_FORWARDED_PROTO`   | Set when terminating TLS at a known reverse proxy.                 |

### Sync-specific

| Var                      | Purpose                                                                |
| ------------------------ | ---------------------------------------------------------------------- |
| `BRANCH_TOKEN_MAP`       | `{token: branch_id}` map. Receive endpoint binds tokens to branches.   |
| `ALLOWED_BRANCH_TOKENS`  | Legacy unbound token list. Use `BRANCH_TOKEN_MAP` for new deployments. |
| `CLOUD_SYNC_TOKEN`       | Required when a branch pushes to the cloud `/api/sync/receive`.        |
| `SYNC_MANAGEMENT_TOKEN`  | Gates `status` / `trigger` / `queue` / `report`. Required outside dev. |

## Authentication

Custom server-side session, **not** Django's `auth`. Login (`/api/admins/auth-login`,
`/api/waiters/auth-login`, `/api/auth-login` for customers) returns an opaque
token and sets it as an HttpOnly cookie. Subsequent requests authenticate via
the cookie or `Authorization: Bearer <token>` — both routes hit the same
`Session` table. JSON views are `@csrf_exempt` because the model is
token-in-cookie + token-in-header, not Django CSRF. There is no public
`auth-register`; admins create users via `POST /api/admins/users`.

Endpoint families:

- `@admin_required` — full admin surface (catalog CRUD, user mgmt, inkassa).
- `@login_required` — cashier / customer / waiter flows.
- `@permission_required('order.update', …)` — fine-grained checks on top.

## Idempotency

Order write endpoints (`orders/create`, `orders/<id>/pay`, `orders/<id>/cancel`
across the admin, customer, and waiter surfaces) accept an
`Idempotency-Key: <opaque-token>` header. Clients should send a fresh UUID per
logical request and reuse the same value on retries — the server replays the
original response on a duplicate key instead of acting twice, and returns
`409` while the original is still in flight. The header is optional; without
it the endpoint behaves the same as before. Stored in `base.IdempotencyKey`.

## Sync

`/api/sync/` exposes:

- `health` — unauthenticated probe.
- `receive` — accepts `Branch <token>` or `Cloud <token>`. `BRANCH_TOKEN_MAP`
  binds each token to one branch so `X-Branch-ID` cannot be spoofed.
- `changes` — pull endpoint, same auth as `receive`.
- `status`, `trigger`, `trigger-pull`, `full-push`, `queue`, `queue/clear`,
  `report` — gated by `Authorization: Management <SYNC_MANAGEMENT_TOKEN>`. Open
  only when `DEBUG=True` and the token is unset.

These endpoints assume a trusted management network; do not expose them
publicly even with the token set.

## Tests

```bash
pytest -q
python manage.py makemigrations --check --dry-run
python manage.py check --deploy
```

## Layout notes

- Models live in each app's `models.py`; `base/models.py` is the shared spine.
- Business logic sits in `<app>/services/`; views are thin and stateless.
- Repository helpers in `base/repositories/` centralize ORM queries.
- HR file uploads land in private `MEDIA_ROOT` and are streamed only via
  auth-gated download views.

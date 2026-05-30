# API changes — integrator notes

Changes that are visible across the HTTP wire and require client teams
to adapt. Anything not listed here is internal refactoring that does
not move bytes on the wire.

Originally tracked as smart_pos task T10 + bug B3.

## Authentication

### 7-day session lifetime

| Where | What changed |
| --- | --- |
| `admins/services/auth_service.py:12` | `SESSION_TTL_DAYS = 7` |
| `POST /api/admins/auth-login` | Returned token expires 7 days after issuance |
| `GET /api/admins/dashboard/today` (any authenticated endpoint) | After 7 days returns **401 Unauthorized** — client must re-login |

**Client action:** treat 401 on any authenticated endpoint as
"session expired, prompt re-login". Don't try to refresh — the
session is a single opaque bearer token, not OAuth.

### License kill switch — 503 envelope

When the install's license is unregistered / suspended / expired /
offline-grace-exceeded, every business endpoint returns **503**
with this body:

```json
{
  "success": false,
  "code": "license_unregistered" | "license_suspended" | "license_expired" | "license_offline_grace_exceeded" | "license_inactive",
  "status": "UNREGISTERED" | "SUSPENDED" | "EXPIRED",
  "message": "<human-readable>",
  "tenant": { "org_name": "...", "email": "..." },
  "banner": "<optional banner from control center>"
}
```

**Client action:** switch on `code` (not `message`) to drive the UX
(setup screen vs. expired-renew screen vs. "contact vendor" screen).

`/api/licensing/status`, `/api/licensing/setup`, and `/healthz` are
allowlisted and continue to work in this state.

## Orders

### `pay_order` payment_method parameter

| Endpoint | Change |
| --- | --- |
| `POST /api/customers/orders/<id>/pay` | Now accepts optional `payment_method` body field |

Accepted values: `"CASH"`, `"UZCARD"`, `"HUMO"`, `"PAYME"`. Defaults to
`"CASH"` when omitted (preserves backward compatibility).

```json
POST /api/customers/orders/42/pay
{
  "payment_method": "UZCARD"
}
```

Unknown values return 422 with `errors.payment_method`. Cash-drawer
side effects only fire when `payment_method == "CASH"`.

## Error envelope normalisation

| Before (legacy / pre-2026-05) | After |
| --- | --- |
| `"This field is mandatory, dawg"` | `"Bad Request"` |
| `"Hmm, can't find that one!"` | `"Not Found"` |
| `"Nope, you can't"` | `"Unauthorized"` / `"Forbidden"` |
| Various creative 5xx messages | `"Internal server error"` (5xx logs the detail server-side) |

The structured fields (`success`, `code`, `errors`) are unchanged —
only the human-readable `message` strings are now standard HTTP
wording.

**Client action:** any test, dashboard, or integration that asserts
exact error TEXT must be updated to either (a) match the new wording
or (b) ideally switch to asserting against `success: false` + the
`code` / `errors.<field>` structured fields, which are stable.

## Idempotency-Key on order mutations

| Endpoint | Behaviour |
| --- | --- |
| `POST /api/customers/orders` | Honors `Idempotency-Key` header |
| `POST /api/customers/orders/<id>/pay` | Honors `Idempotency-Key` header |
| `POST /api/admins/orders/<id>/cancel` | Honors `Idempotency-Key` header |

A client that includes `Idempotency-Key: <uuid>` and retries after a
network failure (without receiving the original 2xx) gets the **same
2xx response** back, not a 4xx duplicate-order error. Keys are scoped
per-endpoint and live in `base.models.IdempotencyKey`. TTL: 24 hours.

**Client action:** generate a fresh UUID per logical retry attempt and
include it on retries. Without the header, the behaviour is unchanged
(row locks + `is_paid` checks still prevent most double-submits, but
not all).

## Licensing setup wizard — email-only

| Endpoint | Change |
| --- | --- |
| `POST /api/licensing/setup` | Body is now `{"email": "..."}` only |

Old fields `org_name` and `invite_code` are no longer required (and
not sent by the alpha_pos client). The control center matches the
email against a pre-issued `InviteCode.intended_email` to verify the
operator. `org_name` can be set later via the owner profile endpoint
once the install is live.

**Client action (renderer / setup wizard UI):** drop the `org_name`
and `invite_code` form fields. Send only `email`.

## License perpetual-unlock endpoint removed

`POST /api/licensing/unlock` no longer exists. The Ed25519 signed
escape hatch was removed in commit `ce56671`. Recovery from a
bricked install is now operator-side only (re-run setup wizard,
or edit the License row via shell).

**Client action (renderer):** remove any UI for pasting an unlock
file — it will 404.

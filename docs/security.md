# Security operations

Operational notes for running alpha_pos in production. Covers the
secrets the system holds, the kill-switch flow, the rotation/recovery
procedures, and the incident-response sketches.

For per-feature threat models look in the inline docstrings — every
security-sensitive module has them (`licensing/services/*`,
`base/security/*`, `notifications/services/qr_order_service.py`).

## Secrets the install owns

| Secret | Where it lives | Rotation impact |
| --- | --- | --- |
| `SECRET_KEY` | `.secret_key` (single-PC) or `SECRET_KEY` env | Invalidates all sessions + signed payloads. Rotate only with a planned re-login window. |
| `LICENSE_FERNET_KEY` | `.license_fernet_key` (single-PC) or `LICENSE_FERNET_KEY` env | At-rest license key becomes undecryptable. Operator must re-run setup wizard. |
| License bearer key | `License.key_encrypted` (Fernet-encrypted, BinaryField) | Encrypted at rest. Recovery = re-run setup wizard against the control center. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` | env | Webhook stops working until updated. Re-register with `setWebhook`. |
| `SYNC_MANAGEMENT_TOKEN`, branch tokens (`BRANCH_TOKEN_MAP`) | env | Sync admin endpoints + branch peers lock out. Rotate token, restart, distribute. |
| `GEMINI_API_KEY` | env | AI assistant goes offline; nothing else affected. |

**Nothing else is a secret.** The control-center vendor public key, the
Ed25519 perpetual-unlock file, and `LICENSE_VENDOR_PUBLIC_KEY` were
removed in commit `ce56671`; they are not part of the current
threat model.

## Boot-time guarantees

| Check | Where | What it prevents |
| --- | --- | --- |
| `SECRET_KEY` required when `DEBUG=False` | `alpha_pos/settings.py` | Booting prod with the insecure dev key |
| `LICENSE_CONTROL_CENTER_URL` must be `https://` when `DEBUG=False` | `alpha_pos/settings.py` | MITM-replaying heartbeat responses to keep returning `ACTIVE` |
| `LICENSE_FERNET_KEY` required when `DEBUG=False` (no SECRET_KEY fallback) | `licensing/services/crypto.py` | `SECRET_KEY` rotation silently invalidating the stored license key |
| Middleware position asserted | `licensing/apps.py` | Refactor moving the kill-switch out of slot 1 |

If any of these fail the process refuses to start. Don't `try/except` past them.

## License kill switch — operational view

The middleware (`licensing/middleware.py`) refuses every non-allowlisted
request when:

1. `License.status` is `UNREGISTERED` — no setup wizard run yet.
2. `License.status` is `SUSPENDED` — the control center has explicitly
   suspended this tenant, or our key was rejected on the last heartbeat
   (401/410).
3. `License.status` is `EXPIRED` — the control center reported expired
   on a heartbeat, OR `License.expires_at` is in the past (per the
   conservative `max(wall_clock, last_server_now)` anchor).
4. Offline grace exceeded — no successful heartbeat for
   `LICENSE_GRACE_DAYS` (default 7).

Heartbeat responses carry an `X-Response-Signature: sha256=<hex>`
header — an HMAC-SHA256 of the canonical JSON body keyed on the bearer
license key. A 200 OK without a valid signature is treated as failure:
the License row stays unchanged and the grace clock keeps ticking. This
defeats a MITM that has stripped TLS and tries to forge `status:
ACTIVE`.

### Recovery — production install bricked

The only paths to restore service:

- **Pay the bill / fix the suspension in the control center.** Next
  heartbeat (≤ 5 minutes) flips status back to ACTIVE.
- **SSH to the host and edit the License row** via
  `python manage.py shell`. Use this only when the control center is
  itself broken; document why in `LicenseEvent.detail` if you do.
- **Re-run the setup wizard** if the at-rest Fernet key was lost or
  rotated (so the bearer key can't be decrypted).

There is no signed-unlock file, no admin URL bypass, no env-var
emergency override in production. `LICENSE_DEV_BYPASS` is hard-gated on
`DEBUG=True` and dead in shipped builds.

## Rate limits in place

| Endpoint | Limit | Module |
| --- | --- | --- |
| `/api/admins/auth-login` | 5 / 60s per IP + per-user backoff | `admins/views/auth_views.py` |
| `/api/licensing/setup` | 5 / 5min per IP, 3 / 5min per email | `licensing/views.py` |
| Telegram webhook | Requires `X-Telegram-Bot-Api-Secret-Token` (503 otherwise) | `notifications/views/telegram_webhook.py` |

All counters live in the configured cache backend. **In multi-worker
gunicorn deploys, switch from LocMemCache to Redis** (`USE_REDIS=true`)
— LocMemCache is per-process and silently multiplies limits by worker
count. The settings module emits a `RuntimeWarning` if this combination
is detected.

## Audit log

`base.models.AuditLog` records every sensitive admin action with actor,
target, IP, and structured metadata. Coverage today:

- `INKASSA_PERFORM`, `USER_CREATE/UPDATE/DELETE`, `SHIFT_RECONCILE`,
  `ORDER_CANCEL`, `PRODUCT_PRICE_CHANGE`,
  `DISCOUNT_CREATE/UPDATE/DELETE`, `LOYALTY_REDEEM`.
- Role/permission changes flow through `USER_UPDATE` with
  `metadata.fields_changed` listing `role`, `permissions`, etc.
  (`admins/views/user_views.py:73-91`).

The table is push-only to the cloud collector (`SyncMixin` opt-out
preserves it as host-local — branch peers cannot inject rows). Edit /
delete is denied at the model layer.

## Incident response sketch

Treat the following as a starting point; refine based on the actual
incident class.

### 1. Suspected leaked license bearer key

1. Open the control-center dashboard, **REVOKE** the LicenseKey.
2. Next heartbeat from the install returns 410 → local flips to
   `SUSPENDED` → middleware blocks.
3. Issue a fresh InviteCode bound to the operator's email.
4. Operator re-runs `/api/licensing/setup` to take a new key.
5. Confirm `LicenseEvent` table on the install shows
   `STATUS_CHANGED ACTIVE→SUSPENDED` then `SETUP_SUCCEEDED`.

### 2. Suspected admin account compromise

1. `python manage.py shell` → flip the user's `status` to `SUSPENDED`,
   rotate their password.
2. Audit log query:
   ```python
   from base.models import AuditLog
   AuditLog.objects.filter(actor_id=<id>).order_by('-created_at')[:50]
   ```
3. Look for `USER_UPDATE` rows where `metadata.fields_changed` contains
   `permissions` or `role` — those are escalation attempts.
4. Look for `ORDER_CANCEL` and `INKASSA_PERFORM` rows — both are
   common abuse vectors.
5. Force-logout every active session for that user:
   ```python
   from base.models import Session
   Session.objects.filter(user_id=<id>).delete()
   ```

### 3. Telegram webhook abuse / spam

1. Rotate `TELEGRAM_WEBHOOK_SECRET`, re-`setWebhook` against
   `https://api.telegram.org/bot<TOKEN>/setWebhook` with the new value.
2. Check the per-chat rate-limit counters in cache; tighten if needed.
3. If the bot token itself leaked, regenerate via BotFather and update
   `TELEGRAM_BOT_TOKEN`.

### 4. Sync token leak

1. Remove the leaked token from `BRANCH_TOKEN_MAP` (or
   `ALLOWED_BRANCH_TOKENS`), restart all branch processes.
2. Audit recent sync push activity via the sync management endpoints.
3. Issue fresh per-branch tokens and redistribute.

## What NOT to do

- Don't disable the license kill switch in production. The DEBUG-only
  bypass exists because removing it would risk a customer bypass.
- Don't commit any `.env`, `.secret_key`, or `.license_fernet_key`
  file. `.gitignore` protects against it; verify before each tag.
- Don't widen `CORS_ALLOWED_ORIGINS` to `*` in production — the
  `corsheaders` library refuses to do this with credentials, but
  permissive lists still expose your endpoints to any origin a browser
  can reach.
- Don't trust `X-Forwarded-For` without `TRUST_FORWARDED_FOR=true` AND
  a known-good proxy in front. Without that gate, IP-based rate limits
  and audit attribution become attacker-controlled.

# Pre-release smoke checklist

Run this against staging before tagging a release. The whole list takes
~10 minutes if everything is healthy; if any step trips, **don't tag**.

Originally tracked as smart_pos question Q15 / task T3.

## 0. Preflight

- [ ] Latest commit on `main` is what you intend to tag.
- [ ] `pytest -q` passes locally (264+ tests as of 2026-05-30).
- [ ] `python manage.py check` clean.
- [ ] `python manage.py makemigrations --check --dry-run` clean.

## 1. End-to-end order lifecycle

Hit staging from a test cashier account:

- [ ] **Login** via `POST /api/admins/auth-login` with cashier creds → returns
      bearer session token.
- [ ] **Create order** via `POST /api/customers/orders` → returns 201 with
      `display_id`, `total_amount`.
- [ ] **Pay** via `POST /api/customers/orders/<id>/pay` with
      `{"payment_method": "CASH"}` → returns 200, `is_paid=true`.
- [ ] **Cancel** the (newly created and not the paid one — keep them separate)
      via `POST /api/admins/orders/<id>/cancel` → returns 200, status =
      CANCELED.

## 2. Aggregates reflect both

- [ ] `GET /api/admins/dashboard/today` shows the paid order in
      `revenue.cash` AND the canceled order in `orders_canceled`.
- [ ] `GET /api/admins/analytics/sales?range=today` counts match the
      dashboard numbers (sanity check that the two surfaces agree).

## 3. Audit trail populated

- [ ] `GET /api/admins/audit-log?action=ORDER_CANCEL` returns the cancel
      action with the cashier's id as `actor_id` and the order id as
      `target_id`.
- [ ] The IP recorded matches your client IP (or proxy IP if
      `TRUST_FORWARDED_FOR` is on).

## 4. Sync trigger (multi-branch deploys only)

Skip if this install is a standalone single-branch deployment.

- [ ] `POST /api/sync/trigger` with `X-Branch-Token: <branch_token>` AND
      `Authorization: Bearer <SYNC_MANAGEMENT_TOKEN>` returns 200 and a
      job ID.
- [ ] `GET /api/sync/status` after ~10 seconds shows the job as
      `COMPLETED` with non-zero push counts.
- [ ] Cloud collector receives the new audit row (verify on the
      collector side).

## 5. License kill switch sanity

- [ ] `GET /api/licensing/status` returns `status: ACTIVE`,
      `is_blocked: false`.
- [ ] Heartbeat daemon log shows a `heartbeat ok: status=ACTIVE` line
      in the last 6 minutes.
- [ ] `License.balance` and `days_remaining` are populated (control
      center is talking to us).

## 6. Roll-back rehearsal

- [ ] You know which previous tag to revert to.
- [ ] You know the migration-rollback command for the new migrations
      (`python manage.py migrate <app> <previous_migration_name>`).
- [ ] Static files / asset caches won't pin to the new build for users
      (CDN purge or hashed-name rebuild ready).

## Recording the run

Paste the result into the release notes:

```
Smoke: 2026-MM-DD HH:MM UTC, staging, branch <id>
- order lifecycle: PASS
- aggregates: PASS
- audit: PASS
- sync trigger: PASS / SKIPPED (single-branch)
- license: PASS
- rollback rehearsal: PASS
Tag: vX.Y.Z
```

If any line is anything other than PASS / SKIPPED, **do not tag** —
file the failure, fix, re-run from step 1.

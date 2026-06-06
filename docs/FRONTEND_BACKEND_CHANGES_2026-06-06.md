# Backend changes for the frontend — 2026-06-06

Branch: `prelaunch-fixes`. Everything below is live in the `alpha_pos` backend.
Base URLs: the monoblock/POS endpoints are mounted at the **root** (`/...`),
the management endpoints under **`/api/admins/...`**.

Response envelope everywhere: `{ "success": bool, "message": str, "data": {...} }`
(HTTP status mirrors success). `data` is what the examples below show.

---

## 1. Roles — new `MANAGER` tier

`User.role` is now one of: `USER, ADMIN, CASHIER, MANAGER, WAITER`.

- **CASHIER** — logs in on the monoblock; operates the till.
- **MANAGER** — logs in on the monoblock **next to cashiers** (NOT the admin
  dashboard), and additionally may use Settings / management screens.
- **ADMIN** — back-office/dashboard; cannot log into the monoblock.
- **WAITER** — own app; treated as kitchen/chef staff for analytics.

Who can call the management endpoints now:

| Endpoint group (`/api/admins/...`) | Allowed roles |
|---|---|
| categories, products, users, inkassa, app-settings | `ADMIN`, `MANAGER` |
| shifts: list/detail/active/templates/**reconcile** | `ADMIN`, `MANAGER` |
| shifts: **start**, **end** | `ADMIN`, `MANAGER`, `CASHIER` |
| **roles / permissions editor** | `ADMIN` only (managers must NOT see it) |
| analytics (incl. new shift analytics) | `ADMIN`, `MANAGER` |

A 403 from these now reads `"Manager access required"` / `"Staff access required"`.

---

## 2. Monoblock login — by `user_id` + PIN (no email needed)

`POST /auth-login`

The cashier/manager picker logs people in by **id + 4-digit PIN**. Email login
still works (managers have a real email; cashiers have an auto-generated
placeholder you should not show).

```jsonc
// Body — send EITHER user_id OR email, plus password (the 4-digit PIN)
{ "user_id": 12, "password": "4821" }
// or
{ "email": "manager@store.uz", "password": "4821" }
```
On success: `data: { token, user: { id, role, permissions, ... } }`. Set the
token as the session (cookie is set automatically; bearer also accepted).
Login is blocked for `ADMIN`/`WAITER` here (each has its own app).

---

## 3. Staff picker

`GET /cashiers` — **public** (shown before login), rate-limited.

Returns active **cashiers + managers**:

```jsonc
{
  "total": 2,
  "cashiers": [
    {
      "id": 12, "uuid": "…",
      "first_name": "Ali", "last_name": "Karimov", "name": "Ali Karimov",
      "email": "ali.karimov@local",   // placeholder for cashiers — don't display
      "role": "CASHIER",
      "is_manager": false,             // true ⇒ show Settings access in the UI
      "permissions": [],               // manager permission list ('*' never granted here)
      "on_shift": false,               // already has an ACTIVE shift ⇒ resume, don't double-start
      "last_login_at": "2026-06-06T08:12:00Z"
    }
  ]
}
```
Flow: `GET /cashiers` → tap a card → enter PIN → `POST /auth-login {user_id, password}`.

---

## 4. Creating users — 4-digit PIN, email optional

`POST /api/admins/users` (manager/admin)

- `password` must be **exactly 4 digits** (the PIN). Error otherwise:
  `422 { errors: { password: "PIN must be exactly 4 digits" } }`.
- `email` is **required only when `role == "MANAGER"`**
  (`422 { errors: { email: "email is required for managers" } }`).
  For every other role email is optional — backend derives a placeholder.

```jsonc
// Cashier (minimal): first + last + PIN
{ "first_name": "Ali", "last_name": "Karimov", "role": "CASHIER", "password": "4821" }
// Manager: email required
{ "first_name": "Dana", "last_name": "S", "role": "MANAGER", "email": "dana@store.uz", "password": "1234" }
```

---

## 5. Shared-till order ownership (relaxed)

Any POS staff (`CASHIER`/`MANAGER`/`ADMIN`) can now act on **any** order —
mark-ready, pay, change status, add/edit items — regardless of which cashier
opened it. The old *"created by another cashier"* 403 is gone for staff. (Only
self-service customers, role `USER`, are still restricted to their own orders.)

No request changes — calls that previously 403'd now succeed.

---

## 6. Instant products (drinks etc.) — `is_instant`

Products have a boolean **`is_instant`**. Instant items need no kitchen prep:
they're served immediately and never appear on the chef/kitchen display.

**Product create/update** (`POST`/`PUT /api/admins/products[/<id>]`): accept
optional `is_instant` (bool, default `false`). It's returned in every product
serialization (admin **and** customer/menu), so the menu can badge them.

```jsonc
{ "name": "Cola", "price": "12000", "category_id": 3, "is_instant": true }
```

**Behavior on orders (automatic, backend-side):**
- An order made up **entirely of instant items** is created already `READY`
  (its `ready_at` is set immediately) — it skips the kitchen.
- In a **mixed** order, instant items are pre-marked ready; only the cooked
  items go to the kitchen. The order becomes `READY` once the cooked items are.
- **`GET /orders/chef-display`** excludes instant items, and fully-instant
  orders don't appear there at all. `items_total`/progress count only cooked items.

The KDS/chef screen therefore only ever shows real kitchen work.

---

## 7. Deep shift analytics (NEW)

Two read endpoints (manager/admin), for any date window. `from`/`to` are
`YYYY-MM-DD` and both default to **today** if omitted (single-day query).

### `GET /api/admins/analytics/shifts/cashiers?from=&to=&user_id=`

`user_id` optional (filter to one cashier). Returns:

```jsonc
{
  "scope": "cashier",
  "date_from": "2026-05-07", "date_to": "2026-06-06",
  "filtered_user_id": null,
  "summary": {
    "shift_count": 42, "distinct_cashiers": 5,
    "by_status": { "ACTIVE": 1, "COMPLETED": 40, "ABANDONED": 1 },
    "total_hours": 318.5, "avg_shift_minutes": 455.0,
    "orders": { "total": 1290, "paid": 1250, "cancelled": 22,
                "cancel_rate_pct": 1.71, "avg_per_shift": 30.71, "units_sold": 4310 },
    "money": {
      "revenue": "184500000.00", "cash": "120300000.00", "card": "64200000.00",
      "avg_per_shift": "4392857.14", "avg_order_value": "147600.00",
      "revenue_per_hour": "579277.00",
      "payment_mix":     { "CASH": "...", "UZCARD": "...", "HUMO": "...", "PAYME": "...", "MIXED": "..." },
      "payment_mix_pct": { "CASH": 65.2, "UZCARD": 20.1, "HUMO": 8.0, "PAYME": 5.0, "MIXED": 1.7 }
    },
    "discounts": { "total_given": "...", "discounted_orders": 80, "discount_rate_pct": 6.2 },
    "speed": { "avg_prep_seconds": 540, "fastest_shift_avg_seconds": 300, "slowest_shift_avg_seconds": 900 },
    "punctuality": {
      "on_time_shifts": 35, "late_shifts": 5, "punctuality_rate_pct": 87.5,
      "avg_late_minutes": 12.4, "max_late_minutes": 41,
      "late_arrivals": [ { "shift_id": 88, "user_id": 12, "user_name": "Ali Karimov",
                           "late_minutes": 41, "start_time": "…" } ]   // who was late, sorted worst-first
    },
    "cash_accuracy": {
      "shifts_reconciled": 38, "shifts_unreconciled": 4,
      "short_count": 6, "over_count": 3, "exact_count": 29,
      "net_variance": "-42000.00", "total_abs_variance": "180000.00", "avg_abs_variance": "4736.84",
      "worst_shortage": { "shift_id": 71, "user_name": "…", "difference": "-50000.00" },
      "biggest_overage": { "shift_id": 64, "user_name": "…", "difference": "30000.00" }
    }
  },
  "leaderboard": [   // per-cashier rollup, ranked by revenue
    { "user_id": 12, "user_name": "Ali Karimov", "shifts": 10, "orders": 320,
      "revenue": "…", "cash": "…", "avg_order_value": "…",
      "cancelled": 4, "cancel_rate_pct": 1.25,
      "late_shifts": 2, "late_minutes_total": 53, "cash_variance": "-12000.00",
      "avg_prep_seconds": 512, "revenue_rank": 1 }
  ],
  "distribution": {
    "by_hour": [ { "hour": 0, "orders": 0, "revenue": "0.00" }, … 24 buckets ],
    "by_date": [ { "date": "2026-06-06", "orders": 73, "revenue": "…" }, … ],
    "peak_hour": 13
  },
  "shifts": [ /* full per-shift breakdown — see below */ ]
}
```

Each entry in `shifts[]` (per cashier shift):
```jsonc
{
  "shift_id": 88, "user_id": 12, "user_name": "Ali Karimov", "status": "COMPLETED",
  "start_time": "…", "end_time": "…", "duration_minutes": 480,
  "orders": { "total", "completed", "cancelled", "open", "preparing", "ready", "paid",
              "cancel_rate_pct", "by_type": { "hall", "delivery", "pickup" } },
  "items": { "units_sold", "line_items" },
  "money": { "revenue", "cash", "card", "avg_order_value",
             "payment_mix": { CASH, UZCARD, HUMO, PAYME, MIXED } },
  "discounts": { "total_given", "discounted_orders", "discount_rate_pct", "avg_discount_pct" },
  "speed": { "avg_prep_seconds", "orders_per_hour", "revenue_per_hour" },
  "punctuality": { "actual_start", "scheduled_start", "late_minutes", "is_late",
                   "attendance": { status, check_in, check_out, work_hours, overtime_hours } | null },
  "reconciliation": { "expected_cash", "actual_cash", "difference", "is_short", "is_over",
                      "notes", "reconciled_by", "reconciled_at" } | null
}
```

### `GET /api/admins/analytics/shifts/kitchen?from=&to=&user_id=&role=&target_prep_minutes=`

Kitchen/chef shifts. `role` selects which staff count as kitchen (default
`WAITER` — there's no dedicated chef role yet). `target_prep_minutes` sets the
"slow order" threshold (default 15). Prep metrics are **window-based** (the
kitchen output while that person was on shift) — per-item chef attribution
isn't tracked in the data model.

```jsonc
{
  "scope": "kitchen", "date_from": "…", "date_to": "…", "filtered_user_id": null,
  "summary": {
    "shift_count": 20, "distinct_staff": 3, "role": "WAITER",
    "by_status": { … }, "total_hours": 150.0, "avg_shift_minutes": 450.0,
    "orders_in_window": 880, "orders_readied": 860, "orders_pending": 20,
    "completion_rate_pct": 97.7,
    "items_prepared": 2600, "items_per_hour": 17.3,
    "prep_time": { "avg_seconds": 520, "best_shift_avg_seconds": 300,
                   "worst_shift_avg_seconds": 1100, "slow_orders": 64,
                   "slow_rate_pct": 7.4, "target_seconds": 900 },
    "punctuality": { same shape as cashier (on_time/late/late_arrivals…) }
  },
  "distribution": { by_hour, by_date, peak_hour },
  "shifts": [
    { "shift_id", "user_id", "user_name", "status", "start_time", "end_time", "duration_minutes",
      "orders_in_window", "orders_readied", "orders_pending", "completion_rate_pct",
      "items_prepared": { "units", "line_items" },
      "prep_time": { "avg_seconds", "median_seconds", "fastest_seconds", "slowest_seconds",
                     "slow_orders", "slow_rate_pct", "target_seconds" },
      "throughput": { "orders_per_hour", "items_per_hour" },
      "punctuality": { … } }
  ]
}
```

**Notes / caveats**
- All money values are strings (avoid float rounding). Seconds are integers.
- `late_minutes`/`is_late` are `null` when a shift has no `shift_template`
  attached (no schedule to compare against). `attendance` is `null` when the HR
  module has no record for that person/day.
- Existing analytics endpoints are unchanged:
  `GET /api/admins/analytics/shifts/<shift_id>` and `…/menu-engineering`.

---

## Migrations

This drop ships migrations (`MANAGER` role, `Product.is_instant`). They run
automatically on container start (`entrypoint.sh` → `migrate`). No FE action.

---

## 8. Treasury — SAFE + BANK (NEW) & inkassa bug fix

Two money pots sit above the till drawer (`CashRegister`):
- **SAFE** — physical cash moved out of the registers by inkassa.
- **BANK** — electronic money (card / Payme), never in the drawer.

### Inkassa fix
`POST /api/admins/inkassa/perform` — **bug fixed**: the register holds only
cash, so now **only the CASH amount leaves the register** (previously card
amounts were wrongly subtracted from the cash drawer and could trip the
"insufficient balance" check). On a successful inkassa the money is routed:
**cash → SAFE, all card amounts → BANK** automatically.

Body unchanged (`{ "cash": "...", "uzcard": "...", "humo": "...", "payme": "...", "notes": "" }`).
New response fields:
```jsonc
{
  "amount_removed": "400.00",      // cash that actually left the register
  "total_collected": "800.00",
  "cash_to_safe": "400.00",
  "card_to_bank": "400.00",
  "balance_before": "1000.00",     // register (cash) before
  "balance_after": "600.00",       // register (cash) after — only cash removed
  "inkassas": [ … ]
}
```

### `GET /api/admins/treasury/accounts` (manager)
```jsonc
{ "accounts": {
    "SAFE": { "kind": "SAFE", "balance": "995000.00", "last_updated": "…" },
    "BANK": { "kind": "BANK", "balance": "320000.00", "last_updated": "…" } } }
```

### `POST /api/admins/treasury/transfer` (manager)
Move money between accounts with a transaction fee. Convention: source loses
`amount`; destination is credited `amount - fee`; `fee` is the bank/processor
charge. Send `Idempotency-Key` header to make retries safe.
```jsonc
// Body — e.g. withdraw cash from the bank
{ "from": "BANK", "to": "SAFE", "amount": "1000000", "fee": "5000", "description": "ATM withdrawal" }
// → BANK -1,000,000, SAFE +995,000
```
```jsonc
// data
{ "amount": "1000000.00", "fee": "5000.00", "credited": "995000.00",
  "from": { "kind": "BANK", "balance": "…" }, "to": { "kind": "SAFE", "balance": "…" },
  "transactions": [ {TRANSFER_OUT…}, {TRANSFER_IN…} ] }
```
`422` if `from==to`, amount ≤ 0, fee < 0, fee > amount, or insufficient funds.

### `POST /api/admins/treasury/expense` (cashier / manager / admin)
Spend money out of SAFE or BANK. Open to cashiers too (not just managers).
```jsonc
{ "account": "SAFE", "amount": "150000", "category": "supplies", "description": "napkins" }
// → SAFE -150,000 ; 201 with { account, transaction }
```
`422` on bad account / amount ≤ 0 / insufficient funds.

### `GET /api/admins/treasury/history?account=&type=&page=&per_page=` (manager)
Append-only ledger. Filter by `account` (SAFE/BANK) and `type`
(`INKASSA, TRANSFER_IN, TRANSFER_OUT, FEE, EXPENSE, ADJUSTMENT`). Each row:
```jsonc
{ "id", "account", "type", "delta", "fee", "balance_before", "balance_after",
  "counterparty", "category", "description", "reference_type", "reference_id",
  "performed_by", "created_at" }
```

---

## 9. Shift handover report (NEW)

When a cashier ends a shift and hands over to the manager, this gives the
manager the full picture in one call.

`GET /api/admins/analytics/shifts/<shift_id>/report` (manager)

```jsonc
{
  "cashier": { "id": 12, "name": "Ali Karimov" },
  "shift": { /* the full per-shift KPIs from §7: orders breakdown, money
               (cash vs card + payment_mix), discounts, avg order value,
               speed, punctuality, cash reconciliation */ },
  "receipt_count": 84,
  "receipts": [   // every receipt taken during the shift
    { "order_id": 501, "display_id": 14, "status": "COMPLETED", "order_type": "HALL",
      "is_paid": true, "payment_method": "CASH", "total_amount": "120000.00",
      "discount_amount": "0.00", "discount_percent": "0",
      "line_items": 3, "units": 5, "created_at": "…", "paid_at": "…" }
  ],
  "products": [   // what sold, sorted by quantity
    { "product_id": 7, "name": "Lavash", "units_sold": 40,
      "times_sold": 31,        // distinct orders it appeared in
      "revenue": "1600000.00" }
  ],
  "best_seller": { … first product … },
  "distribution": { "by_hour": [ {hour, orders, revenue} … 24 ], "by_date": [...], "peak_hour": 13 },
  "peak_hour": 13
}
```

"How much money the cashier has" → `shift.money.cash`, `shift.money.card`, and
`shift.money.payment_mix`. Averages → `shift.money.avg_order_value`; peak hours
→ `distribution.by_hour` / `peak_hour`; all receipts → `receipts[]`; what/how
many sold → `products[]`.

---

## 10. Shift stats now show before the shift is finalized (bug fix)

A shift's `total_orders` / `total_revenue` / `cash_collected` used to be written
only when `end_shift` runs, so an in-progress (`ACTIVE`) shift serialized as
all-zero — "no stats". Now `_serialize_shift` (used by `GET /shifts`,
`/shifts/active`, `/shifts/<id>`) computes those **live** for `ACTIVE` shifts
(clock running to now), so stats appear immediately. `COMPLETED`/`ABANDONED`
shifts keep their frozen end-of-shift numbers. New field on every shift:

```jsonc
{ "status": "ACTIVE", "total_orders": 12, "total_revenue": "1850000.00",
  "cash_collected": "1200000.00", "is_live_stats": true }
```
`is_live_stats: true` ⇒ figures are live (not yet finalized). The deep
analytics and the handover report (§7/§9) already compute live and are
available at any stage (active → ended → confirmed).

---

## 11. Shift lifecycle: explicit ENDED state (fix "ended shows confirmed")

`Shift.status` now has a distinct **`ENDED`** between `ACTIVE` and `COMPLETED`:

```
ACTIVE  →  (POST /shifts/<id>/end)  →  ENDED  →  (POST /shifts/<id>/reconcile)  →  COMPLETED
```

- **`POST /shifts/<id>/end`** now returns `status: "ENDED"` (was `COMPLETED`).
  The shift is closed, its totals are frozen and **visible** — this is the
  state the manager reviews. Map this to your "Ended" label.
- **`POST /shifts/<id>/reconcile`** now requires the shift to be `ENDED` and,
  on success, flips it to `COMPLETED` (your "Confirmed" label). It still
  errors if called before the shift is ended.
- `ABANDONED` unchanged.

So a just-ended shift is `ENDED` (not `COMPLETED`), and stats are available
immediately (`ENDED`/`COMPLETED` use the frozen end-of-shift figures; `ACTIVE`
computes live per §10). Analytics `by_status` now includes an `ENDED` bucket.

---

## 12. Why shift stats could look empty (fixes)

Shift stats are attributed to a shift by `order.cashier_id` + time window, so an
order with no `cashier_id` counts toward nobody's shift. Two fixes:

1. **Orders rung up by a MANAGER are now attributed** to that manager
   (`order.cashier_id`), exactly like a cashier. Previously attribution only
   happened for `role == 'CASHIER'`, so a manager's orders had `cashier_id =
   null` and their shift showed zero stats. Applies to create / add-item /
   status / pay / mark-ready, etc.
2. **The older analytics endpoints are now manager-accessible**:
   `GET /api/admins/analytics/shifts/<id>` and `…/menu-engineering` moved from
   admin-only to `manager_required` (a manager calling them no longer gets 403).

Backend computation itself is verified correct: start shift → cashier/manager
rings & pays an order → end shift → the shift detail, deep analytics, and
handover report all show the orders, revenue and cash/card split.

---

## 13. Expenses open to cashiers (both expense systems)

Cashiers can now **file expenses**, not just admins:

- **Treasury expense** `POST /api/admins/treasury/expense` — `pos_staff_required`
  (CASHIER/MANAGER/ADMIN). Spends straight from SAFE/BANK.
- **HR expense** `GET/POST /api/admins/hr/expenses/` — now `pos_staff_required`;
  cashiers can create (status starts `PENDING`) and view. Reading
  `GET /api/admins/hr/expense-categories/` is open to cashiers too so they can
  pick a category.

Still restricted (manager/admin): creating expense **categories**, and
**approving / rejecting / paying** HR expenses, and editing/deleting expenses.

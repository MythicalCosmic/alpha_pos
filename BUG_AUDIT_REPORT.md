# Alpha POS — codebase audit, 2026-05-26

Scope: ~50K LOC of Python across 9 apps. Four parallel passes scanned for
security, functional bugs, dead code, unfinished features. Every finding
below was opened in source and verified — false positives the agents
flagged are listed at the end with the reason they were dismissed.

## TL;DR — what's actually broken

Three real bugs, eight dead imports, one documented feature gap.

| # | Severity | Where | What |
|---|---|---|---|
| 1 | HIGH | `admins/services/order_service.py:225` | `include_deleted=True` discards every filter (date / status / cashier / payment) and lists every soft-deleted order in the system |
| 2 | HIGH | `customers/services/order_service.py:52` | `.values()` on prefetched items defeats `prefetch_related`; busy `client_display` issues an extra query per order (200+ extra hits at peak) |
| 3 | HIGH | `customers/services/order_service.py:681` | `mark_order_ready` is not `@transaction.atomic`; failure between `order.save()` and bulk-item-update leaves order=READY with items still PREPARING |
| 4 | LOW × 8 | various views/services | Unused imports — `require_http_methods`, `get_session_key`, `ServiceResponse`, `rate_limit`, `json`, `permission_required`, `Count`, `timedelta` |
| 5 | DEFERRED | `notifications/services/telegram_bot.py:506` | Payme checkout creates `is_paid=False` orders with no settlement path. ROADMAP marks this 🟡 partial pending merchant creds — not a bug, intentional |

Everything else the agents flagged was either intentional design (and
documented in code) or a false positive — written up at the bottom.

---

## HIGH — fix now

### H1. `include_deleted=True` blows away every other filter

**File:** `admins/services/order_service.py:225-229`

```python
if include_deleted:
    from base.models import Order
    qs = Order.objects.select_related(
        'user', 'cashier', 'delivery_person'
    ).prefetch_related('items__product__category').order_by(order_by)
```

The function builds a properly filtered queryset via
`OrderRepository.build_filtered_queryset(...)` at line 213, then when
`include_deleted=True` is requested it throws the whole thing away and
rebuilds from `Order.objects` with zero filters. Caller asks for
"deleted orders from cashier=42 in May" → gets every deleted order ever.

**Fix:** drive include-deleted through the repository so it composes
with the other filters (or re-apply the filters after switching
managers).

### H2. `.values()` defeats the prefetch in the customer order list

**File:** `customers/services/order_service.py:52-55`

```python
'items': list(order.items.values(
    'id', 'product__id', 'product__name', 'product__category__id',
    'product__category__name', 'quantity', 'detail', 'price', 'ready_at'
)),
```

The list endpoint calls `OrderRepository.build_filtered_queryset` which
prefetches `items__product__category`. `.values()` issues a **fresh**
query that ignores the prefetch cache. The admin service already fixed
this at line 61-77 (comment in file explicitly says don't use
`.values()`); the customer service still does it. `client_display`
returns up to `DISPLAY_LIMIT = 200` orders → 200+ extra queries per
display refresh.

**Fix:** iterate `order.items.all()` directly the way the admin service
does.

### H3. `mark_order_ready` missing `@transaction.atomic`

**File:** `customers/services/order_service.py:681-713`

```python
@staticmethod
def mark_order_ready(order_id, cashier_id=None, user_id=None, user_role=None):
    ...
    order.status = 'READY'
    order.ready_at = now
    order.save(update_fields=['status', 'ready_at'])
    order.items.filter(ready_at__isnull=True).update(ready_at=now)
    ...
```

`order.save()` commits, then the bulk update of items runs in a separate
implicit transaction. Any DB hiccup between the two leaves the order
flagged READY while items remain PREPARING → kitchen display says
"3/5 ready" but the order is in the READY queue. The admin equivalent
(`admins/services/order_service.py:647`) already has the decorator.

**Fix:** wrap with `@transaction.atomic`.

---

## LOW — dead imports

Verified by direct read; each line listed has the import and zero
references in the file.

| File | Line | Symbol |
|---|---|---|
| `stock/views/ai_views.py` | 4 | `require_http_methods` |
| `admins/views/auth_views.py` | 4 | `get_session_key` |
| `admins/views/auth_views.py` | 5 | `ServiceResponse` |
| `admins/views/order_views.py` | 6 | `rate_limit` |
| `admins/views/user_views.py` | 1 | `import json` |
| `admins/views/user_views.py` | 9 | `permission_required` |
| `admins/services/forecast_service.py` | 16 | `Count` |
| `admins/services/analytics_service.py` | 8 | `timedelta` |

`pyflakes` / `ruff` are not installed in this env — these were found by
direct grep. Recommend adding `ruff` to `requirements-dev.txt` to catch
this class going forward.

---

## DEFERRED — known partial feature

`notifications/services/telegram_bot.py:506-524` — Telegram bot
`_order_checkout` creates orders with `is_paid=False` and
`payment_method=None`. No Payme webhook / callback exists to flip the
payment. ROADMAP already marks this 🟡 partial pending merchant creds.
Behavior is correct given the constraint: take the order, leave
settlement to manual reconciliation until creds arrive. Not a bug.

Per ROADMAP and verified in code, these remain `🚫` (blocked on vendor
access) and are out of scope for this audit:
- Aggregator ingestion (Yandex/Wolt/Express24)
- Fiscal printer / OFD
- Payme / Click / Apelsin direct
- Mobile shell

---

## Dismissed — agent flagged, verified not a bug

### Loyalty race condition (`notifications/services/loyalty_service.py:70`)

Agent claimed concurrent orders for the same phone clobber each other.
**False positive.** The flow is: insert `OrderLoyaltyCredit` (unique on
`order_id`) as the per-order dedup guard, then `get_or_create` the
account, then **F-expression update** the balance. F-expressions are
atomic at the SQL level; the read-modify-write race the agent
described doesn't exist. The code's own comment at line 71-74
explicitly documents this design.

### Stock-handler `try/except Exception` in order creation

`admins/services/order_service.py:355` and the customer equivalent at
line 351 swallow stock-handler exceptions during order create. The
comment in `customers/services/order_service.py:352` reads
`'non-critical stock-handler error in order flow'`. This is intentional
— order creation must not fail if the stock subsystem hiccups; the
order is logged and reconciled later. Could be reviewed as a product
decision but it's not a code defect.

### `_check_rate_limit` fails open on cache exception

`stock/services/ai_assistant_service.py:1099-1120` — comment at line
1103 says *"Failing open on cache errors is acceptable here since the
AI assistant is admin-gated."* Documented intent.

### `discount_amount <= 0` rejection

`discounts/services/discount_service.py:432` — agent claimed 0% promos
should be accepted. But when a BUY_X_GET_Y or FREE_ITEM rule yields a
0 amount it means "no qualifying items" — rejecting with "Discount
does not apply to this order" is the correct behavior. Not a bug.

### Sync `WRITE_DENYLIST` fallback allows-all for new models

`base/services/sync/receiver.py:78-92` — agent suggested fallback
should deny-all. But the system is sync-based replication; deny-all
would break sync for every new model. Comment at line 75-77 explicitly
notes the fallback is the floor (User is locked down), and new models
should declare their own `SYNC_WRITE_DENYLIST`. Design choice,
documented.

### Salary `by_status` dict truncation

`hr/services/salary_service.py:397-402` — agent claimed
`dict(qs.values_list("status").annotate(...))` truncates. False —
`values_list("status")` after annotate emits one row per status (the
group key), so dict() sees unique keys. Worst issue here is the
variable name `count` for a Sum, which is a naming nit.

### License DEBUG-mode plaintext heartbeat

`alpha_pos/settings.py:352-363` — agent claimed an attacker can MITM
the heartbeat in DEBUG. DEBUG mode is dev-only and the project
explicitly requires production to set `DEBUG=False`. Not exploitable
in any deployed scenario.

### QR token reuse after table re-creation

`notifications/services/qr_order_service.py:52` — the scenario
requires (a) deleting a table, (b) creating a new one that re-uses the
same UUID. Django UUIDs are random; UUID collision is not a realistic
threat. Skipping.

### Idempotency key cross-module collision

`base/security/idempotency.py:53` — agent claimed `view_func.__module__`
qualification could collide. View functions in different modules with
the same name plus the same idempotency key plus the same body hash
plus the same auth — would still produce a cached response that only
matches the request that originally produced it. Not exploitable.

---

## Next steps

Fixes for H1, H2, H3 and the eight dead imports follow this report in
the same change. Total surface ~12 small edits.

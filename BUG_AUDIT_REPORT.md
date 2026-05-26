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

---

# Deep-pass follow-up (added 2026-05-26)

After the surface scan above shipped, two general-purpose agents did a
full-file deep read of the sync engine and stock services — the two
most concurrency-heavy surfaces. The full test suite (267 tests) was
run and passes; `ruff` was installed and 127 unused imports were
auto-removed across the codebase. Below is a triage of the deep-pass
findings.

## Fixed in this same pass

### S15. `release_reservation` idempotency skip was dead code

**Files:** `stock/services/order_service.py:377-387`, `stock/services/level_service.py:367-414`

The `release_reservations` flow checks for prior `RESERVATION_RELEASE`
transactions with `reference_type="Order", reference_id=order_id` to
skip duplicate releases. But `StockLevelService.release_reservation`
never wrote `reference_type`/`reference_id` on the RELEASE
transactions — only on the original RESERVATION (line 356-358 of
level_service.py). So the idempotency check could never match a prior
release, and a double-call would fall through into the for-loop, hit
the "Cannot release X: only Y reserved" error path at level_service.py
line 385-388, and return 400 instead of a clean idempotent skip.

**Fix:** added `reference_type` / `reference_id` kwargs to
`release_reservation`, plumbed them into the transaction row, and the
caller in `OrderStockService.release_reservations` now passes
`("Order", order_id)`. Stock tests pass.

### Dead variable: `order_subtotal`

**File:** `discounts/services/discount_service.py:278`

`calculate_discount` computed `order_subtotal` and never used it. The
function uses `applicable_subtotal` for every code path. Removed.

### Dead variables: `page` / `per_page` in stock category list

**File:** `stock/views/category_views.py:14-19`

Category list view extracted `page = safe_page(request)` and
`per_page = safe_per_page(request, 20)` but the service doesn't
accept them and the response is unpaginated. Removed the lines and
added a comment that the endpoint is intentionally unpaginated.

### 127 unused imports across the project

`ruff check --select F401 --fix` removed unused imports from 50+
files. `__init__.py` re-exports were preserved (`--exclude
'**/__init__.py'`). Full test suite re-run: 267 tests pass.

## Open follow-ups (deferred, not blocking ship)

These are real findings worth fixing, but each one is bigger than a
surgical edit and needs separate review. Listing severity + scope so
they can be triaged.

### Sync — open

| ID | Severity | Surface | Summary |
|---|---|---|---|
| FS1 | HIGH | `base/services/sync/receiver.py:240-266` | `_create_or_update` has no `transaction.atomic` + `select_for_update` per record. Two concurrent receives of the same UUID can both pass `_should_replace` against the old version and the later writer wins blindly, defeating the deterministic tiebreaker. Fix: wrap the per-record body in atomic + `select_for_update`. |
| FS2 | HIGH | `base/services/sync/service.py:60-95` | `transport.send_batch` returns `success=True` if `created>0 OR updated>0`, even with `errors[]` non-empty. The service then extends `synced_uuids` with **all** batch UUIDs and deletes them from the queue — the failed ones are lost forever. Fix: server must echo per-UUID outcome, client removes only successes from queue. |
| FS3 | HIGH | `base/models.py:163-237` (default `from_sync_dict`) | The default `from_sync_dict` does `setattr` on data keys with a `hasattr` guard, **without** the `_resolve_foreign_keys` UUID→instance step that the receive-path `_create_or_update` does. Stock / HR / discounts models inherit the default; pull-from-cloud creates rows with every FK as NULL on those models. Only Order / OrderItem / Product / Inkassa / User / AuditLog override correctly. Severity is HIGH only if the pull path is enabled (`get_pull_enabled()` flag); LOW if branches are push-only. Fix: move the FK-UUID resolution into the SyncMixin default, or have every SyncMixin subclass override `from_sync_dict`. |
| FS4 | MEDIUM | `base/models.py:240-265` + `base/services/sync/receiver.py:49-53` | Naive vs aware datetime comparison in `_should_replace` tiebreaker. `dateutil.parser.parse` returns naive when ISO string has no offset; comparing with TZ-aware crashes the whole record-receive with TypeError. Fix: `make_aware` on parse if naive. |
| FS5 | MEDIUM | `base/models.py:73-79` | `SyncMixin.delete()` soft-deletes the parent only — `Order.delete()` doesn't cascade to `OrderItem`. After sync, peer has `Order.is_deleted=True` with live items. Fix: add `SYNC_CASCADE_DELETE = ('items', ...)` per model. |
| FS6 | MEDIUM | `base/models.py:879-923` (`Inkassa.from_sync_dict`) | Inkassa is documented as immutable but `from_sync_dict` does `cls.objects.get(uuid=uuid_val)` and updates in place. A peer that knows an Inkassa UUID can flip `inkass_type` (not denylisted). Fix: skip update on receive (`return instance, 'skipped'` if already exists) — Inkassa is append-only. |
| FS7 | LOW | `base/models.py:240-265` | Soft-delete is not sticky. Branch-A soft-deletes at v3 → branch-B edits the same row at v3 with newer updated_at → branch-B's payload (with `is_deleted=False`) wins and **resurrects** the soft-delete. Fix: in `_should_replace`, deleted side always wins regardless of timestamp. |
| FS8 | LOW | `base/models.py:63,109-114` + `base/services/sync/queue.py:42-53` | `transaction.on_commit(self._queue_for_sync)` only logs on failure. If the on_commit callback raises (DB conn lost, queue table locked, etc.) the row is live but never enters the sync queue. No reconciler exists. Fix: periodic job that scans for `synced_at IS NULL` and re-queues. |
| FS9 | LOW | `base/services/sync/receiver.py:40-64` | `_clean_field_value` accepts arbitrary values for CharField/JSONField with no `field.choices` enforcement. A peer can push `Order.status = "OWNED_BY_ATTACKER"` — denylist blocks money fields but not status. Defense-in-depth: call `field.run_validators(value)`. |

### Stock — open

| ID | Severity | Surface | Summary |
|---|---|---|---|
| SS1 | HIGH | `stock/services/count_service.py:324-362, 490-532` | Stock count TOCTOU: `_populate_count_items` snapshots `system_quantity` at count-creation time; concurrent sales/receipts mutate `StockLevel.quantity` between creation and `_apply_adjustments`. The variance is then applied as a delta on top of the *now-newer* level → ghost shrinkage. Concrete: count at 09:00 (sys=100), sell 5 by 11:00 (now 95), physical=100, variance=0 recorded → level stays 95 although physical=100. Fix: either snapshot at apply-time, or take a "freeze" lock on items being counted. |
| SS2 | MEDIUM | `stock/services/production_service.py:441-445, 615-678, 723-725` | `_consume_ingredients` and `_create_output` use nested `@transaction.atomic` + `set_rollback(True)` on the inner — which only marks the inner savepoint for rollback. The outer `complete()` then continues with `_create_output`, which hits `TransactionManagementError` because the savepoint is in error state. Caller gets opaque error instead of a clean failure response. Fix: drop the inner atomic, let the outer own it; OR raise instead of `set_rollback + return`. |
| SS3 | LOW | `stock/services/purchase_service.py:862-881` | `_update_po_status` doesn't lock the PO row at receiving completion. Two concurrent receivings can both compute status → one overwrites the other. Race window where one sees PARTIAL and overwrites a concurrent RECEIVED → PO stuck in PARTIAL. Fix: `select_for_update` on the PO row at `_update_po_status` entry. |
| SS4 | LOW | `stock/repositories/level.py:31-58` | `get_or_create_level` and the `select_for_update` path don't filter `is_deleted=False`. No current writer soft-deletes StockLevel, so this is latent — would bite if/when sync reconciliation does. |
| SS5 | COSMETIC | `stock/services/{purchase,production}_service.py` | Decimal totals computed without `.quantize(Decimal('0.01'))` — stored to 4 dp, drift sub-soum on big sums. Cosmetic only since UZS rounding is at display. |

## Recommendation

For next ship: nothing in the **open follow-ups** list is a "shipping
catastrophe" — they're real bugs but each requires its own review and
test pass. The three things I'd resolve before a high-stakes ship:

1. **FS3** if you actually use the cloud→branch pull path. If branches
   are push-only, skip it.
2. **SS1** if any venue will run stock counts during open hours
   (almost certainly yes for any real restaurant).
3. **FS6** since Inkassa is the cash ledger and any tampering there
   has financial consequences.

The remaining ~12 are real but lower priority — fix in subsequent
passes.


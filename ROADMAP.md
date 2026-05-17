# alpha_pos — product roadmap

Updated 2026-05-17. Status markers: ✅ shipped · 🟡 partial · ⬜ not started ·
🚫 deferred (needs vendor / out of scope).

## Market frame

Restaurant POS, Uzbek / CIS market. Competing with Iiko and R-Keeper
(both heavy and expensive) and against the "spreadsheet + paper"
status quo at smaller venues. Local market context that shapes every
feature decision: PAYME / UZCARD / HUMO are table stakes, 1C is the
de facto accounting backend, Telegram is where customers actually
are.

**Wedge:** modern + multi-branch-native + cheaper to operate than
the incumbents. Already strong on operations side (multi-branch sync,
recipe-driven stock, HR, discount engine, AI hook). Weak / missing
on customer-facing layer.

## Tier 1 — customer-facing (highest leverage, biggest gap today)

- **Telegram ordering bot.** 🟡 — webhook + dispatcher + /start /menu
  /login /status /order /loyalty all shipped, with inline-keyboard cart
  (callback_query routing). Payme checkout still pending real-merchant
  credentials. Service: `notifications/services/telegram_bot.py`,
  `cart_service.py`; webhook at `/api/telegram/webhook/`.
- **QR menu + table self-ordering.** ✅ — signed token per table,
  public endpoints at `/api/qr/menu/<token>/` and `/api/qr/order/<token>/`.
  Admin mints tokens via `/api/admins/notifications/qr/tables/<id>/token/`.
  Frontend page / printable QR generator still to do (operator currently
  builds the QR from the URL the mint endpoint returns).
- **Loyalty / digital stamp cards.** ✅ — LoyaltySettings + LoyaltyAccount
  + auto-accrual on COMPLETED + paid orders (idempotent via
  OrderLoyaltyCredit). /loyalty in the bot, admin API for redeem at
  `/api/admins/notifications/loyalty/...`.

## Tier 2 — integrations (sticky, reduces switching cost)

- **1C accounting export.** ✅ — `GET /api/admins/exports/1c?from=&to=`
  returns CommerceML 2.05-flavored XML with Cyrillic element names.
  Cancelled orders excluded; unpaid completed excluded by default
  (?include_unpaid=1 override).
- **Yandex Eats / Wolt / Express24 ingestion.** 🚫 (this session) —
  needs aggregator API credentials. When unblocked, the order_type
  enum already has the slot and the queue worker pattern in
  `notifications/services/worker.py` is reusable for ingestion polling.
- **Fiscal printer / OFD (online cash register) integration.** 🚫
  (this session) — needs an actual Uzbek OFD provider SDK + test
  fiscal device. The Order model already records payment_method which
  the provider integration will consume at fiscalization time.
- **Payme / Click / Apelsin direct integration.** 🚫 (this session) —
  needs merchant credentials + sandbox. The QR public order endpoint
  already lays the groundwork: `Order.payment_method` is per-order and
  a webhook handler can flip is_paid + payment_method on Payme callback.

## Tier 3 — leverage the data we already have (where most POSes are weak)

- **Owner mobile app.** 🟡 — API side shipped:
  `GET /api/admins/dashboard/today` bundles revenue + top products +
  low-stock count + who's clocked in. Native mobile shell is a separate
  repo / project, not in scope here.
- **Demand forecasting.** ✅ — `GET /api/admins/forecast/tomorrow` aggregates
  30d of order history by product × weekday × hour, sends to Gemini, parses
  JSON predictions. Rate-limited 5/min per IP.
- **Shift performance scoring.** ✅ —
  `GET /api/admins/analytics/shifts/<id>` returns orders/h, avg prep,
  cancel rate, revenue, etc. for any shift.
- **Menu engineering analytics.** ✅ —
  `GET /api/admins/analytics/menu-engineering?from=&to=` returns the
  Star/Plowhorse/Puzzle/Dog matrix with configurable cogs_fraction
  (default 0.35 since we don't have recipe-cost linkage on Product yet).

## Tier 4 — physical / hardware (capital-intensive, defer)

- Self-service kiosks (in-store ordering tablets). 🚫
- Kitchen display screens — the `chef_display` route already
  exists; productize it. ⬜
- Bluetooth scales for weight-priced items. 🚫
- Bluetooth label printers for delivery / takeaway. 🚫
- Recommended hardware bundle for new venue installs. 🚫

## Explicitly NOT on the list

- Generic web "menu site" — crowded, low-margin, doesn't move the
  needle.
- Branded POS hardware kit — capital-heavy distraction; software
  density matters more first.
- "AI agent" gimmick features — marketing fluff. The AI work that
  matters is forecasting and operational queries (already started
  with the stock assistant).

## My single bet, if forced to pick one

**Telegram ordering bot + loyalty layer.** Possible *only* because
of where the product is geographically positioned. Technical lift is
moderate — Telegram, discount engine, and auth are already there.
Changes what's being sold from "back-office software" to "customer
acquisition tool." That's the pitch that flips margins.

Tier 2 (1C, fiscal printer) is what keeps customers from leaving;
Tier 1 is what brings them in the first place.

## Open questions to figure out before starting any of these

- Who's the actual buyer? Owner vs IT vs head waiter? Different
  features matter to each.
- What's the current customer concentration? Single big chain vs
  many small venues? Roadmap shifts.
- Pricing model — per terminal, per branch, per transaction, flat?
  Influences which features are paywalled vs core.
- Hardware partnership opportunities (fiscal printers, terminals)
  vs ship-software-only.

## Next session — concrete unblocks needed

The five 🚫 items are blocked on real-world access, not engineering
effort. Each needs:

- **Yandex Eats / Wolt / Express24 ingestion.** Partner API credentials
  for whichever aggregator the pilot venue uses + sandbox endpoints.
- **Fiscal printer / OFD.** Pick one Uzbek OFD provider, get their SDK
  + a test fiscal device on the desk.
- **Payme / Click / Apelsin.** Merchant account credentials + sandbox
  URL for one of them (Payme first since `Order.payment_method` already
  has the enum value).
- **Owner mobile app shell.** Decide native vs PWA. The API exists.
- **Recipe-cost linkage on Product.** Would let menu engineering use
  real margin instead of the cogs_fraction proxy. The stock app already
  has Recipe + ProductStockLink; needs a small surface in the admin API
  to connect a Product to a Recipe and propagate per-unit cost into the
  matrix.

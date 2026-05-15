# alpha_pos — product roadmap exploration

Brainstorm, not commitment. Updated 2026-05-16. Edit freely.

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

- **Telegram ordering bot.** Menu / cart / Payme checkout / status
  push. We already integrate Telegram for staff notifications, so
  the auth + bot infra is partly there. This is the one feature
  that flips the pitch from "back-office software" to "customer
  acquisition tool" — that changes margins.
- **QR menu + table self-ordering.** Customer scans QR, orders, pays
  in-app. Massive labor savings for the venue. `Table` and `Place`
  models already exist; mostly UI work + a public order endpoint.
- **Loyalty / digital stamp cards.** `Discount` engine already has
  per-user usage tracking and the `usage_per_user` cap. Stamp cards
  are basically a discount with an accumulator. Bones exist.

## Tier 2 — integrations (sticky, reduces switching cost)

- **1C accounting export.** Non-negotiable in this market. If the
  venue's accountant has to re-key our numbers into 1C, we lose to
  whoever exports cleanly.
- **Yandex Eats / Wolt / Express24 ingestion.** Treat aggregator
  orders as a first-class order source so the kitchen sees one
  unified queue instead of five tablets stacked next to the line.
- **Fiscal printer / OFD (online cash register) integration.**
  Required by UZ law. Without it the venue has to maintain a
  parallel system.
- **Payme / Click / Apelsin direct integration.** Today the cash
  register doesn't track per-method; we just added `payment_method`
  to `Order`. Wiring up real payment terminal callbacks is the next
  step.

## Tier 3 — leverage the data we already have (where most POSes are weak)

- **Owner mobile app.** Live revenue, low-stock alerts,
  top-products today, "who's clocked in right now," push
  notifications. Sells itself in a demo. We already collect every
  piece of data this needs.
- **Demand forecasting.** Order history + recipes + stock levels
  fed to Gemini (already wired): "what should I prep tomorrow
  morning?" This is what Iiko charges enterprise prices for.
- **Shift performance scoring.** We already track `cashier_id`,
  per-order prep times, cancellation rates per shift. Surface as a
  manager view; almost free given the data model.
- **Menu engineering analytics.** Star / Plowhorse / Puzzle / Dog
  matrix on margin × popularity. Tells the chef what to push and
  what to cut.

## Tier 4 — physical / hardware (capital-intensive, defer)

- Self-service kiosks (in-store ordering tablets).
- Kitchen display screens — the `chef_display` route already
  exists; productize it.
- Bluetooth scales for weight-priced items.
- Bluetooth label printers for delivery / takeaway.
- Recommended hardware bundle for new venue installs.

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

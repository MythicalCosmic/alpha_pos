# What's new in Alpha POS

A plain-language summary of everything that landed today (2026-05-17).
Nothing in this file is technical — it's about what your restaurant
can now actually *do* that it couldn't yesterday.

---

## For your customers

Your customers can now do all of this from Telegram, without ever
talking to a waiter:

- **Browse the menu.** They send `/menu` to your bot and see your
  categories. Tap one and they see prices for every dish in that
  category.
- **Share their phone once.** They send `/login` and tap one button
  — Telegram shares their phone number with the bot. We only ever
  accept their own number, not someone else's.
- **Check their orders.** `/status` shows their last 10 orders from
  the past 30 days — order number, what stage it's at (preparing,
  ready, paid), and the total.
- **Build a cart and place an order.** `/order` opens their cart.
  They tap buttons to add items, change quantity, or remove. One
  big "✅ Buyurtma" button places the order. Your cashier sees a
  new open order at the till immediately.
- **Earn loyalty stamps.** Every paid + completed order earns a stamp
  automatically. They send `/loyalty` to see how many stamps they have
  and how many more they need until the next free reward (you set the
  threshold and the reward name in the admin panel).

Customers don't need to install anything. They already have Telegram.

## For walk-in / dine-in customers

You can now print a **QR sticker for each table**. When a customer scans
it, they get a menu page tied to that exact table. Their order goes
straight into your kitchen queue as a normal "in-hall" order, with the
table number attached — no waiter needed for ordering.

To set this up, your admin generates a unique link for each table once,
and you print a QR sticker pointing to it. The sticker keeps working
forever (no expiry) and only ever places orders at *that* table — even
if someone tries to mess with the link, it won't redirect to a
different table.

## For your manager / owner

- **One-screen daily snapshot.** A single dashboard shows today's
  revenue, how many orders, how many paid vs cancelled, the top 5
  best-selling products today, how many stock items are running low,
  and who's currently clocked in on shift.
- **Per-shift scorecard.** Pick any shift (past or current) and see
  that cashier's orders, completion rate, cancel rate, average prep
  time, revenue, and orders-per-hour. Useful for performance reviews
  and spotting training needs.
- **Menu engineering.** A classic Star / Plowhorse / Puzzle / Dog
  analysis across your menu over any date range:
  - **Stars** — popular *and* profitable. Protect these. Don't change.
  - **Plowhorses** — popular but low margin. Try a small price increase
    or cheaper ingredients.
  - **Puzzles** — high margin but nobody orders them. Promote more,
    move them up on the menu.
  - **Dogs** — low margin and unpopular. Consider removing.
- **Demand forecast for tomorrow.** A "what should I prep tomorrow
  morning?" report. It looks at the last 30 days of orders (broken
  down by day-of-week and hour) and suggests prep quantities per
  product. Backed by Gemini AI.

## For your accountant

- **1C export.** Download an XML file of all paid completed orders
  in any date range, in a format your accountant's 1C config can
  ingest directly. Cyrillic field names, CommerceML format. No
  more re-typing receipts into 1C by hand.

## For your setup / IT

A few small admin things now exist that make all the above work:

- **Loyalty settings.** Decide how many stamps per completed order
  (default 1), how many stamps for one reward (default 10), and the
  reward description (default "Bepul ichimlik"). All editable from
  the admin API without redeploying.
- **Customer-facing bot text.** Every message the Telegram bot sends
  to customers (menu intro, login prompt, "you placed order #42",
  etc.) is editable from the same admin panel you use for staff
  notifications. Change wording, translate, add emoji — no developer
  needed.
- **Cashiers can redeem rewards.** At the till, when a customer claims
  a free item, the cashier hits the redeem endpoint with the
  customer's phone and the system decrements their stamp balance.

---

## What's *not* in this update (and why)

These were on the roadmap but couldn't be built today because they
need things outside our control:

- **Payme / Click / Apelsin direct payment** — we need real merchant
  accounts and their sandbox URLs to test against. The order model
  is already ready for it; flipping the switch is half a day's work
  once credentials arrive.
- **Fiscal printer / OFD integration** — required by Uzbek law, but
  we need to pick one OFD provider, get their SDK, and have a test
  fiscal device on the desk.
- **Yandex Eats / Wolt / Express24 unified queue** — needs API access
  from each aggregator. The kitchen will keep using their tablets
  until we get those.
- **Owner mobile app (native)** — the data is all there (the dashboard
  endpoint above provides everything). The phone-app shell is a
  separate project decision: native iOS/Android vs PWA.

The full status of every roadmap item lives in `ROADMAP.md` at the
project root.

---

## Numbers

- **11 new feature commits**, all pushed to `main`.
- **Tests grew from 62 → 219 passing** (157 new tests covering all of
  the above).
- Roughly **4,500 lines of new code** across new features, models,
  and tests.


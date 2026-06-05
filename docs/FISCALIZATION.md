# Soliq fiscalization

Reports every sale to the Uzbek tax authority (Soliq) through an accredited
Fiscal Data Operator (OFD), getting back a **fiscal sign** + **QR** per receipt.

## The golden rule: per-tenant fiscal identity

**Every receipt is fiscalized under the selling business's OWN tax identity
(TIN/СТИР).** Each install carries that one business's credentials — never the
vendor's. Funnelling many businesses through one ID would attribute all their
revenue to that ID (a tax/legal disaster). All fiscal config is therefore
per-install (`.env` / the desktop control panel), never global.

## Architecture

```
order paid ──▶ FiscalizationService.fiscalize_on_payment(order_id)   (never raises)
                 │  (no-op if mode == off)
                 ▼
            build_receipt_payload(order, tenant)   # items, IKPU, VAT, tiyin
                 ▼
            provider.fiscalize(payload)            # MockProvider | MultikassaProvider
                 ▼
            FiscalReceipt(status, fiscal_sign, qr_url, ...)   # the proof, per order
```

- **Providers** plug in behind `fiscalization/providers/base.py:FiscalProvider`.
  `MockProvider` (deterministic, no network) powers dev/CI/demos;
  `MultikassaProvider` is a skeleton awaiting credentials + docs.
- **Serve-now policy** (default): a provider failure marks the receipt `FAILED`
  and the sale still completes; `fiscalize_retry` drains the queue when back
  online. Set `FISCAL_BLOCK_ON_FAILURE=true` to refuse sales until confirmed.

## Modes (runtime-toggleable from the control panel)

| mode | meaning |
|------|---------|
| `off` | disabled — no receipts created |
| `mock` | full pipeline, fake sign/QR, no network — test everything now |
| `sandbox` | real provider, test endpoint + sandbox creds |
| `live` | real provider, production — real fiscal documents |

## Configuration (`.env` / control panel — this business's own values)

```
FISCALIZATION_MODE=off            # off | mock | sandbox | live
FISCAL_PROVIDER=mock              # mock | multikassa
FISCAL_TIN=123456789             # the BUSINESS's tax id
FISCAL_PROVIDER_URL=...           # provider endpoint
FISCAL_MERCHANT_ID=...            # provider credentials
FISCAL_SECRET=...
FISCAL_VAT_PERCENT=0              # QQS rate (0 if not VAT-registered)
FISCAL_BLOCK_ON_FAILURE=false     # serve-now (false) vs block (true)
```

Each `Product` needs an `ikpu_code` (IKPU/SPIC/MXIK, from tasnif.soliq.uz) for
live fiscalization. Blank is tolerated in mock/sandbox so the catalog can be
coded gradually.

## Testing

```
# mock mode, no credentials:
python manage.py fiscalize_order <order_id>      # prints fiscal sign + QR
python manage.py fiscalize_retry                 # drain failed queue
pytest fiscalization/                            # 12 tests, all mock
```
Endpoints (admin-gated): `GET /api/fiscalization/status`, `POST .../mode`,
`POST .../test`, `GET .../receipts`, `POST .../retry`,
`POST .../orders/<id>/fiscalize`. The desktop control panel wraps all of these.

## Going live — what's needed from the operator

1. Sign up with **Multikassa** (recommended) or **Soliq-Servis**; get the
   integration docs + **sandbox credentials**. Ask whether they support a
   **multi-merchant/reseller** model where each business stays under its own TIN.
2. Fill `FISCAL_*` in the control panel; set mode `sandbox`, run a test sale,
   verify the QR on `ofd.soliq.uz`; then switch to `live`.
3. Finish `MultikassaProvider` (the request/response mapping is stubbed with the
   field shape ready — see `fiscalization/providers/multikassa.py`).

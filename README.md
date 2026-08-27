# Frappe Lending — Zeekash Bridge

A Frappe app that makes a **Frappe Lending** site speak **zeekash's published Murabaha
financier contract** (`docs/openapi/financing.yaml`) natively. It installs alongside the
`lending` app and **does not modify it**.

With this app on the site, zeekash reaches Frappe Lending through its stock
`CanonicalFinancingConnector` — onboarding a bank becomes *config* (a `bank_providers`
row + `fin_frappe_lending` config), not a bespoke connector class in zeekash. A third
financier that speaks the same contract is config too.

## How it works

Frappe routes `GET/HEAD/POST` for non-`/api` paths through **page renderers**
(`frappe/app.py`). `frappe_lending_zeekash.router.FinancingRouter` (registered via the
`page_renderer` hook — note: singular) intercepts `/oauth/token` and `/financing/*`,
dispatches to `bank.py`, and returns JSON with contract-correct status codes + the
`error_code` envelope + `Idempotency-Key` replay.

- `router.py` — path/verb dispatch, auth, idempotency, error → JSON
- `bank.py`  — the 14 endpoints, backed by Frappe **Loan Application / Loan / Loan
  Disbursement / Loan Repayment**. Markup is read from the product's schedule, never
  computed. The Murabaha **ownership sequence** (purchaseOrder → disburse → activate,
  with the Sharia gates) and the offer/supplier/asset snapshots live on the
  **Zeekash Murabaha** doctype (state vanilla Lending doesn't model).
- `auth.py` — OAuth2 client-credentials token + bearer check (fail-open when no creds).
- `webhooks.py` — signed (`X-Signature: base64(HMAC_SHA256(body, secret))`) outbound
  webhooks to zeekash on `contract.activated` / `contract.settled`.

## Config (site_config, set with `bench --site <site> set-config <k> <v>`)

| key | meaning |
|---|---|
| `zeekash_company` | ERPNext Company loans are booked against |
| `zeekash_loan_category` | only Loan Products in this category are Murabaha (e.g. `MRB0001`) |
| `zeekash_currency` | override reported currency (else the Company currency) |
| `zeekash_webhook_url` / `zeekash_webhook_host` | where to POST webhooks (+ Host for Docker) |
| `zeekash_webhook_secret` | HMAC secret; must match zeekash's `fin_frappe_lending` webhook_secret |
| `zeekash_client_id` / `zeekash_client_secret` | optional; enables bearer auth |

> **Auth note:** Frappe's framework consumes the `Authorization` header before page
> renderers, so with credentials set the connector's Bearer is rejected by Frappe first.
> The dev bridge therefore runs **unauthenticated** (like zeekash's sandbox bank).
> For production, terminate **mTLS** at the proxy (the connector supports client certs).

## Install / re-setup under frappe_docker

The app is bind-mounted (`~/py/frappe_docker/compose.bridge.yaml`) into every Python
service. Bring the stack up with both compose files:

```bash
cd ~/py/frappe_docker
docker compose -p frappe -f compose.custom.yaml -f compose.bridge.yaml up -d
```

After a **full recreate** (`down`/`up`), the editable pip install and `apps.txt` entry
in the image layer are reset — re-run in each Python service (backend, queue-long,
queue-short, scheduler):

```bash
for s in backend queue-long queue-short scheduler; do
  docker compose -p frappe -f compose.custom.yaml -f compose.bridge.yaml exec -T $s bash -lc \
    'env/bin/pip install -q -e apps/frappe_lending_zeekash; grep -qx frappe_lending_zeekash sites/apps.txt || echo frappe_lending_zeekash >> sites/apps.txt'
done
docker compose -p frappe -f compose.custom.yaml -f compose.bridge.yaml restart backend queue-long queue-short scheduler frontend
```

(The site install and the **Zeekash Murabaha** table persist in the sites/DB volume.)
Restarting `frontend` clears nginx's cached backend DNS (avoids a 502).

For a permanent setup, add this app to the image's `apps.json` and rebuild.

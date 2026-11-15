# ZAD PAY — ZAD OSINT Gateway

Premium white + blue glassmorphism payment management platform. **Python FastAPI + SQLite (no Firebase)**, PWA, 8 languages,
SVG icons, real provider-verified payments (Razorpay + Cashfree), QR codes, payment links, subscriptions, admin panel and Owner Control Center.

## Honest scope (read this first)
* **Real verification only.** An order becomes `paid` only after the provider's *server API* confirms status, amount and currency.
  Webhooks are signature-checked and then **re-verified through the provider API**. Screenshots / UTR numbers are never accepted.
* **Providers:** Razorpay and Cashfree are implemented. **PhonePe and FamPay have no public merchant API for individuals**, so they are not
  "connected" (nothing is faked). Customers *can pay from PhonePe/FamPay/any UPI app* by scanning your gateway QR / opening the payment link.
  PhonePe Business merchants can be added later as another adapter in `app/providers.py`.
* **Test mode** = the provider's sandbox (`rzp_test_…` keys / Cashfree sandbox). No real money moves; orders and transactions are labelled **TEST**.
* I could not call live gateways from the build environment, so **do one sandbox payment end-to-end after deploy** (checklist below).
  The Cashfree adapter in particular should be sandbox-tested first.

## Features
User: register/login/logout, email verification (when SMTP set), forgot/reset password, profile, sessions, ecosystem choice, dashboard,
`/order`, `/connect`, `/verify`, `/qr`, payment links, transactions, subscription (manual renewal, no auto-debit), support tickets, notifications, activity, API keys.
Admin: users (search/block/suspend/activate/deactivate), subscriptions, orders/transactions search, failed payments, provider health, tickets, announcements, CSV reports, activity logs.
Owner (separate center, password re-entry for 10 min on top of login): admins + permissions, plans & prices, free access, per-user pricing, discount codes, branding, maintenance mode, limits, analytics, system health, audit logs, API-key control.

**Security:** scrypt password hashing, HttpOnly+SameSite cookies, CSRF double-submit token, per-IP/per-account rate limits, Fernet-encrypted provider keys,
HMAC webhook verification, idempotent settlement (unique payment IDs + event IDs), append-only `transactions` and `audit_logs` (DB triggers),
server-side ownership checks (no IDOR), backend RBAC, CSP/HSTS/X-Frame headers, HTTPS redirect, generic error responses.

**Auto URL:** the gateway URL is detected from `PUBLIC_URL` → Render's `RENDER_EXTERNAL_URL` → request headers, and shown to every user
(Dashboard) plus used in webhook URLs, canonical tag, sitemap and robots. SEO title is "ZAD OSINT Gateway – ZAD PAY".
For Google to show it on top when people search "ZAD OSINT Gateway": open Google Search Console → add your URL → submit `/sitemap.xml`. Ranking takes time; nobody can guarantee position #1.

## Deploy on Render (GitHub → Render)
1. Unzip, create a **GitHub repo**, push all files (`git init && git add . && git commit -m init && git push`). `.env`/`data/` are git-ignored.
2. Render → **New → Blueprint** → pick the repo (it reads `render.yaml`). Or **New → Web Service** with:
   Build `pip install -r requirements.txt`, Start `uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"`, Health check `/healthz`.
3. Set environment variables: `OWNER_EMAIL`, `OWNER_PASSWORD` (≥10 chars). `SECRET_KEY` is generated automatically. SMTP_* optional.
4. **Storage:** `render.yaml` uses a 1 GB persistent disk at `/var/data` (needs a paid plan). On the **free plan** remove the `disk:` block and `DATA_DIR`:
   it works, but the SQLite data is wiped on every redeploy/restart. Use a paid plan for real users/payments.
5. Open `https://<your-service>.onrender.com` → log in with the owner email/password → **Owner** tab → unlock → check *System health* for warnings.
6. Optional custom domain: Render → Settings → Custom Domains. The app picks it up automatically (or set `PUBLIC_URL`).

## Connect a gateway (every user / the owner)
**Razorpay:** Dashboard → Settings → API Keys → generate (test first). In ZAD PAY open **/connect**, paste Key ID + Secret, mode test/live.
Then Razorpay → Settings → Webhooks → add the **Webhook URL shown in /connect**, choose a secret (paste the same secret in ZAD PAY),
events: `payment_link.paid`, `payment_link.expired`, `payment_link.cancelled`, `payment.captured`.
**Cashfree:** Developers → API Keys (App ID + Secret). Connect in /connect. Add the shown webhook URL in Cashfree → Developers → Webhooks.
Cashfree needs the customer phone for every payment link. Whitelist Render's outbound IPs in Cashfree if IP whitelisting is on.
The **owner** connects a gateway too — that gateway receives **subscription payments**.

## First-run test checklist
1. Connect Razorpay *test* keys → green "connected" (credentials are verified live).
2. /order → ₹10 → Pay now → pay with Razorpay test UPI/card → status flips to **paid** within seconds (webhook, or auto-poll every 5 s).
3. /qr → scan with a UPI app in test mode, /verify page shows provider-verified status.
4. Owner → Plans: change MONTHLY price → user /subscription → pay → plan activates only after verified payment.
5. Switch to live keys only after all of the above work.

## API (also at `/api/docs`)
Cookie session (browser) or `Authorization: Bearer zk_…` (API keys from Profile; state-changing calls with Bearer skip CSRF).
| Method | Path | Notes |
|---|---|---|
| POST | /api/order/create | `{amount, description, provider?, customer_phone?, expires_minutes?, idempotency_key?}` → hosted checkout `pay_url` |
| GET | /api/order/{order_id} | own orders only |
| POST | /api/payment/verify | `{order_id}` → verified against provider API |
| POST | /api/payment/webhook/{connection_id} | public, HMAC-verified, re-verified server-side |
| POST | /api/qr/create | same body as order → QR SVG + order |
| GET | /api/transactions | immutable records |
| GET | /api/user/profile · /api/subscription | |
| GET | /api/admin/users · POST /api/admin/users/{id}/block | admin permission `users` |
Also: `/api/orders`, `/api/connect`, `/api/tickets`, `/api/keys`, `/api/owner/*` (owner + password unlock).

## Run locally
```
pip install -r requirements.txt
export OWNER_EMAIL=you@example.com OWNER_PASSWORD='StrongPass#123' FORCE_HTTPS=0
uvicorn main:app --reload
```
## Languages / icons
English, हिन्दी, বাংলা, தமிழ், తెలుగు, اردو (RTL), العربية (RTL), Español. Add more in `static/i18n.js`. Icons are inline SVG (`static/icons.js`), no emojis.
## Project layout
`main.py` app+middleware · `app/` backend (db, security, providers, routes_*) · `static/` PWA frontend · `render.yaml` · `.env.example`.
## Firestore rules
Not applicable: this build uses SQLite with server-side checks; the browser never talks to the database.

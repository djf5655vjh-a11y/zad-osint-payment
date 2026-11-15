"""Real payment-provider adapters. Every status shown to users comes from the provider's server API,
never from user input or an unverified webhook body."""
import base64
import datetime
import hashlib
import hmac
import time

import httpx

RZ = "https://api.razorpay.com/v1"


class ProviderError(Exception):
    pass


SUPPORTED = [
    {
        "id": "razorpay",
        "name": "Razorpay",
        "key_label": "Key ID (rzp_test_... / rzp_live_...)",
        "secret_label": "Key Secret",
        "needs_webhook_secret": True,
        "webhook_events": "payment_link.paid, payment_link.expired, payment_link.cancelled, payment.captured",
        "note": "UPI, cards, netbanking and wallets. Customers can pay from PhonePe, FamPay, GPay, Paytm and any UPI app.",
    },
    {
        "id": "cashfree",
        "name": "Cashfree Payments",
        "key_label": "App ID (Client ID)",
        "secret_label": "Secret Key",
        "needs_webhook_secret": False,
        "webhook_events": "Payment Link / Payment Success webhooks (signature uses your Secret Key)",
        "note": "UPI, cards, netbanking. Customer phone number is required for each Cashfree payment link.",
    },
]


def _req(method, url, **kw):
    try:
        with httpx.Client(timeout=20) as h:
            r = h.request(method, url, **kw)
    except httpx.HTTPError:
        raise ProviderError("Could not reach the payment provider. Please try again shortly.")
    try:
        data = r.json()
    except ValueError:
        data = {}
    return r.status_code, data


def _err(data, default):
    if isinstance(data, dict):
        e = data.get("error")
        if isinstance(e, dict) and e.get("description"):
            return str(e["description"])[:200]
        if data.get("message"):
            return str(data["message"])[:200]
    return default


def _cf_base(c):
    return "https://sandbox.cashfree.com/pg" if c["mode"] == "test" else "https://api.cashfree.com/pg"


def _cf_headers(c):
    return {"x-client-id": c["key_id"], "x-client-secret": c["secret"], "x-api-version": "2023-08-01", "Content-Type": "application/json"}


def _rz_auth(c):
    return (c["key_id"], c["secret"])


def check(c) -> tuple[bool, str]:
    if c["provider"] == "razorpay":
        if not c["key_id"].startswith("rzp_"):
            return False, "Razorpay Key ID must start with rzp_test_ or rzp_live_."
        if c["key_id"].startswith("rzp_live_") != (c["mode"] == "live"):
            return False, "Key type does not match the selected mode (test/live)."
        s, d = _req("GET", RZ + "/payment_links?count=1", auth=_rz_auth(c))
        if s == 200:
            return True, "Connected"
        if s in (401, 403):
            return False, "Razorpay rejected these credentials."
        return False, _err(d, f"Razorpay returned HTTP {s}.")
    s, d = _req("GET", _cf_base(c) + "/links/zad_health_check", headers=_cf_headers(c))
    if s in (200, 404) and not (isinstance(d, dict) and d.get("type") == "authentication_error"):
        return True, "Connected"
    if s in (401, 403):
        return False, "Cashfree rejected these credentials (check keys, mode and IP whitelisting)."
    return False, _err(d, f"Cashfree returned HTTP {s}.")


def create_link(c, o, callback_url: str) -> dict:
    if c["provider"] == "razorpay":
        body = {
            "amount": o["amount"], "currency": o["currency"], "accept_partial": False,
            "description": (o["description"] or "Payment")[:250], "reference_id": o["id"], "expire_by": int(o["expires_at"]),
            "reminder_enable": False, "notify": {"sms": False, "email": False},
            "callback_url": callback_url, "callback_method": "get",
        }
        cust = {k: v for k, v in (("name", o.get("customer_name")), ("contact", o.get("customer_phone")), ("email", o.get("customer_email"))) if v}
        if cust:
            body["customer"] = cust
        s, d = _req("POST", RZ + "/payment_links", auth=_rz_auth(c), json=body)
        if s not in (200, 201) or not d.get("short_url"):
            raise ProviderError(_err(d, "Razorpay could not create the payment link."))
        return {"ref": d["id"], "url": d["short_url"]}
    phone = (o.get("customer_phone") or "").strip()
    if len(phone) < 10:
        raise ProviderError("Customer phone (10 digits) is required for Cashfree payment links.")
    exp = datetime.datetime.fromtimestamp(o["expires_at"], datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    cust = {"customer_phone": phone}
    if o.get("customer_name"):
        cust["customer_name"] = o["customer_name"]
    if o.get("customer_email"):
        cust["customer_email"] = o["customer_email"]
    body = {
        "link_id": o["id"], "link_amount": float(f"{o['amount'] / 100:.2f}"), "link_currency": o["currency"],
        "link_purpose": (o["description"] or "Payment")[:500], "customer_details": cust, "link_expiry_time": exp,
        "link_notify": {"send_sms": False, "send_email": False}, "link_auto_reminders": False, "link_meta": {"return_url": callback_url},
    }
    s, d = _req("POST", _cf_base(c) + "/links", headers=_cf_headers(c), json=body)
    if s not in (200, 201) or not d.get("link_url"):
        raise ProviderError(_err(d, "Cashfree could not create the payment link."))
    return {"ref": d.get("link_id", o["id"]), "url": d["link_url"]}


def fetch_status(c, o) -> dict:
    """Ask the provider for the truth. Returns status in paid|pending|expired|cancelled."""
    ref = o["provider_ref"]
    if not ref:
        raise ProviderError("Order has no provider reference yet.")
    if c["provider"] == "razorpay":
        s, d = _req("GET", f"{RZ}/payment_links/{ref}", auth=_rz_auth(c))
        if s != 200:
            raise ProviderError(_err(d, f"Razorpay returned HTTP {s}."))
        st = {"paid": "paid", "expired": "expired", "cancelled": "cancelled"}.get(d.get("status"), "pending")
        pid = ref
        pays = d.get("payments")
        if isinstance(pays, list) and pays and isinstance(pays[0], dict) and pays[0].get("payment_id"):
            pid = pays[0]["payment_id"]
        return {"status": st, "paid": int(d.get("amount_paid") or 0), "currency": d.get("currency", "INR"), "payment_id": pid}
    s, d = _req("GET", f"{_cf_base(c)}/links/{ref}", headers=_cf_headers(c))
    if s != 200:
        raise ProviderError(_err(d, f"Cashfree returned HTTP {s}."))
    ls = str(d.get("link_status", "")).upper()
    st = {"PAID": "paid", "EXPIRED": "expired", "CANCELLED": "cancelled"}.get(ls, "pending")
    paid = int(round(float(d.get("link_amount_paid") or 0) * 100))
    pid = ref
    if st == "paid":
        s2, d2 = _req("GET", f"{_cf_base(c)}/links/{ref}/orders?status=PAID", headers=_cf_headers(c))
        if s2 == 200 and isinstance(d2, list) and d2 and isinstance(d2[0], dict) and d2[0].get("order_id"):
            pid = str(d2[0]["order_id"])
    return {"status": st, "paid": paid, "currency": d.get("link_currency", "INR"), "payment_id": pid}


def cancel(c, o):
    ref = o["provider_ref"]
    if not ref:
        return
    if c["provider"] == "razorpay":
        _req("POST", f"{RZ}/payment_links/{ref}/cancel", auth=_rz_auth(c))
    else:
        _req("POST", f"{_cf_base(c)}/links/{ref}/cancel", headers=_cf_headers(c))


def verify_webhook(c, raw: bytes, headers) -> bool:
    if c["provider"] == "razorpay":
        secret = c.get("webhook_secret") or ""
        if not secret:
            return False
        exp = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(exp, headers.get("x-razorpay-signature", ""))
    ts = headers.get("x-webhook-timestamp", "")
    sig = headers.get("x-webhook-signature", "")
    try:
        tv = float(ts)
        tv = tv / 1000 if tv > 1e12 else tv
        if abs(time.time() - tv) > 900:
            return False
    except ValueError:
        return False
    exp = base64.b64encode(hmac.new(c["secret"].encode(), ts.encode() + raw, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(exp, sig)


def event_id(c, raw: bytes, headers) -> str:
    return headers.get("x-razorpay-event-id") or hashlib.sha256(raw).hexdigest()


def candidates(obj, out=None) -> set:
    """Collect order/link identifiers from a webhook body. Only used to LOCATE our order - never to trust a status."""
    out = out if out is not None else set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("reference_id", "link_id", "order_id") and isinstance(v, str):
                out.add(v)
            elif k == "id" and isinstance(v, str) and v.startswith("plink_"):
                out.add(v)
            else:
                candidates(v, out)
    elif isinstance(obj, list):
        for v in obj:
            candidates(v, out)
    return out

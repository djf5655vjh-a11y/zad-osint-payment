import io
import json
import secrets
from decimal import Decimal, InvalidOperation

import segno
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from . import providers
from .db import ex, get_setting, now, one, q, tx, uid
from .deps import audit, base_url, current_user, notify
from .providers import ProviderError
from .security import client_ip, dec, enc, rate
from .services import activate_subscription, current_plan

router = APIRouter(prefix="/api")
FINAL = {"paid", "expired", "cancelled", "failed", "mismatch"}
PROV_IDS = {p["id"] for p in providers.SUPPORTED}


def order_out(o: dict) -> dict:
    return {k: o.get(k) for k in ("id", "amount", "currency", "description", "status", "provider", "mode", "pay_url", "expires_at",
                                  "created_at", "paid_at", "error", "purpose", "customer_name", "customer_phone")}


def to_paise(amount) -> int:
    try:
        d = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise HTTPException(400, "Enter a valid amount.")
    return int(d * 100)


def get_conn(merchant_id: str, provider: str | None = None, any_status: bool = False):
    sql, args = "SELECT * FROM providers WHERE user_id=?", [merchant_id]
    if not any_status:
        sql += " AND status='connected'"
    if provider:
        sql += " AND provider=?"
        args.append(provider)
    rows = q(sql + " ORDER BY created_at", args)
    if not rows:
        return None
    r = rows[0]
    return {"id": r["id"], "provider": r["provider"], "mode": r["mode"], "key_id": r["key_id"], "secret": dec(r["secret_enc"]),
            "webhook_secret": dec(r["webhook_enc"]) if r["webhook_enc"] else ""}


def make_order(user, base, amount, description, provider, cust, expires_min, idem, purpose="payment", merchant_id=None, meta=None):
    paise = to_paise(amount)
    mn, mx = int(get_setting("min_txn_paise", "100")), int(get_setting("max_txn_paise", "50000000"))
    if paise < 100:
        raise HTTPException(400, "Minimum amount is ₹1.00.")
    if purpose == "payment" and not (mn <= paise <= mx):
        raise HTTPException(400, f"Amount must be between ₹{mn/100:.2f} and ₹{mx/100:.2f}.")
    if provider and provider not in PROV_IDS:
        raise HTTPException(400, "Unsupported provider.")
    if idem:
        old = one("SELECT * FROM orders WHERE user_id=? AND idem_key=?", (user["id"], idem))
        if old:
            return order_out(old)
    if purpose == "payment":
        plan, _ = current_plan(user["id"])
        if plan["order_limit"]:
            ms = now() - (now() % 86400) - 86400 * 31
            used = one("SELECT COUNT(*) n FROM orders WHERE user_id=? AND purpose='payment' AND created_at>=?", (user["id"], ms))["n"]
            if used >= plan["order_limit"]:
                raise HTTPException(402, f"Your {plan['name']} plan allows {plan['order_limit']} orders per month. Upgrade in Subscription.")
    merchant = merchant_id or user["id"]
    conn = get_conn(merchant, provider)
    if not conn:
        raise HTTPException(400, "No connected payment provider. Open /connect and connect one first." if purpose == "payment"
                            else "Subscription payments are not available: the owner has not connected a gateway yet.")
    oid, t = "ZP" + secrets.token_hex(9).upper(), now()
    exp = t + max(15, min(int(expires_min), 10080)) * 60
    o = {"id": oid, "user_id": user["id"], "merchant_id": merchant, "purpose": purpose, "provider": conn["provider"], "mode": conn["mode"],
         "amount": paise, "currency": "INR", "description": (description or "Payment").strip()[:200], "status": "created", "expires_at": exp,
         "customer_name": (cust.get("name") or "")[:80] or None, "customer_phone": "".join(ch for ch in (cust.get("phone") or "") if ch.isdigit())[-10:] or None,
         "customer_email": (cust.get("email") or "")[:120] or None}
    ex("INSERT INTO orders(id,user_id,merchant_id,purpose,provider,mode,amount,currency,description,status,expires_at,customer_name,customer_phone,customer_email,idem_key,meta,created_at,updated_at) "
       "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (oid, user["id"], merchant, purpose, o["provider"], o["mode"], paise, "INR", o["description"], "created", exp, o["customer_name"], o["customer_phone"],
        o["customer_email"], idem, json.dumps(meta or {}), t, t))
    try:
        res = providers.create_link(conn, o, f"{base}/verify?order={oid}")
    except ProviderError as e:
        ex("UPDATE orders SET status='failed',error=?,updated_at=? WHERE id=?", (str(e)[:200], now(), oid))
        raise HTTPException(502, str(e))
    ex("UPDATE orders SET status='pending',provider_ref=?,pay_url=?,updated_at=? WHERE id=?", (res["ref"], res["url"], now(), oid))
    audit(user, "order_create", oid, f"{paise} {o['provider']} {o['mode']}")
    return order_out(one("SELECT * FROM orders WHERE id=?", (oid,)))


def settle(o: dict, res: dict) -> dict:
    """Atomic, idempotent settlement. Only a provider-API result can mark an order paid."""
    newly_paid = False
    with tx() as c:
        cur = dict(c.execute("SELECT * FROM orders WHERE id=?", (o["id"],)).fetchone())
        if cur["status"] in FINAL:
            return cur
        t = now()
        if res["status"] == "paid":
            if res["paid"] != cur["amount"] or res["currency"] != cur["currency"]:
                c.execute("UPDATE orders SET status='mismatch',error=?,updated_at=? WHERE id=?",
                          (f"Provider reported {res['paid']} {res['currency']} but order is {cur['amount']} {cur['currency']}", t, cur["id"]))
                c.execute("INSERT OR IGNORE INTO transactions(id,order_id,user_id,merchant_id,provider,mode,provider_payment_id,amount,currency,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                          (uid("TX"), cur["id"], cur["user_id"], cur["merchant_id"], cur["provider"], cur["mode"], res["payment_id"] + "#mismatch", res["paid"], res["currency"], "mismatch", t))
            else:
                n = c.execute("INSERT OR IGNORE INTO transactions(id,order_id,user_id,merchant_id,provider,mode,provider_payment_id,amount,currency,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                              (uid("TX"), cur["id"], cur["user_id"], cur["merchant_id"], cur["provider"], cur["mode"], res["payment_id"], res["paid"], res["currency"], "success", t)).rowcount
                if n:
                    c.execute("UPDATE orders SET status='paid',paid_at=?,error=NULL,updated_at=? WHERE id=?", (t, t, cur["id"]))
                    newly_paid = True
        elif res["status"] in ("expired", "cancelled"):
            c.execute("UPDATE orders SET status=?,updated_at=? WHERE id=?", (res["status"], t, cur["id"]))
        out = dict(c.execute("SELECT * FROM orders WHERE id=?", (o["id"],)).fetchone())
    if newly_paid:
        after_paid(out)
    return out


def after_paid(o: dict):
    if o["purpose"] == "subscription":
        m = json.loads(o["meta"] or "{}")
        activate_subscription(o["user_id"], m.get("plan", "monthly"), int(m.get("days", 30)), o["amount"], "payment")
        if m.get("code"):
            ex("UPDATE discounts SET used=used+1 WHERE code=?", (m["code"],))
        notify(o["user_id"], "Subscription active", f"Your {m.get('plan','')} plan is active. Payment verified.")
    else:
        notify(o["merchant_id"], "Payment received", f"{o['id']}: ₹{o['amount']/100:.2f} verified by {o['provider']}. " + get_setting("tpl_payment_success"))
    audit(None, "payment_verified", o["id"], f"{o['amount']} {o['provider']} {o['mode']}")


def verify_order(o: dict) -> dict:
    if o["status"] in FINAL:
        return o
    conn = get_conn(o["merchant_id"], o["provider"], any_status=True)
    if not conn:
        raise HTTPException(409, "Provider connection was removed; cannot verify this order.")
    try:
        res = providers.fetch_status(conn, o)
    except ProviderError as e:
        ex("UPDATE orders SET error=?,updated_at=? WHERE id=?", (str(e)[:200], now(), o["id"]))
        raise HTTPException(502, str(e))
    if res["status"] == "pending" and o["expires_at"] and now() > o["expires_at"] + 120:
        res["status"] = "expired"
    return settle(o, res)


# ---------------- orders ----------------
class OrderIn(BaseModel):
    amount: float = Field(gt=0, le=10000000)
    description: str = Field(min_length=1, max_length=200)
    provider: str | None = None
    customer_name: str | None = Field(default=None, max_length=80)
    customer_phone: str | None = Field(default=None, max_length=15)
    customer_email: str | None = Field(default=None, max_length=120)
    expires_minutes: int = Field(default=60, ge=15, le=10080)
    idempotency_key: str | None = Field(default=None, max_length=64)


@router.post("/order/create")
def create_order(b: OrderIn, request: Request, user=Depends(current_user)):
    rate("oc:" + user["id"], 30, 600)
    return {"order": make_order(user, base_url(request), b.amount, b.description, b.provider,
                                {"name": b.customer_name, "phone": b.customer_phone, "email": b.customer_email}, b.expires_minutes, b.idempotency_key)}


@router.get("/orders")
def list_orders(user=Depends(current_user)):
    return {"items": [order_out(o) for o in q("SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 200", (user["id"],))]}


def own_order(oid: str, user) -> dict:
    o = one("SELECT * FROM orders WHERE id=? AND user_id=?", (oid, user["id"]))
    if not o:
        raise HTTPException(404, "Order not found.")
    return o


@router.get("/order/{order_id}")
def get_order(order_id: str, user=Depends(current_user)):
    return {"order": order_out(own_order(order_id, user))}


@router.post("/order/{order_id}/cancel")
def cancel_order(order_id: str, request: Request, user=Depends(current_user)):
    o = own_order(order_id, user)
    if o["status"] not in ("created", "pending"):
        raise HTTPException(400, "Only unpaid orders can be cancelled.")
    conn = get_conn(o["merchant_id"], o["provider"], any_status=True)
    if conn:
        providers.cancel(conn, o)
    o = verify_order(o) if conn else o
    if o["status"] in ("created", "pending"):
        ex("UPDATE orders SET status='cancelled',updated_at=? WHERE id=? AND status IN ('created','pending')", (now(), o["id"]))
    audit(user, "order_cancel", order_id, request=request)
    return {"order": order_out(one("SELECT * FROM orders WHERE id=?", (order_id,)))}


class VerifyIn(BaseModel):
    order_id: str = Field(min_length=6, max_length=40)


@router.post("/payment/verify")
def verify(b: VerifyIn, user=Depends(current_user)):
    rate("vf:" + user["id"], 120, 600)
    o = own_order(b.order_id.strip(), user)
    if o["status"] not in FINAL and now() - (o["last_verify"] or 0) >= 3:
        ex("UPDATE orders SET last_verify=? WHERE id=?", (now(), o["id"]))
        o = verify_order(o)
    return {"order": order_out(o), "verified_by": "provider_api"}


@router.get("/transactions")
def transactions(user=Depends(current_user)):
    return {"items": q("SELECT id,order_id,provider,mode,provider_payment_id,amount,currency,status,created_at FROM transactions WHERE user_id=? OR merchant_id=? ORDER BY created_at DESC LIMIT 200",
                       (user["id"], user["id"]))}


# ---------------- webhook ----------------
@router.post("/payment/webhook")
@router.post("/payment/webhook/{conn_id}")
async def webhook(request: Request, conn_id: str | None = None):
    conn_id = conn_id or request.query_params.get("c")
    rate("wh:" + client_ip(request), 300, 60)
    raw = await request.body()
    if len(raw) > 262144 or not conn_id:
        raise HTTPException(400, "Bad request.")
    row = one("SELECT * FROM providers WHERE id=?", (conn_id,))
    if not row:
        raise HTTPException(404, "Unknown endpoint.")
    conn = {"id": row["id"], "provider": row["provider"], "mode": row["mode"], "key_id": row["key_id"], "secret": dec(row["secret_enc"]),
            "webhook_secret": dec(row["webhook_enc"]) if row["webhook_enc"] else ""}
    if not providers.verify_webhook(conn, raw, request.headers):
        audit(None, "webhook_rejected", conn_id, "invalid signature", request)
        raise HTTPException(401, "Invalid signature.")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "Invalid JSON.")
    eid = providers.event_id(conn, raw, request.headers)
    if one("SELECT id FROM webhook_events WHERE id=?", (eid,)):
        return {"status": "duplicate"}
    cands = list(providers.candidates(payload))
    order = None
    if cands:
        ph = ",".join("?" * len(cands))
        order = one(f"SELECT * FROM orders WHERE merchant_id=? AND provider=? AND (id IN ({ph}) OR provider_ref IN ({ph}))", [row["user_id"], row["provider"], *cands, *cands])
    if order:
        try:
            await run_in_threadpool(verify_order, order)  # re-verified against provider API; webhook body is never trusted
        except HTTPException:
            raise HTTPException(503, "Verification temporarily failed; provider will retry.")
    ex("INSERT OR IGNORE INTO webhook_events(id,provider,received_at) VALUES(?,?,?)", (eid, row["provider"], now()))
    return {"status": "ok" if order else "ignored"}


# ---------------- QR ----------------
def qr_svg(url: str) -> str:
    b = io.BytesIO()
    segno.make(url, error="m").save(b, kind="svg", scale=8, border=2, dark="#0b3ea8", light="#ffffff", xmldecl=False)
    return b.getvalue().decode()


@router.post("/qr/create")
def qr_create(b: OrderIn, request: Request, user=Depends(current_user)):
    rate("qr:" + user["id"], 30, 600)
    o = make_order(user, base_url(request), b.amount, b.description, b.provider,
                   {"name": b.customer_name, "phone": b.customer_phone, "email": b.customer_email}, b.expires_minutes, b.idempotency_key)
    qid = uid("qr_")
    ex("INSERT OR IGNORE INTO qr_codes(id,user_id,order_id,svg,expires_at,created_at) VALUES(?,?,?,?,?,?)", (qid, user["id"], o["id"], qr_svg(o["pay_url"]), o["expires_at"], now()))
    return {"qr": qr_item(one("SELECT qr.id,qr.order_id,qr.svg,qr.expires_at,o.status,o.amount,o.description,o.pay_url FROM qr_codes qr JOIN orders o ON o.id=qr.order_id WHERE qr.id=?", (qid,)) or {})}


def qr_item(r):
    return {"id": r.get("id"), "order_id": r.get("order_id"), "svg": r.get("svg"), "expires_at": r.get("expires_at"), "status": r.get("status"),
            "amount": r.get("amount"), "description": r.get("description"), "pay_url": r.get("pay_url")}


@router.get("/qr")
def qr_list(user=Depends(current_user)):
    rows = q("SELECT qr.id,qr.order_id,qr.svg,qr.expires_at,o.status,o.amount,o.description,o.pay_url FROM qr_codes qr JOIN orders o ON o.id=qr.order_id "
             "WHERE qr.user_id=? ORDER BY qr.created_at DESC LIMIT 30", (user["id"],))
    return {"items": [qr_item(r) for r in rows]}


@router.get("/qr/{qid}.svg")
def qr_download(qid: str, user=Depends(current_user)):
    r = one("SELECT * FROM qr_codes WHERE id=? AND user_id=?", (qid, user["id"]))
    if not r:
        raise HTTPException(404, "QR not found.")
    return Response(r["svg"], media_type="image/svg+xml", headers={"Content-Disposition": f'attachment; filename="zadpay-{r["order_id"]}.svg"'})


# ---------------- connect ----------------
class ConnectIn(BaseModel):
    provider: str
    key_id: str = Field(min_length=6, max_length=120)
    key_secret: str = Field(min_length=6, max_length=200)
    webhook_secret: str | None = Field(default=None, max_length=200)
    mode: str = "test"


def conn_out(r, request):
    return {"provider": r["provider"], "mode": r["mode"], "key_id": r["key_id"][:8] + "••••", "status": r["status"], "last_check": r["last_check"],
            "last_error": r["last_error"], "webhook_url": f"{base_url(request)}/api/payment/webhook/{r['id']}", "webhook_secret_set": bool(r["webhook_enc"]),
            "created_at": r["created_at"]}


@router.get("/connect")
def connect_list(request: Request, user=Depends(current_user)):
    return {"items": [conn_out(r, request) for r in q("SELECT * FROM providers WHERE user_id=?", (user["id"],))]}


@router.post("/connect")
def connect(b: ConnectIn, request: Request, user=Depends(current_user)):
    rate("cn:" + user["id"], 10, 600)
    if b.provider not in PROV_IDS or b.mode not in ("test", "live"):
        raise HTTPException(400, "Invalid provider or mode.")
    c = {"provider": b.provider, "mode": b.mode, "key_id": b.key_id.strip(), "secret": b.key_secret.strip()}
    ok, msg = providers.check(c)
    if not ok:
        raise HTTPException(400, msg)
    old = one("SELECT id FROM providers WHERE user_id=? AND provider=?", (user["id"], b.provider))
    wh = enc(b.webhook_secret.strip()) if b.webhook_secret and b.webhook_secret.strip() else None
    if old:
        ex("UPDATE providers SET mode=?,key_id=?,secret_enc=?,webhook_enc=COALESCE(?,webhook_enc),status='connected',last_check=?,last_error=NULL WHERE id=?",
           (b.mode, c["key_id"], enc(c["secret"]), wh, now(), old["id"]))
    else:
        ex("INSERT INTO providers(id,user_id,provider,mode,key_id,secret_enc,webhook_enc,status,last_check,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
           (secrets.token_urlsafe(18), user["id"], b.provider, b.mode, c["key_id"], enc(c["secret"]), wh, "connected", now(), now()))
    audit(user, "provider_connect", b.provider, b.mode, request)
    return {"item": conn_out(one("SELECT * FROM providers WHERE user_id=? AND provider=?", (user["id"], b.provider)), request)}


@router.post("/connect/{provider}/check")
def connect_check(provider: str, request: Request, user=Depends(current_user)):
    rate("cc:" + user["id"], 20, 600)
    r = one("SELECT * FROM providers WHERE user_id=? AND provider=?", (user["id"], provider))
    if not r:
        raise HTTPException(404, "Provider not connected.")
    c = {"provider": r["provider"], "mode": r["mode"], "key_id": r["key_id"], "secret": dec(r["secret_enc"])}
    try:
        ok, msg = providers.check(c)
    except ProviderError as e:
        ok, msg = False, str(e)
    ex("UPDATE providers SET status=?,last_check=?,last_error=? WHERE id=?", ("connected" if ok else "error", now(), None if ok else msg, r["id"]))
    return {"item": conn_out(one("SELECT * FROM providers WHERE id=?", (r["id"],)), request)}


@router.delete("/connect/{provider}")
def disconnect(provider: str, request: Request, user=Depends(current_user)):
    ex("DELETE FROM providers WHERE user_id=? AND provider=?", (user["id"], provider))
    audit(user, "provider_disconnect", provider, request=request)
    return {"ok": True}

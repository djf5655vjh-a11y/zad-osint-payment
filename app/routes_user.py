import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import mailer, providers
from .config import SECRET_FROM_ENV
from .db import ex, get_setting, now, one, q, uid
from .deps import audit, base_url, current_user, notify, public_user
from .routes_auth import LANGS, strong
from .security import check_password, client_ip, hash_password, rate, sha
from .services import current_plan, plan_out

router = APIRouter(prefix="/api")


@router.get("/meta")
def meta(request: Request):
    b = base_url(request)
    return {
        "brand": get_setting("brand_name", "ZAD PAY"), "tagline": get_setting("tagline"), "color": get_setting("primary_color", "#1456f0"),
        "base_url": b, "webhook_base": b + "/api/payment/webhook/", "email_enabled": mailer.enabled(),
        "maintenance": get_setting("maintenance", "0") == "1", "maintenance_message": get_setting("maintenance_message"),
        "registration_open": get_setting("registration_open", "1") == "1", "providers": providers.SUPPORTED,
        "plans": [plan_out(p) for p in q("SELECT * FROM plans WHERE enabled=1 ORDER BY price")],
    }


@router.get("/user/profile")
def profile(user=Depends(current_user)):
    p, s = current_plan(user["id"])
    return {"user": public_user(user), "plan": p["name"], "plan_code": p["code"], "plan_expires": s["expires_at"] if s else None}


class ProfileIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    phone: str | None = Field(default=None, max_length=15)
    lang: str | None = None
    ecosystem: str | None = None


@router.put("/user/profile")
def update_profile(b: ProfileIn, request: Request, user=Depends(current_user)):
    if b.ecosystem is not None and b.ecosystem not in ("fampay", "phonepe", "other"):
        raise HTTPException(400, "Invalid payment ecosystem.")
    if b.lang is not None and b.lang not in LANGS:
        raise HTTPException(400, "Unsupported language.")
    vals = {"name": b.name.strip() if b.name else None, "phone": (re.sub(r"\D", "", b.phone)[-10:] if b.phone is not None else None), "lang": b.lang, "ecosystem": b.ecosystem}
    for k, v in vals.items():
        if v is not None:
            ex(f"UPDATE users SET {k}=? WHERE id=?", (v, user["id"]))
    audit(user, "profile_update", request=request)
    return {"user": public_user(one("SELECT * FROM users WHERE id=?", (user["id"],)))}


class PwIn(BaseModel):
    current: str = Field(max_length=128)
    new: str = Field(min_length=8, max_length=128)


@router.post("/user/password")
def change_password(b: PwIn, request: Request, user=Depends(current_user)):
    rate("pw:" + user["id"], 6, 900)
    if not check_password(b.current, user["pw_hash"]):
        raise HTTPException(400, "Current password is incorrect.")
    strong(b.new)
    ex("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(b.new), user["id"]))
    s = getattr(request.state, "session", None)
    ex("DELETE FROM sessions WHERE user_id=? AND id<>?", (user["id"], s["id"] if s else -1))
    audit(user, "password_change", request=request)
    return {"ok": True}


@router.get("/user/sessions")
def sessions(request: Request, user=Depends(current_user)):
    cur = getattr(request.state, "session", None)
    rows = q("SELECT id,created_at,expires_at,ip,ua FROM sessions WHERE user_id=? AND expires_at>? ORDER BY created_at DESC", (user["id"], now()))
    for r in rows:
        r["current"] = bool(cur and cur["id"] == r["id"])
    return {"sessions": rows}


@router.delete("/user/sessions/{sid}")
def revoke_session(sid: int, user=Depends(current_user)):
    ex("DELETE FROM sessions WHERE id=? AND user_id=?", (sid, user["id"]))
    return {"ok": True}


@router.get("/dashboard")
def dashboard(user=Depends(current_user)):
    rows = q("SELECT status,COUNT(*) n,COALESCE(SUM(amount),0) s FROM orders WHERE user_id=? AND purpose='payment' GROUP BY status", (user["id"],))
    m = {r["status"]: r for r in rows}
    def n(*ks): return sum(m[k]["n"] for k in ks if k in m)
    p, s = current_plan(user["id"])
    recent = q("SELECT id,amount,currency,description,status,mode,created_at FROM orders WHERE user_id=? AND purpose='payment' ORDER BY created_at DESC LIMIT 6", (user["id"],))
    prov = q("SELECT provider,mode,status FROM providers WHERE user_id=?", (user["id"],))
    return {"total": sum(r["n"] for r in rows), "paid": n("paid"), "pending": n("created", "pending"), "failed": n("failed", "expired", "cancelled", "mismatch"),
            "received": m["paid"]["s"] if "paid" in m else 0, "recent": recent, "providers": prov, "plan": p["name"], "plan_expires": s["expires_at"] if s else None,
            "unread": one("SELECT COUNT(*) n FROM notifications WHERE user_id=? AND read=0", (user["id"],))["n"]}


@router.get("/notifications")
def notifications(user=Depends(current_user)):
    return {"items": q("SELECT id,title,body,read,created_at FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 100", (user["id"],))}


@router.post("/notifications/read")
def notifications_read(user=Depends(current_user)):
    ex("UPDATE notifications SET read=1 WHERE user_id=?", (user["id"],))
    return {"ok": True}


@router.get("/activity")
def activity(user=Depends(current_user)):
    return {"items": q("SELECT action,target,ip,created_at FROM audit_logs WHERE actor_id=? ORDER BY id DESC LIMIT 100", (user["id"],))}


# ---------- support tickets ----------
class TicketIn(BaseModel):
    subject: str = Field(min_length=3, max_length=120)
    body: str = Field(min_length=3, max_length=3000)


class ReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=3000)


@router.get("/tickets")
def tickets(user=Depends(current_user)):
    return {"items": q("SELECT * FROM tickets WHERE user_id=? ORDER BY updated_at DESC LIMIT 100", (user["id"],))}


@router.post("/tickets")
def new_ticket(b: TicketIn, user=Depends(current_user)):
    rate("tk:" + user["id"], 10, 3600)
    t, tid = now(), uid("T")
    ex("INSERT INTO tickets(id,user_id,subject,status,created_at,updated_at) VALUES(?,?,?,?,?,?)", (tid, user["id"], b.subject.strip(), "open", t, t))
    ex("INSERT INTO ticket_messages(ticket_id,user_id,is_staff,body,created_at) VALUES(?,?,?,?,?)", (tid, user["id"], 0, b.body.strip(), t))
    return {"id": tid}


@router.get("/tickets/{tid}")
def ticket(tid: str, user=Depends(current_user)):
    t = one("SELECT * FROM tickets WHERE id=? AND user_id=?", (tid, user["id"]))
    if not t:
        raise HTTPException(404, "Ticket not found.")
    return {"ticket": t, "messages": q("SELECT is_staff,body,created_at FROM ticket_messages WHERE ticket_id=? ORDER BY id", (tid,))}


@router.post("/tickets/{tid}/reply")
def ticket_reply(tid: str, b: ReplyIn, user=Depends(current_user)):
    t = one("SELECT * FROM tickets WHERE id=? AND user_id=?", (tid, user["id"]))
    if not t:
        raise HTTPException(404, "Ticket not found.")
    ex("INSERT INTO ticket_messages(ticket_id,user_id,is_staff,body,created_at) VALUES(?,?,?,?,?)", (tid, user["id"], 0, b.body.strip(), now()))
    ex("UPDATE tickets SET status='open',updated_at=? WHERE id=?", (now(), tid))
    return {"ok": True}


# ---------- API keys ----------
class KeyIn(BaseModel):
    name: str = Field(min_length=2, max_length=40)


@router.get("/keys")
def keys(user=Depends(current_user)):
    return {"items": q("SELECT id,name,prefix,revoked,created_at,last_used FROM api_keys WHERE user_id=? ORDER BY created_at DESC", (user["id"],))}


@router.post("/keys")
def new_key(b: KeyIn, request: Request, user=Depends(current_user)):
    if one("SELECT COUNT(*) n FROM api_keys WHERE user_id=? AND revoked=0", (user["id"],))["n"] >= 5:
        raise HTTPException(400, "Maximum 5 active API keys.")
    raw = "zk_" + secrets.token_urlsafe(32)
    ex("INSERT INTO api_keys(id,user_id,name,key_hash,prefix,created_at) VALUES(?,?,?,?,?,?)", (uid("k_"), user["id"], b.name.strip(), sha(raw), raw[:9], now()))
    audit(user, "api_key_create", b.name, request=request)
    return {"key": raw, "note": "Copy it now - it will never be shown again."}


@router.delete("/keys/{kid}")
def del_key(kid: str, request: Request, user=Depends(current_user)):
    ex("UPDATE api_keys SET revoked=1 WHERE id=? AND user_id=?", (kid, user["id"]))
    audit(user, "api_key_revoke", kid, request=request)
    return {"ok": True}


# ---------- subscription ----------
class CheckoutIn(BaseModel):
    plan: str = Field(max_length=30)
    code: str | None = Field(default=None, max_length=30)
    provider: str | None = None


def price_for(user, plan, code):
    price = plan["price"]
    if user.get("custom_price") is not None:
        price = user["custom_price"]
    d = None
    if code:
        d = one("SELECT * FROM discounts WHERE code=? AND active=1", (code.strip().upper(),))
        if not d or (d["max_uses"] and d["used"] >= d["max_uses"]):
            raise HTTPException(400, "Discount code is invalid or exhausted.")
        price = max(0, price - (price * d["percent"] // 100) - d["flat"])
    return price, d


@router.get("/subscription")
def subscription(user=Depends(current_user)):
    p, s = current_plan(user["id"])
    owner = one("SELECT id FROM users WHERE role='owner' LIMIT 1")
    ready = bool(owner and one("SELECT id FROM providers WHERE user_id=? AND status='connected'", (owner["id"],)))
    return {"plan": p["name"], "plan_code": p["code"], "expires_at": s["expires_at"] if s else None, "custom_price": user.get("custom_price"),
            "plans": [plan_out(x) for x in q("SELECT * FROM plans WHERE enabled=1 ORDER BY price")], "payments_ready": ready,
            "history": q("SELECT plan,status,price,source,starts_at,expires_at FROM subscriptions WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (user["id"],))}


@router.post("/subscription/checkout")
def checkout(b: CheckoutIn, request: Request, user=Depends(current_user)):
    from .routes_pay import make_order
    from .services import activate_subscription, plan_row

    rate("co:" + user["id"], 10, 600)
    plan = plan_row(b.plan)
    if not plan or not plan["enabled"]:
        raise HTTPException(400, "This plan is not available.")
    if plan["code"] == "free":
        raise HTTPException(400, "You are already on the free plan by default.")
    price, d = price_for(user, plan, b.code)
    if price <= 0:
        activate_subscription(user["id"], plan["code"], plan["days"], 0, "free_access")
        if d:
            ex("UPDATE discounts SET used=used+1 WHERE code=?", (d["code"],))
        audit(user, "subscription_free", plan["code"], request=request)
        return {"activated": True}
    owner = one("SELECT id FROM users WHERE role='owner' LIMIT 1")
    if not owner:
        raise HTTPException(503, "Subscription payments are not available yet.")
    o = make_order(user, base_url(request), price / 100, f"ZAD PAY {plan['name']} plan ({plan['days']} days)", b.provider,
                   {"name": user["name"], "phone": user.get("phone"), "email": user["email"]}, 60, None,
                   purpose="subscription", merchant_id=owner["id"], meta={"plan": plan["code"], "days": plan["days"], "code": d["code"] if d else None})
    return {"activated": False, "order": o}

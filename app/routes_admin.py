import csv
import io
import json
import os
import platform
import re
import sys
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import mailer
from .config import DATA_DIR, DB_PATH, SECRET_FROM_ENV
from .db import ex, get_setting, now, one, q, set_setting, uid
from .deps import audit, base_url, current_user, notify, owner_elevated, owner_user, public_user, staff
from .routes_auth import EMAIL_RE, new_token, strong
from .security import check_password, hash_password, rate
from .services import activate_subscription, cancel_subscription, current_plan, plan_out, plan_row

START = time.time()
admin = APIRouter(prefix="/api/admin")
owner = APIRouter(prefix="/api/owner")
PERMS = ["users", "payments", "tickets", "announce", "subscriptions", "reports"]


def target_user(actor, uid_: str) -> dict:
    t = one("SELECT * FROM users WHERE id=?", (uid_,))
    if not t:
        raise HTTPException(404, "User not found.")
    if t["role"] == "owner" or t["id"] == actor["id"]:
        raise HTTPException(403, "You cannot modify this account.")
    if t["role"] == "admin" and actor["role"] != "owner":
        raise HTTPException(403, "Only the owner can modify admin accounts.")
    return t


# ---------------- admin: users ----------------
@admin.get("/users")
def users(search: str = "", role: str = "", status: str = "", limit: int = 50, offset: int = 0, user=Depends(staff("users"))):
    sql, args = "SELECT id,email,name,phone,role,status,perms,ecosystem,email_verified,custom_price,created_at,last_login FROM users WHERE 1=1", []
    if search:
        sql += " AND (email LIKE ? OR name LIKE ? OR id=?)"
        args += [f"%{search[:60]}%", f"%{search[:60]}%", search[:60]]
    if role in ("user", "admin", "owner"):
        sql += " AND role=?"
        args.append(role)
    if status in ("active", "suspended", "blocked", "inactive"):
        sql += " AND status=?"
        args.append(status)
    rows = q(sql + " ORDER BY created_at DESC LIMIT ? OFFSET ?", args + [min(limit, 200), max(offset, 0)])
    for r in rows:
        r["plan"] = current_plan(r["id"])[0]["name"]
    return {"items": rows}


@admin.get("/users/{uid_}")
def user_detail(uid_: str, user=Depends(staff("users"))):
    t = one("SELECT * FROM users WHERE id=?", (uid_,))
    if not t:
        raise HTTPException(404, "User not found.")
    p, s = current_plan(uid_)
    return {"user": public_user(t) | {"custom_price": t["custom_price"]}, "plan": p["name"], "plan_expires": s["expires_at"] if s else None,
            "orders": one("SELECT COUNT(*) n FROM orders WHERE user_id=?", (uid_,))["n"],
            "paid": one("SELECT COUNT(*) n FROM orders WHERE user_id=? AND status='paid'", (uid_,))["n"],
            "providers": q("SELECT provider,mode,status,last_check FROM providers WHERE user_id=?", (uid_,)),
            "subscriptions": q("SELECT plan,status,price,source,starts_at,expires_at FROM subscriptions WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (uid_,))}


def set_status(actor, uid_, status, request, reason=""):
    t = target_user(actor, uid_)
    ex("UPDATE users SET status=? WHERE id=?", (status, t["id"]))
    if status != "active":
        ex("DELETE FROM sessions WHERE user_id=?", (t["id"],))
    audit(actor, f"user_{status}", t["email"], reason, request)
    return {"ok": True, "status": status}


class ReasonIn(BaseModel):
    reason: str = Field(default="", max_length=200)


class StatusIn(BaseModel):
    status: str
    reason: str = Field(default="", max_length=200)


@admin.post("/users/{uid_}/block")
def block(uid_: str, request: Request, b: ReasonIn = ReasonIn(), user=Depends(staff("users"))):
    return set_status(user, uid_, "blocked", request, b.reason)


@admin.post("/users/{uid_}/unblock")
def unblock(uid_: str, request: Request, b: ReasonIn = ReasonIn(), user=Depends(staff("users"))):
    return set_status(user, uid_, "active", request, b.reason)


@admin.post("/users/{uid_}/status")
def status(uid_: str, b: StatusIn, request: Request, user=Depends(staff("users"))):
    if b.status not in ("active", "suspended", "blocked", "inactive"):
        raise HTTPException(400, "Invalid status.")
    return set_status(user, uid_, b.status, request, b.reason)


@admin.post("/users/{uid_}/reset-link")
def reset_link(uid_: str, request: Request, user=Depends(staff("users"))):
    t = target_user(user, uid_)
    tok = new_token(t["id"], "reset", 1)
    audit(user, "reset_link_issued", t["email"], request=request)
    return {"link": f"{base_url(request)}/reset?token={tok}", "note": "Valid for 1 hour. Share it only with the account holder."}


class SubIn(BaseModel):
    action: str
    plan: str | None = None
    days: int = Field(default=30, ge=1, le=3650)
    expires_at: int | None = None


@admin.post("/users/{uid_}/subscription")
def manage_sub(uid_: str, b: SubIn, request: Request, user=Depends(staff("subscriptions"))):
    t = one("SELECT * FROM users WHERE id=?", (uid_,))
    if not t:
        raise HTTPException(404, "User not found.")
    if b.action == "cancel":
        cancel_subscription(uid_)
    else:
        p = plan_row(b.plan or "")
        if not p:
            raise HTTPException(400, "Choose a valid plan.")
        if b.action == "grant":
            activate_subscription(uid_, p["code"], b.days, 0, "free_access")
        elif b.action == "extend":
            activate_subscription(uid_, p["code"], b.days, 0, "extended")
        elif b.action == "set_expiry":
            if not b.expires_at or b.expires_at <= now():
                raise HTTPException(400, "Expiry must be in the future.")
            activate_subscription(uid_, p["code"], 0, 0, "manual", expires_at=b.expires_at)
        else:
            raise HTTPException(400, "Invalid action.")
    notify(uid_, "Subscription updated", f"Your subscription was updated by the team ({b.action}).")
    audit(user, "subscription_" + b.action, t["email"], b.plan or "", request)
    return {"ok": True}


# ---------------- admin: payments ----------------
@admin.get("/orders")
def all_orders(search: str = "", status: str = "", user=Depends(staff("payments"))):
    sql, args = "SELECT o.id,o.amount,o.status,o.provider,o.mode,o.purpose,o.error,o.created_at,u.email FROM orders o JOIN users u ON u.id=o.user_id WHERE 1=1", []
    if search:
        sql += " AND (o.id LIKE ? OR u.email LIKE ? OR o.provider_ref=?)"
        args += [f"%{search[:60]}%", f"%{search[:60]}%", search[:60]]
    if status:
        sql += " AND o.status IN (%s)" % ",".join("?" * len(status.split(",")))
        args += status.split(",")
    return {"items": q(sql + " ORDER BY o.created_at DESC LIMIT 200", args)}


@admin.get("/transactions")
def all_txns(search: str = "", user=Depends(staff("payments"))):
    sql, args = "SELECT t.*,u.email FROM transactions t JOIN users u ON u.id=t.user_id WHERE 1=1", []
    if search:
        sql += " AND (t.id LIKE ? OR t.order_id LIKE ? OR t.provider_payment_id LIKE ? OR u.email LIKE ?)"
        args += [f"%{search[:60]}%"] * 4
    return {"items": q(sql + " ORDER BY t.created_at DESC LIMIT 200", args)}


@admin.get("/providers")
def all_providers(user=Depends(staff("payments"))):
    return {"items": q("SELECT p.provider,p.mode,p.status,p.last_check,p.last_error,u.email FROM providers p JOIN users u ON u.id=p.user_id ORDER BY p.created_at DESC LIMIT 200")}


# ---------------- admin: tickets / announce / logs / export ----------------
@admin.get("/tickets")
def all_tickets(status: str = "", user=Depends(staff("tickets"))):
    sql, args = "SELECT t.*,u.email FROM tickets t JOIN users u ON u.id=t.user_id", []
    if status:
        sql += " WHERE t.status=?"
        args.append(status)
    return {"items": q(sql + " ORDER BY t.updated_at DESC LIMIT 200", args)}


@admin.get("/tickets/{tid}")
def ticket_view(tid: str, user=Depends(staff("tickets"))):
    t = one("SELECT * FROM tickets WHERE id=?", (tid,))
    if not t:
        raise HTTPException(404, "Ticket not found.")
    return {"ticket": t, "messages": q("SELECT is_staff,body,created_at FROM ticket_messages WHERE ticket_id=? ORDER BY id", (tid,))}


class StaffReply(BaseModel):
    body: str = Field(default="", max_length=3000)
    status: str = "answered"


@admin.post("/tickets/{tid}/reply")
def ticket_reply(tid: str, b: StaffReply, request: Request, user=Depends(staff("tickets"))):
    t = one("SELECT * FROM tickets WHERE id=?", (tid,))
    if not t or b.status not in ("open", "answered", "closed"):
        raise HTTPException(400, "Invalid ticket or status.")
    if b.body.strip():
        ex("INSERT INTO ticket_messages(ticket_id,user_id,is_staff,body,created_at) VALUES(?,?,?,?,?)", (tid, user["id"], 1, b.body.strip(), now()))
        notify(t["user_id"], "Support replied", t["subject"])
    ex("UPDATE tickets SET status=?,updated_at=? WHERE id=?", (b.status, now(), tid))
    audit(user, "ticket_reply", tid, b.status, request)
    return {"ok": True}


class AnnounceIn(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    body: str = Field(min_length=2, max_length=600)


@admin.post("/announce")
def announce(b: AnnounceIn, request: Request, user=Depends(staff("announce"))):
    ex("INSERT INTO notifications(id,user_id,title,body,created_at) SELECT 'n_'||lower(hex(randomblob(8))),id,?,?,? FROM users WHERE status='active'", (b.title.strip(), b.body.strip(), now()))
    audit(user, "announcement", b.title, request=request)
    return {"ok": True}


@admin.get("/logs")
def logs(user=Depends(staff())):
    return {"items": q("SELECT l.action,l.target,l.detail,l.ip,l.created_at,u.email actor FROM audit_logs l LEFT JOIN users u ON u.id=l.actor_id WHERE l.actor_role IN ('admin','owner') ORDER BY l.id DESC LIMIT 200")}


def safe(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


@admin.get("/export/{kind}")
def export(kind: str, request: Request, user=Depends(staff("reports"))):
    spec = {"users": "SELECT id,email,name,role,status,created_at FROM users", "orders": "SELECT id,user_id,amount,currency,status,provider,mode,purpose,created_at,paid_at FROM orders",
            "transactions": "SELECT id,order_id,user_id,provider,mode,provider_payment_id,amount,currency,status,created_at FROM transactions"}
    if kind not in spec:
        raise HTTPException(404, "Unknown report.")
    rows = q(spec[kind] + " ORDER BY created_at DESC LIMIT 50000")
    buf = io.StringIO()
    w = csv.writer(buf)
    if rows:
        w.writerow(rows[0].keys())
        for r in rows:
            w.writerow([safe(v) for v in r.values()])
    audit(user, "export", kind, str(len(rows)), request)
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="zadpay-{kind}.csv"'})


# ---------------- owner ----------------
class PwIn(BaseModel):
    password: str = Field(max_length=128)


@owner.post("/unlock")
def unlock(b: PwIn, request: Request, user=Depends(owner_user)):
    rate("unlock:" + user["id"], 5, 600)
    if not check_password(b.password, user["pw_hash"]):
        audit(user, "owner_unlock_failed", request=request)
        raise HTTPException(401, "Incorrect password.")
    s = request.state.session
    if not s:
        raise HTTPException(403, "Owner actions require a browser session.")
    ex("UPDATE sessions SET elevated_until=? WHERE id=?", (now() + 600, s["id"]))
    audit(user, "owner_unlock", request=request)
    return {"ok": True, "elevated_until": now() + 600}


@owner.get("/state")
def state(request: Request, user=Depends(owner_user)):
    s = request.state.session
    return {"elevated": bool(s and s["elevated_until"] > now())}


class PlanIn(BaseModel):
    name: str = Field(min_length=2, max_length=30)
    price: float = Field(ge=0, le=100000)
    days: int = Field(default=30, ge=1, le=3650)
    enabled: bool = True
    order_limit: int | None = Field(default=None, ge=0)
    features: list[str] = []


@owner.get("/plans")
def plans(user=Depends(owner_elevated)):
    return {"items": [plan_out(p) for p in q("SELECT * FROM plans ORDER BY price")]}


@owner.put("/plans/{code}")
def put_plan(code: str, b: PlanIn, request: Request, user=Depends(owner_elevated)):
    if not re.fullmatch(r"[a-z0-9_]{2,20}", code):
        raise HTTPException(400, "Plan code: 2-20 lowercase letters, digits or underscore.")
    if code == "free" and b.price != 0:
        raise HTTPException(400, "The free plan must cost 0.")
    ex("INSERT INTO plans(code,name,price,days,enabled,order_limit,features) VALUES(?,?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET "
       "name=excluded.name,price=excluded.price,days=excluded.days,enabled=excluded.enabled,order_limit=excluded.order_limit,features=excluded.features",
       (code, b.name.strip().upper(), int(round(b.price * 100)), b.days, int(b.enabled), b.order_limit or None, json.dumps([f[:80] for f in b.features[:12]])))
    audit(user, "plan_save", code, f"{b.price}", request)
    return {"ok": True}


class PriceIn(BaseModel):
    price: float | None = Field(default=None, ge=0, le=100000)


@owner.post("/users/{uid_}/price")
def custom_price(uid_: str, b: PriceIn, request: Request, user=Depends(owner_elevated)):
    t = one("SELECT id,email FROM users WHERE id=?", (uid_,))
    if not t:
        raise HTTPException(404, "User not found.")
    ex("UPDATE users SET custom_price=? WHERE id=?", (None if b.price is None else int(round(b.price * 100)), uid_))
    audit(user, "custom_price", t["email"], str(b.price), request)
    return {"ok": True}


class DiscountIn(BaseModel):
    code: str = Field(min_length=3, max_length=30)
    percent: int = Field(default=0, ge=0, le=100)
    flat: float = Field(default=0, ge=0, le=100000)
    max_uses: int = Field(default=0, ge=0)


@owner.get("/discounts")
def discounts(user=Depends(owner_elevated)):
    return {"items": q("SELECT * FROM discounts ORDER BY created_at DESC")}


@owner.post("/discounts")
def new_discount(b: DiscountIn, request: Request, user=Depends(owner_elevated)):
    code = b.code.strip().upper()
    if not re.fullmatch(r"[A-Z0-9_-]{3,30}", code) or (b.percent == 0 and b.flat == 0):
        raise HTTPException(400, "Provide a valid code and a percent or flat discount.")
    ex("INSERT INTO discounts(code,percent,flat,active,max_uses,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET percent=excluded.percent,flat=excluded.flat,max_uses=excluded.max_uses,active=1",
       (code, b.percent, int(round(b.flat * 100)), 1, b.max_uses, now()))
    audit(user, "discount_save", code, request=request)
    return {"ok": True}


@owner.post("/discounts/{code}/toggle")
def toggle_discount(code: str, user=Depends(owner_elevated)):
    ex("UPDATE discounts SET active=1-active WHERE code=?", (code.upper(),))
    audit(user, "discount_toggle", code)
    return {"ok": True}


class AdminIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)
    perms: list[str] = PERMS


class PermsIn(BaseModel):
    perms: list[str] = PERMS


def clean_perms(p):
    return ",".join(x for x in p if x in PERMS)


@owner.post("/admins")
def create_admin(b: AdminIn, request: Request, user=Depends(owner_elevated)):
    email = b.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email.")
    strong(b.password)
    if one("SELECT id FROM users WHERE email=?", (email,)):
        raise HTTPException(409, "Email already registered. Use Promote instead.")
    ex("INSERT INTO users(id,email,name,pw_hash,role,perms,status,email_verified,lang,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
       (uid("u_"), email, b.name.strip(), hash_password(b.password), "admin", clean_perms(b.perms), "active", 1, "en", now()))
    audit(user, "admin_create", email, clean_perms(b.perms), request)
    return {"ok": True}


@owner.post("/users/{uid_}/promote")
def promote(uid_: str, b: PermsIn, request: Request, user=Depends(owner_elevated)):
    t = target_user(user, uid_)
    ex("UPDATE users SET role='admin',perms=? WHERE id=?", (clean_perms(b.perms), t["id"]))
    audit(user, "admin_promote", t["email"], clean_perms(b.perms), request)
    return {"ok": True}


@owner.post("/users/{uid_}/demote")
def demote(uid_: str, request: Request, user=Depends(owner_elevated)):
    t = target_user(user, uid_)
    ex("UPDATE users SET role='user',perms='' WHERE id=?", (t["id"],))
    ex("DELETE FROM sessions WHERE user_id=?", (t["id"],))
    audit(user, "admin_demote", t["email"], request=request)
    return {"ok": True}


@owner.post("/users/{uid_}/perms")
def set_perms(uid_: str, b: PermsIn, request: Request, user=Depends(owner_elevated)):
    t = target_user(user, uid_)
    if t["role"] != "admin":
        raise HTTPException(400, "Permissions apply to admin accounts only.")
    ex("UPDATE users SET perms=? WHERE id=?", (clean_perms(b.perms), t["id"]))
    audit(user, "perms_set", t["email"], clean_perms(b.perms), request)
    return {"ok": True}


SETTING_KEYS = {"brand_name", "tagline", "primary_color", "maintenance", "maintenance_message", "registration_open", "tpl_welcome", "tpl_payment_success"}


class SettingsIn(BaseModel):
    values: dict[str, str] = {}
    min_txn: float | None = Field(default=None, ge=1)
    max_txn: float | None = Field(default=None, ge=1)


@owner.get("/settings")
def get_settings(user=Depends(owner_elevated)):
    s = {k: get_setting(k) for k in SETTING_KEYS}
    s["min_txn"] = int(get_setting("min_txn_paise", "100")) / 100
    s["max_txn"] = int(get_setting("max_txn_paise", "50000000")) / 100
    return {"settings": s}


@owner.put("/settings")
def put_settings(b: SettingsIn, request: Request, user=Depends(owner_elevated)):
    for k, v in b.values.items():
        if k not in SETTING_KEYS:
            continue
        v = v.strip()[:1000]
        if k == "primary_color" and not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            raise HTTPException(400, "Color must look like #1456f0.")
        if k in ("maintenance", "registration_open") and v not in ("0", "1"):
            raise HTTPException(400, "Invalid toggle value.")
        set_setting(k, v)
    if b.min_txn is not None:
        set_setting("min_txn_paise", str(int(b.min_txn * 100)))
    if b.max_txn is not None:
        set_setting("max_txn_paise", str(int(b.max_txn * 100)))
    audit(user, "settings_update", ",".join(b.values.keys()), request=request)
    return {"ok": True}


@owner.get("/analytics")
def analytics(user=Depends(owner_elevated)):
    since = now() - 14 * 86400
    return {
        "users": one("SELECT COUNT(*) n FROM users")["n"], "admins": one("SELECT COUNT(*) n FROM users WHERE role='admin'")["n"],
        "orders": q("SELECT status,COUNT(*) n,COALESCE(SUM(amount),0) s FROM orders GROUP BY status"),
        "subscription_revenue": one("SELECT COALESCE(SUM(amount),0) s FROM orders WHERE purpose='subscription' AND status='paid'")["s"],
        "volume": one("SELECT COALESCE(SUM(amount),0) s FROM orders WHERE purpose='payment' AND status='paid'")["s"],
        "active_subs": one("SELECT COUNT(*) n FROM subscriptions WHERE status='active' AND expires_at>?", (now(),))["n"],
        "series": q("SELECT date(paid_at,'unixepoch') d,COUNT(*) n,SUM(amount) s FROM orders WHERE status='paid' AND paid_at>=? GROUP BY d ORDER BY d", (since,)),
    }


@owner.get("/health")
def health(request: Request, user=Depends(owner_elevated)):
    warns = []
    b = base_url(request)
    if not b.startswith("https://"):
        warns.append("Site is not served over HTTPS.")
    if not SECRET_FROM_ENV:
        warns.append("SECRET_KEY env var not set; a key file in DATA_DIR is used. Set SECRET_KEY on Render.")
    if not mailer.enabled():
        warns.append("SMTP not configured: email verification & password-reset emails are disabled.")
    if not one("SELECT id FROM providers WHERE user_id=? AND status='connected'", (user["id"],)):
        warns.append("Owner has not connected a payment gateway: paid subscriptions are unavailable.")
    return {"base_url": b, "uptime_s": int(time.time() - START), "python": sys.version.split()[0], "platform": platform.platform(),
            "db_size": os.path.getsize(DB_PATH) if DB_PATH.exists() else 0, "db_ok": bool(one("SELECT 1 x")), "data_dir": str(DATA_DIR),
            "email_enabled": mailer.enabled(), "providers_connected": one("SELECT COUNT(*) n FROM providers WHERE status='connected'")["n"],
            "warnings": warns}


@owner.get("/audit")
def audit_logs(search: str = "", user=Depends(owner_elevated)):
    sql, args = "SELECT l.id,l.action,l.target,l.detail,l.ip,l.actor_role,l.created_at,u.email actor FROM audit_logs l LEFT JOIN users u ON u.id=l.actor_id", []
    if search:
        sql += " WHERE l.action LIKE ? OR l.target LIKE ? OR u.email LIKE ?"
        args = [f"%{search[:60]}%"] * 3
    return {"items": q(sql + " ORDER BY l.id DESC LIMIT 300", args)}


@owner.get("/keys")
def all_keys(user=Depends(owner_elevated)):
    return {"items": q("SELECT k.id,k.name,k.prefix,k.revoked,k.created_at,k.last_used,u.email FROM api_keys k JOIN users u ON u.id=k.user_id ORDER BY k.created_at DESC LIMIT 200")}


@owner.delete("/keys/{kid}")
def revoke_key(kid: str, request: Request, user=Depends(owner_elevated)):
    ex("UPDATE api_keys SET revoked=1 WHERE id=?", (kid,))
    audit(user, "api_key_revoke_admin", kid, request=request)
    return {"ok": True}

import json

from .db import ex, now, one, q, uid


def plan_row(code):
    return one("SELECT * FROM plans WHERE code=?", (code,))


def current_sub(user_id):
    return one("SELECT * FROM subscriptions WHERE user_id=? AND status='active' AND expires_at>? ORDER BY expires_at DESC LIMIT 1", (user_id, now()))


def current_plan(user_id):
    s = current_sub(user_id)
    p = plan_row(s["plan"]) if s else None
    return (p or plan_row("free") or {"code": "free", "name": "FREE", "order_limit": 20, "features": "[]"}), s


def activate_subscription(user_id, plan, days, price, source, expires_at=None):
    t = now()
    cur = current_sub(user_id)
    if expires_at is None:
        start = cur["expires_at"] if cur and cur["plan"] == plan else t
        expires_at = start + days * 86400
    ex("UPDATE subscriptions SET status='replaced' WHERE user_id=? AND status='active'", (user_id,))
    ex("INSERT INTO subscriptions(id,user_id,plan,status,price,source,starts_at,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
       (uid("s_"), user_id, plan, "active", price, source, t, expires_at, t))
    return expires_at


def cancel_subscription(user_id):
    ex("UPDATE subscriptions SET status='cancelled' WHERE user_id=? AND status='active'", (user_id,))


def plan_out(p):
    return {"code": p["code"], "name": p["name"], "price": p["price"], "days": p["days"], "enabled": bool(p["enabled"]),
            "order_limit": p["order_limit"], "features": json.loads(p["features"] or "[]")}

import re

from fastapi import Depends, HTTPException, Request

from .config import PUBLIC_URL
from .db import ex, get_setting, now, one, uid
from .security import client_ip, sha

COOKIE = "zp_session"


def base_url(request: Request) -> str:
    """Hosting URL is detected automatically (env override -> Render URL -> request headers)."""
    if PUBLIC_URL:
        return PUBLIC_URL
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",")[0]
    host = re.sub(r"[^a-zA-Z0-9.\-:\[\]]", "", host)
    return f"{proto}://{host}"


def public_user(u: dict) -> dict:
    return {k: u.get(k) for k in ("id", "name", "email", "phone", "role", "perms", "status", "ecosystem", "lang", "email_verified", "created_at", "last_login")}


def audit(user, action: str, target: str = "", detail: str = "", request: Request | None = None):
    ex(
        "INSERT INTO audit_logs(actor_id,actor_role,action,target,detail,ip,created_at) VALUES(?,?,?,?,?,?,?)",
        (user["id"] if user else None, user["role"] if user else "system", action, target[:200], detail[:500], client_ip(request) if request else "", now()),
    )


def notify(user_id: str, title: str, body: str):
    ex("INSERT INTO notifications(id,user_id,title,body,created_at) VALUES(?,?,?,?,?)", (uid("n_"), user_id, title[:120], body[:600], now()))


def current_user(request: Request) -> dict:
    user = None
    request.state.session = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer zk_"):
        k = one("SELECT * FROM api_keys WHERE key_hash=? AND revoked=0", (sha(auth[7:].strip()),))
        if k:
            user = one("SELECT * FROM users WHERE id=?", (k["user_id"],))
            ex("UPDATE api_keys SET last_used=? WHERE id=?", (now(), k["id"]))
    else:
        tok = request.cookies.get(COOKIE)
        if tok:
            s = one("SELECT * FROM sessions WHERE token_hash=? AND expires_at>?", (sha(tok), now()))
            if s:
                user = one("SELECT * FROM users WHERE id=?", (s["user_id"],))
                request.state.session = s
    if not user:
        raise HTTPException(401, "Please log in to continue.")
    if user["status"] != "active":
        raise HTTPException(403, f"Your account is {user['status']}. Please contact support.")
    if get_setting("maintenance", "0") == "1" and user["role"] == "user":
        raise HTTPException(503, get_setting("maintenance_message", "Under maintenance."))
    return user


def staff(perm: str | None = None):
    def dep(user=Depends(current_user)):
        if user["role"] not in ("admin", "owner"):
            raise HTTPException(403, "Admin access required.")
        if user["role"] == "admin" and perm and perm not in (user.get("perms") or "").split(","):
            raise HTTPException(403, "You do not have permission for this action.")
        return user

    return dep


def owner_user(user=Depends(current_user)):
    if user["role"] != "owner":
        raise HTTPException(403, "Owner access required.")
    return user


def owner_elevated(request: Request, user=Depends(owner_user)):
    s = getattr(request.state, "session", None)
    if not s or s["elevated_until"] < now():
        raise HTTPException(403, "reauth_required")
    return user

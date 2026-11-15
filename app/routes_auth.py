import re
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from . import mailer
from .config import SESSION_DAYS
from .db import ex, get_setting, now, one, q, uid
from .deps import COOKIE, audit, base_url, current_user, notify, public_user
from .security import _DUMMY, check_password, client_ip, hash_password, rate, sha

router = APIRouter(prefix="/api/auth")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
LANGS = {"en", "hi", "bn", "ta", "te", "ur", "ar", "es"}


def strong(pw: str):
    if len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise HTTPException(400, "Password must be at least 8 characters and include letters and numbers.")


def new_token(user_id: str, kind: str, hours: int) -> str:
    tok = secrets.token_urlsafe(32)
    ex("INSERT INTO tokens(token_hash,user_id,kind,expires_at) VALUES(?,?,?,?)", (sha(tok), user_id, kind, now() + hours * 3600))
    return tok


def set_session(resp: Response, request: Request, user_id: str):
    tok = secrets.token_urlsafe(32)
    t = now()
    ex("DELETE FROM sessions WHERE expires_at<?", (t,))
    ex(
        "INSERT INTO sessions(token_hash,user_id,created_at,expires_at,ip,ua) VALUES(?,?,?,?,?,?)",
        (sha(tok), user_id, t, t + SESSION_DAYS * 86400, client_ip(request), (request.headers.get("user-agent") or "")[:200]),
    )
    secure = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip() == "https"
    resp.set_cookie(COOKIE, tok, max_age=SESSION_DAYS * 86400, httponly=True, secure=secure, samesite="lax", path="/")
    resp.set_cookie("zp_csrf", secrets.token_urlsafe(24), max_age=SESSION_DAYS * 86400, httponly=False, secure=secure, samesite="lax", path="/")


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)
    phone: str | None = Field(default=None, max_length=15)
    lang: str = "en"


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


@router.post("/register")
def register(b: RegisterIn, request: Request, bg: BackgroundTasks):
    rate("reg:" + client_ip(request), 6, 3600)
    if get_setting("registration_open", "1") != "1":
        raise HTTPException(403, "Registrations are currently closed.")
    email = b.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    strong(b.password)
    phone = re.sub(r"\D", "", b.phone or "")[-10:] or None
    if one("SELECT id FROM users WHERE email=?", (email,)):
        raise HTTPException(409, "An account with this email already exists.")
    verified = 0 if mailer.enabled() else 1
    u = uid("u_")
    ex(
        "INSERT INTO users(id,email,name,phone,pw_hash,role,status,email_verified,lang,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (u, email, b.name.strip(), phone, hash_password(b.password), "user", "active", verified, b.lang if b.lang in LANGS else "en", now()),
    )
    notify(u, "Welcome", get_setting("tpl_welcome"))
    if mailer.enabled():
        tok = new_token(u, "verify", 48)
        bg.add_task(mailer.send, email, "Verify your ZAD PAY email", f"Open this link to verify your email:\n{base_url(request)}/api/auth/verify-email?token={tok}\n\nThis link expires in 48 hours.")
    audit({"id": u, "role": "user"}, "register", email, request=request)
    return {"ok": True, "verification_required": mailer.enabled(),
            "message": "Account created. Check your email to verify, then log in." if mailer.enabled() else "Account created. You can log in now."}


@router.get("/verify-email")
def verify_email(token: str):
    t = one("SELECT * FROM tokens WHERE token_hash=? AND kind='verify' AND used=0 AND expires_at>?", (sha(token), now()))
    if not t:
        return RedirectResponse("/login?verified=0")
    ex("UPDATE users SET email_verified=1 WHERE id=?", (t["user_id"],))
    ex("UPDATE tokens SET used=1 WHERE token_hash=?", (t["token_hash"],))
    return RedirectResponse("/login?verified=1")


class EmailIn(BaseModel):
    email: str = Field(max_length=254)


@router.post("/resend-verification")
def resend(b: EmailIn, request: Request, bg: BackgroundTasks):
    rate("resend:" + client_ip(request), 5, 3600)
    u = one("SELECT * FROM users WHERE email=?", (b.email.strip().lower(),))
    if u and not u["email_verified"] and mailer.enabled():
        tok = new_token(u["id"], "verify", 48)
        bg.add_task(mailer.send, u["email"], "Verify your ZAD PAY email", f"Verify: {base_url(request)}/api/auth/verify-email?token={tok}")
    return {"ok": True, "message": "If the account exists and needs verification, an email has been sent."}


@router.post("/login")
def login(b: LoginIn, request: Request, response: Response):
    email = b.email.strip().lower()
    rate("login:" + client_ip(request), 15, 300)
    rate("logine:" + email, 8, 900)
    u = one("SELECT * FROM users WHERE email=?", (email,))
    ok = check_password(b.password, u["pw_hash"] if u else _DUMMY)
    if not u or not ok:
        raise HTTPException(401, "Incorrect email or password.")
    if u["status"] != "active":
        raise HTTPException(403, f"Your account is {u['status']}. Please contact support.")
    if not u["email_verified"]:
        raise HTTPException(403, "Please verify your email first. Check your inbox.")
    if get_setting("maintenance", "0") == "1" and u["role"] == "user":
        raise HTTPException(503, get_setting("maintenance_message"))
    set_session(response, request, u["id"])
    ex("UPDATE users SET last_login=? WHERE id=?", (now(), u["id"]))
    audit(u, "login", request=request)
    return {"user": public_user(u)}


@router.post("/logout")
def logout(request: Request, response: Response):
    tok = request.cookies.get(COOKIE)
    if tok:
        ex("DELETE FROM sessions WHERE token_hash=?", (sha(tok),))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.post("/forgot")
def forgot(b: EmailIn, request: Request, bg: BackgroundTasks):
    rate("forgot:" + client_ip(request), 5, 3600)
    u = one("SELECT * FROM users WHERE email=?", (b.email.strip().lower(),))
    if not mailer.enabled():
        return {"ok": True, "message": "Email service is not configured on this server. Ask an admin to generate a reset link for you."}
    if u and u["status"] == "active":
        tok = new_token(u["id"], "reset", 1)
        bg.add_task(mailer.send, u["email"], "Reset your ZAD PAY password", f"Reset link (valid 1 hour):\n{base_url(request)}/reset?token={tok}\n\nIgnore this email if you did not request it.")
    return {"ok": True, "message": "If the account exists, a reset link has been emailed."}


class ResetIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(min_length=8, max_length=128)


@router.post("/reset")
def reset(b: ResetIn, request: Request):
    rate("reset:" + client_ip(request), 10, 3600)
    strong(b.password)
    t = one("SELECT * FROM tokens WHERE token_hash=? AND kind='reset' AND used=0 AND expires_at>?", (sha(b.token), now()))
    if not t:
        raise HTTPException(400, "This reset link is invalid or has expired.")
    ex("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(b.password), t["user_id"]))
    ex("UPDATE tokens SET used=1 WHERE token_hash=?", (t["token_hash"],))
    ex("DELETE FROM sessions WHERE user_id=?", (t["user_id"],))
    audit({"id": t["user_id"], "role": "user"}, "password_reset", request=request)
    return {"ok": True, "message": "Password updated. Please log in."}

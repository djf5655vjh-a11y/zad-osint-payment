import json
import logging
import secrets
import sqlite3
import time
from contextlib import contextmanager

from .config import DB_PATH, OWNER_EMAIL, OWNER_NAME, OWNER_PASSWORD

log = logging.getLogger("zadpay")


def now() -> int:
    return int(time.time())


def uid(prefix: str = "") -> str:
    return prefix + secrets.token_hex(8)


def connect() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=30000")
    return c


def q(sql, args=()):
    c = connect()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def one(sql, args=()):
    r = q(sql, args)
    return r[0] if r else None


def ex(sql, args=()) -> int:
    c = connect()
    try:
        return c.execute(sql, args).rowcount
    finally:
        c.close()


@contextmanager
def tx():
    c = connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        yield c
        c.execute("COMMIT")
    except Exception:
        try:
            c.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        c.close()


def get_setting(key: str, default: str = "") -> str:
    r = one("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else default


def set_setting(key: str, value: str):
    ex("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,name TEXT,phone TEXT,pw_hash TEXT NOT NULL,
 role TEXT NOT NULL DEFAULT 'user',perms TEXT DEFAULT '',status TEXT NOT NULL DEFAULT 'active',email_verified INTEGER DEFAULT 0,
 ecosystem TEXT,lang TEXT DEFAULT 'en',custom_price INTEGER,created_at INTEGER,last_login INTEGER);
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,token_hash TEXT UNIQUE,user_id TEXT,created_at INTEGER,
 expires_at INTEGER,elevated_until INTEGER DEFAULT 0,ip TEXT,ua TEXT);
CREATE TABLE IF NOT EXISTS tokens(token_hash TEXT PRIMARY KEY,user_id TEXT,kind TEXT,expires_at INTEGER,used INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS api_keys(id TEXT PRIMARY KEY,user_id TEXT,name TEXT,key_hash TEXT UNIQUE,prefix TEXT,revoked INTEGER DEFAULT 0,
 created_at INTEGER,last_used INTEGER);
CREATE TABLE IF NOT EXISTS providers(id TEXT PRIMARY KEY,user_id TEXT,provider TEXT,mode TEXT,key_id TEXT,secret_enc TEXT,webhook_enc TEXT,
 status TEXT,last_check INTEGER,last_error TEXT,created_at INTEGER,UNIQUE(user_id,provider));
CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,merchant_id TEXT NOT NULL,purpose TEXT DEFAULT 'payment',
 provider TEXT,mode TEXT,amount INTEGER,currency TEXT DEFAULT 'INR',description TEXT,status TEXT,provider_ref TEXT,pay_url TEXT,
 expires_at INTEGER,customer_name TEXT,customer_phone TEXT,customer_email TEXT,idem_key TEXT,meta TEXT,error TEXT,created_at INTEGER,
 updated_at INTEGER,paid_at INTEGER,last_verify INTEGER DEFAULT 0,UNIQUE(user_id,idem_key));
CREATE TABLE IF NOT EXISTS transactions(id TEXT PRIMARY KEY,order_id TEXT,user_id TEXT,merchant_id TEXT,provider TEXT,mode TEXT,
 provider_payment_id TEXT UNIQUE,amount INTEGER,currency TEXT,status TEXT,created_at INTEGER);
CREATE TABLE IF NOT EXISTS webhook_events(id TEXT PRIMARY KEY,provider TEXT,received_at INTEGER);
CREATE TABLE IF NOT EXISTS qr_codes(id TEXT PRIMARY KEY,user_id TEXT,order_id TEXT,svg TEXT,expires_at INTEGER,created_at INTEGER);
CREATE TABLE IF NOT EXISTS plans(code TEXT PRIMARY KEY,name TEXT,price INTEGER,days INTEGER DEFAULT 30,enabled INTEGER DEFAULT 1,
 order_limit INTEGER,features TEXT);
CREATE TABLE IF NOT EXISTS subscriptions(id TEXT PRIMARY KEY,user_id TEXT,plan TEXT,status TEXT,price INTEGER,source TEXT,
 starts_at INTEGER,expires_at INTEGER,created_at INTEGER);
CREATE TABLE IF NOT EXISTS discounts(code TEXT PRIMARY KEY,percent INTEGER DEFAULT 0,flat INTEGER DEFAULT 0,active INTEGER DEFAULT 1,
 max_uses INTEGER DEFAULT 0,used INTEGER DEFAULT 0,created_at INTEGER);
CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY,user_id TEXT,title TEXT,body TEXT,read INTEGER DEFAULT 0,created_at INTEGER);
CREATE TABLE IF NOT EXISTS tickets(id TEXT PRIMARY KEY,user_id TEXT,subject TEXT,status TEXT DEFAULT 'open',created_at INTEGER,updated_at INTEGER);
CREATE TABLE IF NOT EXISTS ticket_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,ticket_id TEXT,user_id TEXT,is_staff INTEGER,body TEXT,created_at INTEGER);
CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,actor_id TEXT,actor_role TEXT,action TEXT,target TEXT,detail TEXT,
 ip TEXT,created_at INTEGER);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
CREATE INDEX IF NOT EXISTS ix_orders_user ON orders(user_id,created_at);
CREATE INDEX IF NOT EXISTS ix_orders_ref ON orders(merchant_id,provider_ref);
CREATE INDEX IF NOT EXISTS ix_txn_user ON transactions(user_id,created_at);
CREATE INDEX IF NOT EXISTS ix_sess_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_notif_user ON notifications(user_id,created_at);
CREATE INDEX IF NOT EXISTS ix_audit_actor ON audit_logs(actor_id,created_at);
CREATE TRIGGER IF NOT EXISTS txn_no_update BEFORE UPDATE ON transactions BEGIN SELECT RAISE(ABORT,'transactions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS txn_no_delete BEFORE DELETE ON transactions BEGIN SELECT RAISE(ABORT,'transactions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_logs BEGIN SELECT RAISE(ABORT,'audit logs are immutable'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_logs BEGIN SELECT RAISE(ABORT,'audit logs are immutable'); END;
"""

DEFAULT_SETTINGS = {
    "brand_name": "ZAD PAY",
    "tagline": "ZAD OSINT Gateway - secure payments, instant verification",
    "primary_color": "#1456f0",
    "maintenance": "0",
    "maintenance_message": "We are upgrading ZAD PAY. Please check back soon.",
    "registration_open": "1",
    "min_txn_paise": "100",
    "max_txn_paise": "50000000",
    "tpl_welcome": "Welcome to ZAD PAY! Connect a payment provider to start accepting payments.",
    "tpl_payment_success": "Payment received and verified by the provider.",
}

DEFAULT_PLANS = [
    ("free", "FREE", 0, 30, 1, 20, json.dumps(["Free dashboard access", "Limited features", "Basic transaction history", "20 orders / month"])),
    ("monthly", "MONTHLY", 3000, 30, 1, 500, json.dumps(["Standard platform features", "500 orders / month", "QR + payment links"])),
    ("premium", "PREMIUM", 9900, 30, 1, 5000, json.dumps(["Premium dashboard", "Advanced analytics", "5000 orders / month", "Priority support"])),
]


def init_db():
    c = connect()
    try:
        c.executescript(SCHEMA)
    finally:
        c.close()
    for k, v in DEFAULT_SETTINGS.items():
        ex("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    if not one("SELECT code FROM plans LIMIT 1"):
        for p in DEFAULT_PLANS:
            ex("INSERT INTO plans(code,name,price,days,enabled,order_limit,features) VALUES(?,?,?,?,?,?,?)", p)
    bootstrap_owner()


def bootstrap_owner():
    from .security import hash_password

    if not OWNER_EMAIL or not OWNER_PASSWORD:
        log.warning("OWNER_EMAIL / OWNER_PASSWORD not set - no owner account exists. Set them in Render environment.")
        return
    if len(OWNER_PASSWORD) < 10:
        log.warning("OWNER_PASSWORD must be at least 10 characters - owner not created.")
        return
    u = one("SELECT id,role FROM users WHERE email=?", (OWNER_EMAIL,))
    if not u:
        ex(
            "INSERT INTO users(id,email,name,pw_hash,role,perms,status,email_verified,ecosystem,lang,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (uid("u_"), OWNER_EMAIL, OWNER_NAME, hash_password(OWNER_PASSWORD), "owner", "*", "active", 1, "other", "en", now()),
        )
        log.info("Owner account created for %s", OWNER_EMAIL)
    elif u["role"] != "owner":
        ex("UPDATE users SET role='owner',perms='*',status='active',email_verified=1 WHERE id=?", (u["id"],))

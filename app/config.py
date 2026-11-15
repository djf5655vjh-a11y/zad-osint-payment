import os
import secrets
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "zadpay.db"

SECRET_FROM_ENV = bool(os.getenv("SECRET_KEY") and len(os.getenv("SECRET_KEY", "")) >= 32)


def _secret() -> str:
    s = os.getenv("SECRET_KEY", "")
    if len(s) >= 32:
        return s
    f = DATA_DIR / "secret.key"
    if f.exists():
        return f.read_text().strip()
    s = secrets.token_urlsafe(48)
    f.write_text(s)
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return s


SECRET_KEY = _secret()
BRAND = os.getenv("BRAND_NAME", "ZAD PAY")
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "").strip().lower()
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD", "")
OWNER_NAME = os.getenv("OWNER_NAME", "Owner")
# Hosting URL is auto-detected: PUBLIC_URL (optional override) -> Render's RENDER_EXTERNAL_URL -> request headers
PUBLIC_URL = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
FORCE_HTTPS = os.getenv("FORCE_HTTPS", "1") == "1"
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "14"))
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "") or SMTP_USER

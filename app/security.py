import base64
import collections
import hashlib
import hmac
import secrets
import threading
import time

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request

from .config import SECRET_KEY

_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(("enc:" + SECRET_KEY).encode()).digest()))


def enc(s: str) -> str:
    return _fernet.encrypt(s.encode()).decode()


def dec(s: str) -> str:
    try:
        return _fernet.decrypt(s.encode()).decode()
    except (InvalidToken, ValueError):
        return ""


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "s1$" + salt.hex() + "$" + h.hex()


def check_password(pw: str, stored: str) -> bool:
    try:
        _, s, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(s), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False


_DUMMY = hash_password("dummy-password-for-timing")
_hits: dict = collections.defaultdict(collections.deque)
_lock = threading.Lock()


def rate(key: str, limit: int, window: int):
    t = time.time()
    with _lock:
        d = _hits[key]
        while d and d[0] < t - window:
            d.popleft()
        if len(d) >= limit:
            raise HTTPException(429, "Too many requests. Please slow down and try again shortly.")
        d.append(t)
        if len(_hits) > 5000:
            for k in list(_hits):
                if not _hits[k] or _hits[k][-1] < t - 3600:
                    del _hits[k]


def client_ip(r: Request) -> str:
    xf = r.headers.get("x-forwarded-for")
    if xf:
        return xf.split(",")[0].strip()[:64]
    return r.client.host if r.client else "0.0.0.0"

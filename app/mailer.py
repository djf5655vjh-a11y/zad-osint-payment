import logging
import smtplib
from email.message import EmailMessage

from .config import SMTP_FROM, SMTP_HOST, SMTP_PASS, SMTP_PORT, SMTP_USER

log = logging.getLogger("zadpay")


def enabled() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS)


def send(to: str, subject: str, text: str):
    if not enabled():
        return
    try:
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = SMTP_FROM, to, subject
        m.set_content(text)
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as s:
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(m)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(m)
    except Exception as e:  # never crash a request because email failed
        log.error("Email send failed: %s", type(e).__name__)

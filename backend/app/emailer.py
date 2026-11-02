import logging
import re
import smtplib
import ssl
import time
from email.message import EmailMessage

import httpx

from .config import get_settings

log = logging.getLogger("cartbridge.email")

# In dev/test (no Resend key and no SMTP host), sent messages are kept here and logged.
outbox: list[EmailMessage] = []

# Tests set this to an httpx.MockTransport so no real request is made.
_transport: httpx.BaseTransport | None = None

_TOKEN_RE = re.compile(r"(token=)([\w-]{6})[\w-]*")


def mask_tokens(text: str) -> str:
    """Shortens any token=... in text so full tokens never reach logs."""
    return _TOKEN_RE.sub(r"\1\2...", text)


def mask_email(addr: str) -> str:
    """'jane.doe@example.com' -> 'j***@example.com' for logs and script output."""
    local, _, domain = addr.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def _send_resend(to: str, subject: str, body: str, html: str | None, idempotency_key: str | None) -> bool:
    """POST to the Resend HTTP API. One retry on a network error or 5xx (same Idempotency-Key, so it can't
    double-send). Never logs the API key, the body or the recipient's full address."""
    s = get_settings()
    payload = {"from": s.email_from, "to": [to], "subject": subject, "text": body, "reply_to": s.email_reply_to}
    if html:
        payload["html"] = html
    headers = {"Authorization": f"Bearer {s.resend_api_key}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key[:256]
    for attempt in (1, 2):
        try:
            with httpx.Client(timeout=15, transport=_transport) as client:
                r = client.post(s.resend_api_url, json=payload, headers=headers)
            if r.status_code < 300:
                return True
            log.error("Resend rejected email (HTTP %s, attempt %s)", r.status_code, attempt)
            if r.status_code < 500:
                return False
        except httpx.HTTPError as e:
            log.error("Resend request failed (%s, attempt %s)", type(e).__name__, attempt)
        if attempt == 1:
            time.sleep(0.5)
    return False


def send_email(to: str, subject: str, body: str, html: str | None = None,
               idempotency_key: str | None = None) -> bool:
    """Sends via Resend if RESEND_API_KEY is set, else SMTP if configured, else logs only (dev).
    Returns True if the message was handed to a provider. Never raises."""
    s = get_settings()
    if s.resend_api_key:
        return _send_resend(to, subject, body, html, idempotency_key)

    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    if not s.smtp_host:
        outbox.append(msg)
        log.warning("Email not configured; email to %s not sent: %s", mask_email(to), subject)
        # Dev convenience: show the body (with links) on the console, but never on an https/production host.
        shown = body if not s.base_url.startswith("https") else mask_tokens(body)
        print(f"\n--- EMAIL to {to} ---\n{subject}\n\n{shown}\n---------------\n", flush=True)
        return False

    if html:  # only on the real SMTP path; the dev outbox stays plain text
        msg.add_alternative(html, subtype="html")
    ctx = ssl.create_default_context()
    try:
        if s.smtp_ssl:
            with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=ctx, timeout=20) as smtp:
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password or "")
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
                if s.smtp_starttls:
                    smtp.starttls(context=ctx)
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password or "")
                smtp.send_message(msg)
    except Exception:  # never crash a request because email failed
        log.exception("Failed to send email to %s", mask_email(to))
        return False
    return True

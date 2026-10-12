import logging
import smtplib
import ssl
from email.message import EmailMessage

from .config import get_settings

log = logging.getLogger("cartbridge.email")

# In dev/test (no SMTP host), sent messages are kept here and logged.
outbox: list[EmailMessage] = []


def send_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    if not s.smtp_host:
        outbox.append(msg)
        log.warning("SMTP not configured; email to %s:\n%s\n%s", to, subject, body)
        print(f"\n--- EMAIL to {to} ---\n{subject}\n\n{body}\n---------------\n", flush=True)
        return

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
        log.exception("Failed to send email to %s", to)

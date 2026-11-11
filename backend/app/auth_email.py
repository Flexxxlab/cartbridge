"""Verification and password-reset emails: token issuing, templates and delivery.

Tokens are random, only their SHA-256 is stored, each is single-use and expires. The raw token
exists only in the email link. Delivery never raises (see emailer.send_email).
"""
import logging
from datetime import timedelta
from html import escape

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import get_settings
from .emailer import mask_email, send_email
from .models import EmailToken, User, utcnow
from .security import new_token

log = logging.getLogger("cartbridge.email")


def send_existing_account_email(user: User) -> None:
    """Placeholder: notify the existing account owner that a signup attempt was made.
    In production this would send an email informing them they already have an account.
    """
    # Simple log for now; actual email sending can be added later.
    log.info(f"Signup attempt for existing email {user.email} (user id {user.id})")



def issue_token(db: Session, user: User, purpose: str, ttl: timedelta, void_older: bool = True) -> tuple[str, str]:
    """Creates a token. Returns (raw, hash). With void_older the user's older unused tokens of the same purpose
    stop working. Reset tokens pass void_older=False: anyone could otherwise keep voiding a victim's pending
    reset link by requesting new ones; the 1 h expiry and single use already bound them."""
    now = utcnow()
    if void_older:
        db.execute(update(EmailToken).where(EmailToken.user_id == user.id, EmailToken.purpose == purpose,
                                            EmailToken.used_at.is_(None)).values(used_at=now))
    raw, h = new_token()
    db.add(EmailToken(user_id=user.id, token_hash=h, purpose=purpose, expires_at=now + ttl))
    db.commit()
    return raw, h


def _layout(heading: str, paragraphs: list[str], button_text: str, link: str, footer: str) -> str:
    s = get_settings()
    paras = "".join(f'<p style="margin:0 0 14px">{p}</p>' for p in paragraphs)
    return (
        '<!doctype html><html><body style="margin:0;padding:24px 12px;background:#f6f7f9;'
        'font:16px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1d2330">'
        '<table role="presentation" align="center" width="100%" style="max-width:520px"><tr><td>'
        f'<div style="font-weight:700;font-size:18px;margin:0 0 12px">{escape(s.app_name)}</div>'
        '<div style="background:#fff;border:1px solid #e4e7ec;border-radius:10px;padding:24px">'
        f'<h1 style="font-size:20px;margin:0 0 14px">{escape(heading)}</h1>{paras}'
        f'<p style="margin:20px 0"><a href="{escape(link, quote=True)}" style="background:#0b63ce;color:#fff;'
        f'text-decoration:none;padding:10px 18px;border-radius:8px;display:inline-block;font-weight:600">'
        f'{escape(button_text)}</a></p>'
        f'<p style="margin:0;font-size:13px;color:#667085;word-break:break-all">Or paste this link into your '
        f'browser:<br>{escape(link)}</p></div>'
        f'<p style="font-size:13px;color:#667085;margin:14px 0 0">{footer}</p>'
        '</td></tr></table></body></html>'
    )


def _footer() -> str:
    s = get_settings()
    return f'Questions? Reply to this email or write to {escape(s.support_email)}.'


def verification_email(user: User, link: str) -> tuple[str, str, str]:
    s = get_settings()
    hours = s.email_token_ttl_hours
    subject = f"Verify your {s.app_name} account"
    text = (f"Hi {user.username},\n\nConfirm your email to start creating API keys:\n{link}\n\n"
            f"This link works once and expires in {hours} hours. If you didn't sign up for {s.app_name}, "
            f"ignore this email.\n\nQuestions? Reply to this email or write to {s.support_email}.\n")
    html = _layout("Confirm your email",
                   [f"Hi {escape(user.username)}, confirm your email to start creating API keys.",
                    f"This link works once and expires in {hours} hours. If you didn't sign up for "
                    f"{escape(s.app_name)}, ignore this email."],
                   "Verify email", link, _footer())
    return subject, text, html


def reset_email(user: User, link: str) -> tuple[str, str, str]:
    s = get_settings()
    minutes = s.reset_token_ttl_minutes
    subject = f"Reset your {s.app_name} password"
    text = (f"Hi {user.username},\n\nSomeone asked to reset the password for your {s.app_name} account. "
            f"Choose a new one here:\n{link}\n\nThis link works once and expires in {minutes} minutes. "
            f"If you didn't ask for this, ignore this email; your password stays the same.\n\n"
            f"Questions? Reply to this email or write to {s.support_email}.\n")
    html = _layout("Reset your password",
                   [f"Hi {escape(user.username)}, someone asked to reset the password for your "
                    f"{escape(s.app_name)} account.",
                    f"This link works once and expires in {minutes} minutes. If you didn't ask for this, "
                    "ignore this email; your password stays the same."],
                   "Choose a new password", link, _footer())
    return subject, text, html


def _link(path: str, raw: str) -> str:
    return f"{get_settings().base_url.rstrip('/')}{path}?token={raw}"


def deliver_verification(user: User, raw: str, token_hash: str) -> bool:
    subject, text, html = verification_email(user, _link("/verify", raw))
    return send_email(user.email, subject, text, html, idempotency_key=f"verify-{token_hash[:40]}")


def deliver_reset(user: User, raw: str, token_hash: str) -> bool:
    subject, text, html = reset_email(user, _link("/reset", raw))
    return send_email(user.email, subject, text, html, idempotency_key=f"reset-{token_hash[:40]}")


def send_verification_now(db: Session, user: User) -> bool:
    """Issue a fresh verification token and send it, synchronously (used by the batch script)."""
    raw, h = issue_token(db, user, "verify", timedelta(hours=get_settings().email_token_ttl_hours))
    ok = deliver_verification(user, raw, h)
    if not ok:  # let a re-run try this user again
        db.execute(update(EmailToken).where(EmailToken.token_hash == h).values(expires_at=utcnow()))
        db.commit()
    log.info("verification email user_id=%s to=%s sent=%s", user.id, mask_email(user.email), ok)
    return ok


def unverified_users(db: Session, skip_recent: bool = True) -> list[User]:
    """Active unverified users. With skip_recent, users who got a verification link in the last
    email_token_ttl_hours are left out (a token is unexpired exactly that long), so a re-run or a crash
    followed by a re-run never mails the same person twice."""
    q = select(User).where(User.email_verified_at.is_(None), User.is_active.is_(True))
    if skip_recent:
        recent = select(EmailToken.user_id).where(EmailToken.purpose == "verify", EmailToken.expires_at > utcnow())
        q = q.where(User.id.not_in(recent))
    return list(db.scalars(q.order_by(User.id)))

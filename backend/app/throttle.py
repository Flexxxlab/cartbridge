"""Per-IP throttle for signup, login and resend. Stored in the database so it survives restarts.

Behind the reverse proxy the client IP comes from X-Forwarded-For (uvicorn --proxy-headers with
--forwarded-allow-ips set to the proxy; see the Dockerfile).
"""
from datetime import timedelta

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AuthAttempt, utcnow
from .ux import throttle_message

KEEP_SECONDS = 86400  # attempt rows older than this are pruned
WHAT = {"signup": "sign-up attempts", "login": "login attempts", "resend": "verification requests"}


def client_ip(request: Request) -> str:
    return (request.client.host if request.client else "unknown")[:64]


def rule(action: str) -> tuple[int, int]:
    s = get_settings()
    return getattr(s, f"throttle_{action}_max"), getattr(s, f"throttle_{action}_window")


def retry_after(db: Session, ip: str, action: str) -> int:
    """0 if this attempt is allowed (and records it), else seconds until the oldest attempt ages out."""
    limit, window = rule(action)
    now = utcnow()
    db.execute(delete(AuthAttempt).where(AuthAttempt.created_at <= now - timedelta(seconds=KEEP_SECONDS)))
    rows = db.scalars(select(AuthAttempt.created_at).where(
        AuthAttempt.ip == ip, AuthAttempt.action == action, AuthAttempt.created_at > now - timedelta(seconds=window)
    ).order_by(AuthAttempt.created_at)).all()
    if len(rows) >= limit:
        db.commit()
        frees_at = rows[len(rows) - limit] + timedelta(seconds=window)
        return max(1, int((frees_at - now).total_seconds()) + 1)
    db.add(AuthAttempt(ip=ip, action=action, created_at=now))
    db.commit()
    return 0


def throttled(request: Request, db: Session, action: str, render) -> HTMLResponse | None:
    """Returns a 429 page if this IP is over the limit for `action`, else None. `render` is web.render."""
    wait = retry_after(db, client_ip(request), action)
    if not wait:
        return None
    resp = render(request, "message.html", 429, title="Too many attempts",
                  message=throttle_message(WHAT[action], wait))
    resp.headers["Retry-After"] = str(wait)
    return resp

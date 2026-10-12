from datetime import timedelta

from fastapi import Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .api_auth import require_api_key
from .config import get_settings
from .db import get_db
from .models import CartRequestLog, User, utcnow


def _oldest_after(db: Session, user_id: int, since):
    return db.scalar(
        select(func.min(CartRequestLog.created_at)).where(
            CartRequestLog.user_id == user_id, CartRequestLog.created_at > since
        )
    )


def _count_since(db: Session, user_id: int, since) -> int:
    return db.scalar(
        select(func.count()).select_from(CartRequestLog).where(
            CartRequestLog.user_id == user_id, CartRequestLog.created_at > since
        )
    )


def enforce_cart_limits(user: User = Depends(require_api_key), db: Session = Depends(get_db)) -> User:
    s = get_settings()
    now = utcnow()
    window = timedelta(seconds=s.cart_window_seconds)
    day = timedelta(days=1)

    # Keep the table small: nothing older than a day matters.
    db.execute(delete(CartRequestLog).where(CartRequestLog.created_at <= now - day))

    for span, limit, label in (
        (window, s.cart_limit_per_window, f"{s.cart_limit_per_window} requests per {s.cart_window_seconds // 60} minutes"),
        (day, s.cart_limit_per_day, f"{s.cart_limit_per_day} requests per day"),
    ):
        if _count_since(db, user.id, now - span) >= limit:
            oldest = _oldest_after(db, user.id, now - span)
            retry = max(1, int((oldest + span - now).total_seconds()) + 1)
            db.commit()
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Rate limit exceeded ({label}). Try again in {retry} seconds.",
                headers={"Retry-After": str(retry)},
            )

    db.add(CartRequestLog(user_id=user.id, created_at=now))
    db.commit()
    return user

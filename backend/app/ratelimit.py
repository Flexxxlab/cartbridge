from datetime import timedelta

from fastapi import Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .api_auth import require_api_key
from .config import get_settings
from .db import get_db
from .models import CartRequestLog, PlatformAccess, User, utcnow

Tier = tuple[int, int]  # (window seconds, max requests)
MAX_WINDOW = 86400  # log rows older than a day are pruned


def parse_limits(text: str) -> list[Tier]:
    """"120:5,3600:10,86400:20" -> [(120, 5), (3600, 10), (86400, 20)]. Raises ValueError if malformed."""
    tiers = []
    for part in text.split(","):
        secs, count = part.strip().split(":")
        tier = (int(secs), int(count))
        if not 0 < tier[0] <= MAX_WINDOW or tier[1] < 0:
            raise ValueError(f"bad limit {part!r}: window must be 1..{MAX_WINDOW} seconds")
        tiers.append(tier)
    return tiers


def describe_window(seconds: int) -> str:
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds % size == 0:
            n = seconds // size
            return unit if n == 1 else f"{n} {unit}s"
    return f"{seconds} seconds"


def limits_for(db: Session, user: User) -> list[Tier]:
    """CartBridge's own Walmart access is metered tighter than a developer's own credentials."""
    s = get_settings()
    plat = db.get(PlatformAccess, user.id)
    if plat and plat.limits:
        return parse_limits(plat.limits)
    if plat:
        return [(s.cart_window_seconds, s.cart_limit_per_window), (86400, s.cart_limit_per_day)]
    return [(s.cart_window_seconds, s.own_key_limit_per_window), (86400, s.own_key_limit_per_day)]


def enforce_cart_limits(user: User = Depends(require_api_key), db: Session = Depends(get_db)) -> User:
    now = utcnow()
    db.execute(delete(CartRequestLog).where(CartRequestLog.created_at <= now - timedelta(seconds=MAX_WINDOW)))

    blocked: list[tuple[int, str]] = []  # (retry seconds, description)
    for seconds, limit in limits_for(db, user):
        since = now - timedelta(seconds=seconds)
        rows = db.scalars(select(CartRequestLog.created_at).where(
            CartRequestLog.user_id == user.id, CartRequestLog.created_at > since
        ).order_by(CartRequestLog.created_at)).all()
        if len(rows) >= limit:
            # The window frees a slot when the (len - limit + 1)th oldest request ages out.
            frees_at = rows[len(rows) - limit] + timedelta(seconds=seconds) if limit else now + timedelta(seconds=seconds)
            blocked.append((max(1, int((frees_at - now).total_seconds()) + 1),
                            f"{limit} requests per {describe_window(seconds)}"))
    if blocked:
        retry, label = max(blocked)
        db.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Rate limit exceeded ({label}). Try again in {retry} seconds.",
            headers={"Retry-After": str(retry)},
        )

    db.add(CartRequestLog(user_id=user.id, created_at=now))
    db.commit()
    return user

from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .api_auth import require_api_key
from .config import get_settings
from .db import get_db
from .models import CartRequestLog, PlatformAccess, UsageMonthly, User, UserLimits, utcnow
from .plans import get_plan
from .ux import format_duration, over_limit_message

Tier = tuple[int, int]  # (window seconds, max requests)
MAX_WINDOW = 86400  # log rows older than a day are pruned

# Windows offered on the dashboard.
WINDOW_CHOICES = [(60, "1 minute"), (120, "2 minutes"), (300, "5 minutes"), (900, "15 minutes"),
                  (3600, "1 hour"), (86400, "1 day")]
MAX_COUNT = 100_000
MONTHLY_LABEL = "calendar month"


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


def describe_plan(plan) -> str:
    """'10 requests per 5 minutes and 200 requests per calendar month.'"""
    parts = [f"{n} requests per {describe_window(secs)}" for secs, n in plan.tiers]
    if plan.monthly is not None:
        parts.append(f"{plan.monthly} requests per {MONTHLY_LABEL}")
    return (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]) + "."


def ceiling_for(db: Session, user: User) -> list[Tier]:
    """The most an account may use. Operator-granted access to the server's Walmart credentials is set
    per account; accounts with their own credentials get the limits of their plan."""
    s = get_settings()
    plat = db.get(PlatformAccess, user.id)
    if plat and plat.limits:
        return parse_limits(plat.limits)
    if plat:
        return [(s.cart_window_seconds, s.cart_limit_per_window), (86400, s.cart_limit_per_day)]
    return list(get_plan(user.plan).tiers)


def chosen_for(db: Session, user: User) -> list[Tier] | None:
    """Limits the user set on their dashboard, or None if they haven't."""
    row = db.get(UserLimits, user.id)
    return parse_limits(row.limits) if row and row.limits else None


def default_chosen(db: Session, user: User) -> list[Tier]:
    if db.get(PlatformAccess, user.id):
        return []  # the granted ceiling is the default
    return list(get_plan(user.plan).tiers)


def limits_for(db: Session, user: User) -> list[Tier]:
    """Enforced tiers: the user's own choice and the account ceiling, keeping the stricter per window."""
    chosen = chosen_for(db, user)
    merged: dict[int, int] = {}
    for secs, n in ceiling_for(db, user) + (chosen if chosen is not None else default_chosen(db, user)):
        merged[secs] = min(n, merged.get(secs, n))
    return sorted(merged.items())


def plan_name_for(db: Session, user: User) -> str:
    return "Platform" if db.get(PlatformAccess, user.id) else get_plan(user.plan).name


def month_key(now: datetime) -> str:
    return now.strftime("%Y-%m")


def next_month_start(now: datetime) -> datetime:
    return datetime(now.year + (now.month == 12), now.month % 12 + 1, 1)


def monthly_limit_for(db: Session, user: User) -> int | None:
    """Calendar-month cap from the plan. Operator-granted accounts have no monthly cap."""
    return None if db.get(PlatformAccess, user.id) else get_plan(user.plan).monthly


def monthly_used(db: Session, user: User, now: datetime) -> int:
    row = db.get(UsageMonthly, (user.id, month_key(now)))
    return row.count if row else 0


def usage_for(db: Session, user: User) -> list[dict]:
    """Per-tier usage for display: label, used, limit, seconds until a slot frees, and (when a tier is full)
    the shared over-limit message."""
    now = utcnow()
    plan = plan_name_for(db, user)
    out = []
    for seconds, limit in limits_for(db, user):
        rows = db.scalars(select(CartRequestLog.created_at).where(
            CartRequestLog.user_id == user.id, CartRequestLog.created_at > now - timedelta(seconds=seconds)
        ).order_by(CartRequestLog.created_at)).all()
        resets = int((rows[0] + timedelta(seconds=seconds) - now).total_seconds()) + 1 if rows else 0
        out.append({"label": f"per {describe_window(seconds)}", "used": len(rows), "limit": limit,
                    "resets_in": max(0, resets),
                    "message": over_limit_message(f"{limit} requests per {describe_window(seconds)}", plan, max(1, resets))
                    if len(rows) >= limit else None})
    cap = monthly_limit_for(db, user)
    if cap is not None:
        used = monthly_used(db, user, now)
        resets = int((next_month_start(now) - now).total_seconds())
        out.append({"label": f"per {MONTHLY_LABEL}", "used": used, "limit": cap, "resets_in": resets,
                    "message": over_limit_message(f"{cap} requests per {MONTHLY_LABEL}", plan, resets)
                    if used >= cap else None})
    for row in out:
        row["resets_text"] = format_duration(row["resets_in"]) if row["resets_in"] else ""
    return out


def _bump_monthly(db: Session, user_id: int, month: str) -> None:
    """Atomic count += 1. The first request of a month inserts; if a concurrent request won that insert
    (IntegrityError), retry the update once."""
    def bump() -> bool:
        return db.execute(update(UsageMonthly).where(UsageMonthly.user_id == user_id, UsageMonthly.month == month)
                          .values(count=UsageMonthly.count + 1)).rowcount > 0
    if bump():
        return
    try:
        with db.begin_nested():
            db.add(UsageMonthly(user_id=user_id, month=month, count=1))
    except IntegrityError:
        if not bump():
            raise


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
    cap = monthly_limit_for(db, user)
    if cap is not None and monthly_used(db, user, now) >= cap:
        blocked.append((max(1, int((next_month_start(now) - now).total_seconds())),
                        f"{cap} requests per {MONTHLY_LABEL}"))
    if blocked:
        retry, label = max(blocked)
        db.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            over_limit_message(label, plan_name_for(db, user), retry),
            headers={"Retry-After": str(retry)},
        )

    db.add(CartRequestLog(user_id=user.id, created_at=now))
    if cap is not None:
        _bump_monthly(db, user.id, month_key(now))
    db.commit()
    return user

"""Sign-up bot defences: signed form timestamp, honeypot, disposable-domain blocklist."""
import hashlib
import hmac
import time

from .config import get_settings

MIN_SECONDS = 3          # a human can't fill the form faster
MAX_SECONDS = 2 * 3600   # stale forms are dropped too

# Small blocklist of throwaway domains (seen in bot sign-ups + common disposable services).
DISPOSABLE_DOMAINS = frozenset({
    "formtests.info", "kupibit.me", "mailinator.com", "guerrillamail.com", "guerrillamail.net",
    "guerrillamail.org", "sharklasers.com", "10minutemail.com", "10minutemail.net", "tempmail.com",
    "temp-mail.org", "temp-mail.io", "yopmail.com", "yopmail.net", "trashmail.com", "throwawaymail.com",
    "getnada.com", "maildrop.cc", "dispostable.com", "fakeinbox.com", "mailnesia.com", "mintemail.com",
    "moakt.com", "emailondeck.com", "tempmailo.com", "mohmal.com", "burnermail.io",
})


def _sig(ts: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), f"signup:{ts}".encode(), hashlib.sha256).hexdigest()[:32]


def sign_timestamp(now: float | None = None) -> str:
    ts = str(int(now if now is not None else time.time()))
    return f"{ts}.{_sig(ts)}"


def timestamp_ok(value: str, now: float | None = None, min_seconds: int | None = None) -> bool:
    """True if value is an untampered timestamp issued between MIN and MAX seconds ago."""
    try:
        ts, sig = (value or "").split(".", 1)
        if not hmac.compare_digest(sig, _sig(ts)):
            return False
        age = (now if now is not None else time.time()) - int(ts)
    except (ValueError, TypeError):
        return False
    lo = get_settings().signup_min_seconds if min_seconds is None else min_seconds
    return lo <= age <= MAX_SECONDS


def looks_like_bot(honeypot: str, ts: str, now: float | None = None) -> bool:
    return bool(honeypot) or not timestamp_ok(ts, now)


def disposable(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].lower().strip(".")
    return any(domain == d or domain.endswith("." + d) for d in DISPOSABLE_DOMAINS)

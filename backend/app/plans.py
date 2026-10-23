"""Plan -> limits table. Every account has a `plan` (default "free").

Operator-granted accounts (PlatformAccess) use their own grants instead of the plan's limits.
Paid plans are "Contact us to buy" for now: no prices, no checkout.
"""
from dataclasses import dataclass

Tier = tuple[int, int]  # (window seconds, max requests)


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    tiers: tuple[Tier, ...]       # rolling windows
    monthly: int | None           # requests per calendar month (UTC), None = no monthly cap


PLANS: dict[str, Plan] = {
    # Bring your own Walmart key: 10 requests per 5 minutes and 200 per calendar month.
    "free": Plan("free", "Free", ((300, 10),), 200),
    # Not sold online yet; assigned by the operator after a "Contact us to buy" email.
    "pro": Plan("pro", "Pro", ((300, 100), (86400, 5000)), 100_000),
}
DEFAULT_PLAN = "free"


def get_plan(key: str | None) -> Plan:
    return PLANS.get(key or DEFAULT_PLAN, PLANS[DEFAULT_PLAN])

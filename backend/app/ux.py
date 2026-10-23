"""User-facing strings shared by the site, the API and the docs (see docs/self-serve-ux.md).

Duck copies these verbatim, so change the wording here and in that file together.
"""
from .config import get_settings


def verify_notice() -> str:
    return ("Verification emails can take longer than usual. "
            f"For immediate access, email {get_settings().support_email}.")


def forgot_password() -> str:
    return f"Forgot your password? Email {get_settings().support_email}"


CONTACT_TO_BUY = "Need more? Contact us to buy"


def contact_url() -> str:
    return f"mailto:{get_settings().support_email}"


def format_duration(seconds: int) -> str:
    """45 -> '45 seconds', 300 -> '5 minutes', 7200 -> '2 hours', 90000 -> '1 day 1 hour'."""
    seconds = max(1, int(seconds))
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    parts = []
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        n, seconds = divmod(seconds, size)
        if n:
            parts.append(f"{n} {unit}{'s' if n != 1 else ''}")
    return " ".join(parts[:2])


def over_limit_message(limit_label: str, plan_name: str, retry_seconds: int) -> str:
    """The one message shape for every over-limit error, in the API (`detail`) and on the dashboard.

    'Rate limit exceeded (10 requests per 5 minutes) on the Free plan. Try again in 4 minutes.
     Need more? Contact us to buy: mailto:helpdesk@flexxxlab.com'
    """
    return (f"Rate limit exceeded ({limit_label}) on the {plan_name} plan. "
            f"Try again in {format_duration(retry_seconds)}. {CONTACT_TO_BUY}: {contact_url()}")


def throttle_message(what: str, retry_seconds: int) -> str:
    return (f"Too many {what} from your network. Try again in {format_duration(retry_seconds)}. "
            f"Need help? Email {get_settings().support_email}.")

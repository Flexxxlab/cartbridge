from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "CartBridge"
    # Shown in the site footer on every page.
    support_email: str = "helpdesk@flexxxlab.com"
    company_name: str = "Flexxxlab"
    company_url: str = "https://flexxxlab.com/"
    source_url: str = "https://github.com/Flexxxlab/cartbridge"
    # Public URL of this server; used in verification email links.
    base_url: str = "http://localhost:8000"
    # Signs session cookies. MUST be overridden in production.
    secret_key: str = "dev-only-change-me"
    database_url: str = "sqlite:///./cartbridge.db"

    # SMTP. If smtp_host is empty, emails are printed to the console (dev mode).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "CartBridge <no-reply@example.com>"
    smtp_starttls: bool = True
    smtp_ssl: bool = False  # implicit TLS (port 465)

    # Resend (https://resend.com) transactional email. If resend_api_key is empty (and no SMTP host),
    # emails are only logged and the site shows the "email helpdesk" notices instead.
    resend_api_key: str | None = None
    resend_api_url: str = "https://api.resend.com/emails"
    email_from: str = "CartBridge <helpdesk@flexxxlab.com>"
    email_reply_to: str = "helpdesk@flexxxlab.com"

    email_token_ttl_hours: int = 24  # verification links
    reset_token_ttl_minutes: int = 60  # password-reset links
    max_api_keys_per_user: int = 10

    # /v1/cart limits for accounts that use CartBridge's own Walmart access (e.g. a first-party app).
    # Per user, across all of their API keys; per-account overrides via `python -m app.admin`.
    cart_limit_per_window: int = 2
    cart_window_seconds: int = 300
    cart_limit_per_day: int = 6
    # Limits for developers using their own Walmart credentials come from the plan table (app/plans.py).

    # Per-IP throttle on signup, login and resend: max attempts per window (seconds).
    throttle_signup_max: int = 5
    throttle_signup_window: int = 3600
    throttle_login_max: int = 20
    throttle_login_window: int = 900
    throttle_resend_max: int = 3  # verification emails per IP per window
    throttle_resend_window: int = 3600
    throttle_resend_acct_max: int = 3  # ... and per account
    throttle_resend_acct_window: int = 3600
    throttle_forgot_max: int = 5  # forgot-password requests per IP per window
    throttle_forgot_window: int = 3600
    throttle_forgot_email_max: int = 3  # ... and per requested address (hashed; applies whether or not it exists)
    throttle_forgot_email_window: int = 3600
    throttle_reset_max: int = 10  # set-new-password submissions per IP per window
    throttle_reset_window: int = 3600

    # Comma-separated usernames or emails allowed to use /admin (edit limits, grant platform access).
    admin_usernames: str = ""

    # Encrypts stored Walmart credentials. Falls back to a key derived from secret_key.
    encryption_key: str | None = None

    # Walmart: "mock" (no credentials, fake products) or "affiliate" (walmart.io Affiliate API)
    walmart_provider: str = "mock"
    walmart_consumer_id: str | None = None
    walmart_key_version: str = "1"
    walmart_private_key_path: str | None = None
    walmart_private_key: str | None = None  # PEM contents, alternative to the path
    walmart_publisher_id: str | None = None  # Impact Radius publisher id (affiliate tracking)
    walmart_api_base: str = "https://developer.api.walmart.com/api-proxy/service/affil/product/v2"
    walmart_cart_base: str = "https://affil.walmart.com/cart/addToCart"


    @property
    def email_enabled(self) -> bool:
        """True when real emails are sent (Resend key or SMTP host set)."""
        return bool(self.resend_api_key or self.smtp_host)

    @property
    def admins(self) -> set[str]:
        return {u.strip().lower() for u in self.admin_usernames.split(",") if u.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()

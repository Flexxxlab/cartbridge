from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "CartBridge"
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

    email_token_ttl_hours: int = 24
    max_api_keys_per_user: int = 10

    # /v1/cart limits per user (across all of their API keys)
    cart_limit_per_window: int = 2
    cart_window_seconds: int = 300
    cart_limit_per_day: int = 6

    # Walmart: "mock" (no credentials, fake products) or "affiliate" (walmart.io Affiliate API)
    walmart_provider: str = "mock"
    walmart_consumer_id: str | None = None
    walmart_key_version: str = "1"
    walmart_private_key_path: str | None = None
    walmart_private_key: str | None = None  # PEM contents, alternative to the path
    walmart_publisher_id: str | None = None  # Impact Radius publisher id (affiliate tracking)
    walmart_api_base: str = "https://developer.api.walmart.com/api-proxy/service/affil/product/v2"
    walmart_cart_base: str = "https://affil.walmart.com/cart/addToCart"


@lru_cache
def get_settings() -> Settings:
    return Settings()

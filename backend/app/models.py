from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None] = mapped_column(default=None)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None


class EmailToken(Base):
    __tablename__ = "email_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    purpose: Mapped[str] = mapped_column(String(20), default="verify")
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None] = mapped_column(default=None)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    prefix: Mapped[str] = mapped_column(String(16))  # shown in the dashboard, e.g. "cb_AbC123xy"
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(default=None)

    user: Mapped[User] = relationship(back_populates="api_keys")


class CartRequestLog(Base):
    """One row per /v1/cart call; used for rate limits and daily quotas."""

    __tablename__ = "cart_request_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class WalmartCredential(Base):
    """A developer's own Walmart Affiliate API credentials. The private key is stored encrypted."""

    __tablename__ = "walmart_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    consumer_id: Mapped[str] = mapped_column(String(100))
    key_version: Mapped[str] = mapped_column(String(20), default="1")
    publisher_id: Mapped[str | None] = mapped_column(String(50), default=None)
    private_key_enc: Mapped[str] = mapped_column(String(8192))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PlatformAccess(Base):
    """Accounts allowed to use CartBridge's own Walmart credentials (granted by the operator only)."""

    __tablename__ = "platform_access"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # Cart-request limits as "seconds:count,..." e.g. "120:5,3600:10,86400:20". Empty = server defaults.
    limits: Mapped[str | None] = mapped_column(String(200), default=None)


class UserLimits(Base):
    """Limits a user chose for their own account. Always enforced together with the account's ceiling."""

    __tablename__ = "user_limits"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    limits: Mapped[str] = mapped_column(String(200))  # "seconds:count,..."

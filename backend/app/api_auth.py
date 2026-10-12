from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import ApiKey, User, utcnow
from .security import sha256_hex


def require_api_key(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    raw = x_api_key
    if not raw and authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key", headers={"WWW-Authenticate": "Bearer"}
    )
    if not raw:
        raise unauthorized
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == sha256_hex(raw), ApiKey.revoked_at.is_(None)))
    if not key or not key.user.is_active or not key.user.is_verified:
        raise unauthorized
    key.last_used_at = utcnow()
    db.commit()
    return key.user

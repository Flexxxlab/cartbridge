"""Which Walmart credentials serve a given account's /v1/cart request."""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .config import get_settings
from .crypto import decrypt
from .models import PlatformAccess, User, WalmartCredential
from .stores import STORES, WalmartAffiliateProvider, get_provider
from .stores.base import StoreProvider


def walmart_source(db: Session, user: User) -> str:
    """'platform' (CartBridge's own access, operator-granted), 'own' (developer's credentials) or 'missing'."""
    if db.get(PlatformAccess, user.id):
        return "platform"
    if db.query(WalmartCredential.id).filter_by(user_id=user.id).first():
        return "own"
    return "missing"


async def provider_for(db: Session, user: User, store_id: str) -> tuple[StoreProvider, bool]:
    """Returns (provider, owned). Callers must `await provider.aclose()` when owned is True."""
    if store_id.lower() not in {s["id"] for s in STORES}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unsupported store '{store_id}'")
    s = get_settings()
    if s.walmart_provider != "affiliate":  # dev/test: fake products for everyone
        return get_provider(store_id), False
    source = walmart_source(db, user)
    if source == "platform":
        return get_provider(store_id), False
    if source == "own":
        cred = db.query(WalmartCredential).filter_by(user_id=user.id).one()
        provider = WalmartAffiliateProvider(
            s,
            consumer_id=cred.consumer_id,
            key_version=cred.key_version,
            private_key_pem=decrypt(cred.private_key_enc),
            publisher_id=cred.publisher_id,
        )
        return provider, True
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "No Walmart credentials on this account. Add your own Walmart Affiliate API credentials in the dashboard.",
    )

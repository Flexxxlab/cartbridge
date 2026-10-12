from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .cart import build_cart
from .api_auth import require_api_key
from .models import User
from .db import get_db
from .providers import provider_for, walmart_source
from .ratelimit import enforce_cart_limits
from .schemas import CartRequest, CartResponse, MeResponse
from .stores import STORES

router = APIRouter(prefix="/v1", tags=["api"])


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(require_api_key), db: Session = Depends(get_db)):
    return MeResponse(username=user.username, email=user.email, email_verified=user.is_verified,
                      walmart_credentials=walmart_source(db, user))


@router.get("/stores")
def stores(_: User = Depends(require_api_key)):
    return STORES


@router.post("/cart", response_model=CartResponse)
async def create_cart(req: CartRequest, user: User = Depends(enforce_cart_limits), db: Session = Depends(get_db)):
    provider, owned = await provider_for(db, user, req.store)
    try:
        return await build_cart(provider, req.items)
    finally:
        if owned:
            await provider.aclose()

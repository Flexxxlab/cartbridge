from fastapi import APIRouter, Depends, HTTPException, status

from .cart import build_cart
from .api_auth import require_api_key
from .models import User
from .ratelimit import enforce_cart_limits
from .schemas import CartRequest, CartResponse, MeResponse
from .stores import STORES, get_provider

router = APIRouter(prefix="/v1", tags=["api"])


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(require_api_key)):
    return MeResponse(username=user.username, email=user.email, email_verified=user.is_verified)


@router.get("/stores")
def stores(_: User = Depends(require_api_key)):
    return STORES


@router.post("/cart", response_model=CartResponse)
async def create_cart(req: CartRequest, _: User = Depends(enforce_cart_limits)):
    provider = get_provider(req.store)
    if not provider:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unsupported store '{req.store}'")
    return await build_cart(provider, req.items)

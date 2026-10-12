from ..config import get_settings
from .base import Product, StoreError, StoreProvider
from .walmart import WalmartAffiliateProvider, WalmartMockProvider

_providers: dict[str, StoreProvider] = {}

STORES = [{"id": "walmart", "name": "Walmart"}]


def get_provider(store_id: str) -> StoreProvider | None:
    store_id = store_id.lower()
    if store_id in _providers:
        return _providers[store_id]
    s = get_settings()
    if store_id == "walmart":
        p: StoreProvider = WalmartAffiliateProvider(s) if s.walmart_provider == "affiliate" else WalmartMockProvider(s)
    else:
        return None
    _providers[store_id] = p
    return p


async def close_providers() -> None:
    for p in _providers.values():
        await p.aclose()
    _providers.clear()


__all__ = ["Product", "StoreError", "StoreProvider", "STORES", "get_provider", "close_providers"]

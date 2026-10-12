"""Walmart providers.

Affiliate API (walmart.io): every request is signed with your RSA private key.
  String to sign = "{consumer_id}\n{timestamp_ms}\n{key_version}\n"
  Signature      = base64(RSA-SHA256-PKCS1v15(string))

Cart link: https://affil.walmart.com/cart/addToCart?items=ITEMID|QTY,ITEMID|QTY
Opening it (WebView or browser / Walmart app) adds every item to that session's cart.
"""
import base64
import hashlib
import re
import time

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from ..config import Settings
from .base import Product, StoreError, StoreProvider

_ITEM_ID = re.compile(r"^\d{1,20}$")


class _WalmartCartMixin:
    cart_base: str

    def is_valid_item_id(self, item_id: str) -> bool:
        return bool(_ITEM_ID.match(item_id))

    def build_cart_url(self, lines: list[tuple[str, int]]) -> str:
        for item_id, _ in lines:
            if not _ITEM_ID.match(item_id):
                raise ValueError(f"invalid Walmart item id: {item_id!r}")
        items = ",".join(f"{item_id}|{qty}" for item_id, qty in lines)
        return f"{self.cart_base}?items={items}"


def sign_walmart_request(key, consumer_id: str, key_version: str, ts_ms: str) -> str:
    """key: a loaded RSA private key (cryptography)."""
    to_sign = f"{consumer_id}\n{ts_ms}\n{key_version}\n".encode()
    sig = key.sign(to_sign, padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode()


class WalmartAffiliateProvider(_WalmartCartMixin, StoreProvider):
    id = "walmart"
    name = "Walmart"

    def __init__(self, s: Settings):
        if not s.walmart_consumer_id:
            raise RuntimeError("WALMART_CONSUMER_ID is required for the affiliate provider")
        if s.walmart_private_key:
            pem = s.walmart_private_key.replace("\\n", "\n").encode()
        elif s.walmart_private_key_path:
            with open(s.walmart_private_key_path, "rb") as f:
                pem = f.read()
        else:
            raise RuntimeError("WALMART_PRIVATE_KEY or WALMART_PRIVATE_KEY_PATH is required")
        self._key = serialization.load_pem_private_key(pem, password=None)
        self.consumer_id = s.walmart_consumer_id
        self.key_version = s.walmart_key_version
        self.publisher_id = s.walmart_publisher_id
        self.api_base = s.walmart_api_base.rstrip("/")
        self.cart_base = s.walmart_cart_base
        self._client = httpx.AsyncClient(timeout=10)

    def _headers(self) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        return {
            "WM_CONSUMER.ID": self.consumer_id,
            "WM_CONSUMER.INTIMESTAMP": ts,
            "WM_SEC.KEY_VERSION": self.key_version,
            "WM_SEC.AUTH_SIGNATURE": sign_walmart_request(self._key, self.consumer_id, self.key_version, ts),
            "Accept": "application/json",
        }

    async def search(self, query: str, limit: int = 10) -> list[Product]:
        params: dict[str, str | int] = {"query": query, "numItems": limit}
        if self.publisher_id:
            params["publisherId"] = self.publisher_id
        try:
            r = await self._client.get(f"{self.api_base}/search", params=params, headers=self._headers())
        except httpx.HTTPError as e:
            raise StoreError(f"Walmart search failed: {e}") from e
        if r.status_code == 404:
            return []
        if r.status_code >= 400:
            raise StoreError(f"Walmart search HTTP {r.status_code}: {r.text[:200]}")
        out = []
        for it in r.json().get("items", []) or []:
            if it.get("itemId") is None:
                continue
            available = bool(it.get("availableOnline")) or str(it.get("stock", "")).lower() == "available"
            out.append(
                Product(
                    item_id=str(it["itemId"]),
                    name=it.get("name", ""),
                    price=it.get("salePrice") or it.get("msrp"),
                    image_url=it.get("mediumImage") or it.get("thumbnailImage"),
                    product_url=it.get("productTrackingUrl") or it.get("productUrl"),
                    available=available,
                )
            )
        return out

    async def aclose(self) -> None:
        await self._client.aclose()


class WalmartMockProvider(_WalmartCartMixin, StoreProvider):
    """No credentials needed. Returns deterministic fake products for development and tests."""

    id = "walmart"
    name = "Walmart"

    def __init__(self, s: Settings):
        self.cart_base = s.walmart_cart_base

    async def search(self, query: str, limit: int = 10) -> list[Product]:
        q = query.strip()
        if not q or q.lower().startswith("zzz"):  # lets tests exercise the "unmatched" path
            return []
        item_id = str(10_000_000 + int(hashlib.sha256(q.lower().encode()).hexdigest(), 16) % 89_999_999)
        return [
            Product(
                item_id=item_id,
                name=f"Great Value {q.title()}",
                price=round(1 + (int(item_id) % 900) / 100, 2),
                image_url=None,
                product_url=f"https://www.walmart.com/ip/{item_id}",
                available=True,
            )
        ]

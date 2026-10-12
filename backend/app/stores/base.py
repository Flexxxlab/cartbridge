from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Product:
    item_id: str
    name: str
    price: float | None = None
    image_url: str | None = None
    product_url: str | None = None
    available: bool = True


class StoreError(Exception):
    """Upstream store API failure."""


class StoreProvider(ABC):
    id: str
    name: str

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[Product]:
        ...

    @abstractmethod
    def build_cart_url(self, lines: list[tuple[str, int]]) -> str:
        """lines = [(item_id, quantity), ...] -> a URL that adds them all to the cart."""

    def is_valid_item_id(self, item_id: str) -> bool:
        return bool(item_id)

    async def aclose(self) -> None:
        pass

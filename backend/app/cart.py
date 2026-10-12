import asyncio
import math

from .schemas import CartLine, CartResponse, IngredientIn, MatchedProduct, UnmatchedLine
from .stores import Product, StoreError, StoreProvider

# Units where "quantity" means "number of packages/units to buy".
COUNT_UNITS = {
    "", "each", "ea", "count", "ct", "pc", "pcs", "piece", "pieces", "item", "items", "unit", "units",
    "can", "cans", "bottle", "bottles", "pack", "packs", "package", "packages", "bag", "bags",
    "box", "boxes", "jar", "jars", "carton", "cartons", "loaf", "loaves", "bunch", "bunches", "head", "heads",
}


def cart_quantity_for(ing: IngredientIn) -> tuple[int, str | None]:
    if ing.cart_quantity:
        return ing.cart_quantity, None
    unit = (ing.unit or "").strip().lower()
    if unit in COUNT_UNITS:
        return min(99, max(1, math.ceil(ing.quantity))), None
    # Weight/volume (lb, oz, cup, g...) — package size is unknown, so add one package.
    return 1, f"Added 1 package for {ing.quantity:g} {ing.unit}; adjust in cart if needed."


def pick_product(products: list[Product]) -> Product | None:
    for p in products:
        if p.available:
            return p
    return None


async def build_cart(provider: StoreProvider, items: list[IngredientIn]) -> CartResponse:
    sem = asyncio.Semaphore(5)

    async def resolve(ing: IngredientIn) -> Product | str:
        if ing.item_id:
            if not provider.is_valid_item_id(ing.item_id):
                return "invalid item_id for this store"
            return Product(item_id=ing.item_id, name=ing.name)
        async with sem:
            try:
                results = await provider.search(ing.name)
            except StoreError:
                return "store search failed; try again"
        p = pick_product(results)
        return p if p else "no available product found"

    resolved = await asyncio.gather(*(resolve(i) for i in items))

    lines: list[CartLine] = []
    unmatched: list[UnmatchedLine] = []
    merged: dict[str, int] = {}  # same product requested twice -> sum quantities
    for ing, res in zip(items, resolved):
        if isinstance(res, str):
            unmatched.append(UnmatchedLine(ingredient=ing, reason=res))
            continue
        qty, note = cart_quantity_for(ing)
        merged[res.item_id] = min(99, merged.get(res.item_id, 0) + qty)
        lines.append(
            CartLine(
                ingredient=ing,
                product=MatchedProduct(
                    item_id=res.item_id, name=res.name, price=res.price,
                    image_url=res.image_url, product_url=res.product_url,
                ),
                cart_quantity=qty,
                note=note,
            )
        )

    cart_url = provider.build_cart_url(list(merged.items())) if merged else None
    priced = [l.product.price * l.cart_quantity for l in lines if l.product.price is not None]
    total = round(sum(priced), 2) if priced and len(priced) == len(lines) else None
    return CartResponse(store=provider.id, cart_url=cart_url, lines=lines, unmatched=unmatched, estimated_total=total)

from pydantic import BaseModel, Field


class IngredientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200, examples=["chicken breast"])
    quantity: float = Field(default=1, gt=0, le=1000)
    unit: str | None = Field(default=None, max_length=30, examples=["lb", "each", "can"])
    # Optional overrides
    item_id: str | None = Field(default=None, max_length=20, description="Skip search and use this store item id")
    cart_quantity: int | None = Field(default=None, ge=1, le=99, description="Exact number of units to add")


class CartRequest(BaseModel):
    store: str = Field(default="walmart", examples=["walmart"])
    items: list[IngredientIn] = Field(min_length=1, max_length=100)


class MatchedProduct(BaseModel):
    item_id: str
    name: str
    price: float | None = None
    image_url: str | None = None
    product_url: str | None = None


class CartLine(BaseModel):
    ingredient: IngredientIn
    product: MatchedProduct
    cart_quantity: int
    note: str | None = None


class UnmatchedLine(BaseModel):
    ingredient: IngredientIn
    reason: str


class CartResponse(BaseModel):
    store: str
    cart_url: str | None = Field(description="Open in a WebView, browser or the store app to add all items")
    lines: list[CartLine]
    unmatched: list[UnmatchedLine]
    estimated_total: float | None = None


class MeResponse(BaseModel):
    username: str
    email: str
    email_verified: bool

/// Supported stores.
enum CartStore {
  walmart(
    id: 'walmart',
    displayName: 'Walmart',
    cartPageUrl: 'https://www.walmart.com/cart',
  );

  const CartStore({required this.id, required this.displayName, required this.cartPageUrl});

  /// Id sent to the backend.
  final String id;
  final String displayName;

  /// The store's plain cart page (no items added). Used for "refresh" and
  /// "view cart in app" so we never re-add items by reloading the add-to-cart link.
  final String cartPageUrl;

  static CartStore? fromId(String id) {
    for (final s in CartStore.values) {
      if (s.id == id) return s;
    }
    return null;
  }
}

/// One ingredient to buy.
class Ingredient {
  const Ingredient(
    this.name, {
    this.quantity = 1,
    this.unit,
    this.itemId,
    this.cartQuantity,
  });

  /// e.g. "chicken breast"
  final String name;

  /// e.g. 2
  final double quantity;

  /// e.g. "lb", "each", "can". Count-like units ("each", "can", null...) become
  /// that many units in the cart; weight/volume units add one package.
  final String? unit;

  /// Optional: skip search and use this exact store item id.
  final String? itemId;

  /// Optional: exact number of units to add (1–99).
  final int? cartQuantity;

  Map<String, dynamic> toJson() => {
        'name': name,
        'quantity': quantity,
        if (unit != null) 'unit': unit,
        if (itemId != null) 'item_id': itemId,
        if (cartQuantity != null) 'cart_quantity': cartQuantity,
      };

  factory Ingredient.fromJson(Map<String, dynamic> j) => Ingredient(
        j['name'] as String,
        quantity: (j['quantity'] as num?)?.toDouble() ?? 1,
        unit: j['unit'] as String?,
        itemId: j['item_id'] as String?,
        cartQuantity: j['cart_quantity'] as int?,
      );
}

class MatchedProduct {
  const MatchedProduct({required this.itemId, required this.name, this.price, this.imageUrl, this.productUrl});

  final String itemId;
  final String name;
  final double? price;
  final String? imageUrl;
  final String? productUrl;

  factory MatchedProduct.fromJson(Map<String, dynamic> j) => MatchedProduct(
        itemId: j['item_id'] as String,
        name: j['name'] as String,
        price: (j['price'] as num?)?.toDouble(),
        imageUrl: j['image_url'] as String?,
        productUrl: j['product_url'] as String?,
      );
}

class CartLine {
  const CartLine({required this.ingredient, required this.product, required this.cartQuantity, this.note});

  final Ingredient ingredient;
  final MatchedProduct product;
  final int cartQuantity;
  final String? note;

  factory CartLine.fromJson(Map<String, dynamic> j) => CartLine(
        ingredient: Ingredient.fromJson(j['ingredient'] as Map<String, dynamic>),
        product: MatchedProduct.fromJson(j['product'] as Map<String, dynamic>),
        cartQuantity: j['cart_quantity'] as int,
        note: j['note'] as String?,
      );
}

class UnmatchedIngredient {
  const UnmatchedIngredient({required this.ingredient, required this.reason});

  final Ingredient ingredient;
  final String reason;

  factory UnmatchedIngredient.fromJson(Map<String, dynamic> j) => UnmatchedIngredient(
        ingredient: Ingredient.fromJson(j['ingredient'] as Map<String, dynamic>),
        reason: j['reason'] as String,
      );
}

class CartResult {
  const CartResult({
    required this.store,
    required this.cartUrl,
    required this.lines,
    required this.unmatched,
    this.estimatedTotal,
  });

  final CartStore store;

  /// Opening this URL adds every matched item to the cart. Null if nothing matched.
  final String? cartUrl;
  final List<CartLine> lines;
  final List<UnmatchedIngredient> unmatched;
  final double? estimatedTotal;

  bool get hasItems => cartUrl != null && lines.isNotEmpty;

  factory CartResult.fromJson(Map<String, dynamic> j) => CartResult(
        store: CartStore.fromId(j['store'] as String) ?? CartStore.walmart,
        cartUrl: j['cart_url'] as String?,
        lines: (j['lines'] as List).map((e) => CartLine.fromJson(e as Map<String, dynamic>)).toList(),
        unmatched:
            (j['unmatched'] as List).map((e) => UnmatchedIngredient.fromJson(e as Map<String, dynamic>)).toList(),
        estimatedTotal: (j['estimated_total'] as num?)?.toDouble(),
      );
}

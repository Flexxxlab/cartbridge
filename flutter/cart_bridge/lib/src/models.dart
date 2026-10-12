/// Supported stores.
enum CartStore {
  /// Walmart, via the Walmart Affiliate API.
  walmart(
    id: 'walmart',
    displayName: 'Walmart',
    cartPageUrl: 'https://www.walmart.com/cart',
  );

  const CartStore(
      {required this.id, required this.displayName, required this.cartPageUrl});

  /// Id sent to the backend.
  /// The identifier the server uses for this store, e.g. `walmart`.
  final String id;

  /// A name suitable for showing to users.
  final String displayName;

  /// The store's plain cart page (no items added). Used for "refresh" and
  /// "view cart in app" so we never re-add items by reloading the add-to-cart link.
  /// The store's plain cart page, loaded on refresh so items aren't re-added.
  final String cartPageUrl;

  /// Returns the store with the given server [id], or `null` if unknown.
  static CartStore? fromId(String id) {
    for (final s in CartStore.values) {
      if (s.id == id) return s;
    }
    return null;
  }
}

/// One ingredient to buy.
class Ingredient {
  /// Creates an ingredient to look up in the store.
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

  /// The JSON body the CartBridge server expects; unset fields are omitted.
  Map<String, dynamic> toJson() => {
        'name': name,
        'quantity': quantity,
        if (unit != null) 'unit': unit,
        if (itemId != null) 'item_id': itemId,
        if (cartQuantity != null) 'cart_quantity': cartQuantity,
      };

  /// Parses an ingredient from its JSON form.
  factory Ingredient.fromJson(Map<String, dynamic> j) => Ingredient(
        j['name'] as String,
        quantity: (j['quantity'] as num?)?.toDouble() ?? 1,
        unit: j['unit'] as String?,
        itemId: j['item_id'] as String?,
        cartQuantity: j['cart_quantity'] as int?,
      );
}

/// A store product that an ingredient was matched to.
class MatchedProduct {
  /// Creates a matched product.
  const MatchedProduct(
      {required this.itemId,
      required this.name,
      this.price,
      this.imageUrl,
      this.productUrl});

  /// The store's identifier for the product.
  final String itemId;

  /// The product's display name.
  final String name;

  /// The unit price, if the store reported one.
  final double? price;

  /// A product image, if available.
  final String? imageUrl;

  /// A link to the product page, if available.
  final String? productUrl;

  /// Parses a matched product from the server's JSON.
  factory MatchedProduct.fromJson(Map<String, dynamic> j) => MatchedProduct(
        itemId: j['item_id'] as String,
        name: j['name'] as String,
        price: (j['price'] as num?)?.toDouble(),
        imageUrl: j['image_url'] as String?,
        productUrl: j['product_url'] as String?,
      );
}

/// One cart line: a requested ingredient, its matched product and quantity.
class CartLine {
  /// Creates a cart line.
  const CartLine(
      {required this.ingredient,
      required this.product,
      required this.cartQuantity,
      this.note});

  /// The ingredient that was requested.
  final Ingredient ingredient;

  /// The product it was matched to.
  final MatchedProduct product;

  /// How many units were added to the cart.
  final int cartQuantity;

  /// Extra context, e.g. when a weight or volume became one package.
  final String? note;

  /// Parses a cart line from the server's JSON.
  factory CartLine.fromJson(Map<String, dynamic> j) => CartLine(
        ingredient:
            Ingredient.fromJson(j['ingredient'] as Map<String, dynamic>),
        product: MatchedProduct.fromJson(j['product'] as Map<String, dynamic>),
        cartQuantity: j['cart_quantity'] as int,
        note: j['note'] as String?,
      );
}

/// An ingredient that could not be added to the cart, with the reason.
class UnmatchedIngredient {
  /// Creates an unmatched-ingredient record.
  const UnmatchedIngredient({required this.ingredient, required this.reason});

  /// The ingredient that could not be added.
  final Ingredient ingredient;

  /// Why it was skipped.
  final String reason;

  /// Parses an unmatched ingredient from the server's JSON.
  factory UnmatchedIngredient.fromJson(Map<String, dynamic> j) =>
      UnmatchedIngredient(
        ingredient:
            Ingredient.fromJson(j['ingredient'] as Map<String, dynamic>),
        reason: j['reason'] as String,
      );
}

/// The outcome of building a cart: a link plus what matched and what didn't.
class CartResult {
  /// Creates a cart result.
  const CartResult({
    required this.store,
    required this.cartUrl,
    required this.lines,
    required this.unmatched,
    this.estimatedTotal,
  });

  /// The store the cart was built for.
  final CartStore store;

  /// Opening this URL adds every matched item to the cart. Null if nothing matched.
  /// A link that adds every matched item to the store's cart, or `null` when
  /// nothing matched.
  final String? cartUrl;

  /// The matched items, one per product.
  final List<CartLine> lines;

  /// Ingredients that could not be matched to a product.
  final List<UnmatchedIngredient> unmatched;

  /// The estimated cart total, if prices were available.
  final double? estimatedTotal;

  /// Whether there is a cart link with at least one item.
  bool get hasItems => cartUrl != null && lines.isNotEmpty;

  /// Parses a cart result from the server's JSON.
  factory CartResult.fromJson(Map<String, dynamic> j) => CartResult(
        store: CartStore.fromId(j['store'] as String) ?? CartStore.walmart,
        cartUrl: j['cart_url'] as String?,
        lines: (j['lines'] as List)
            .map((e) => CartLine.fromJson(e as Map<String, dynamic>))
            .toList(),
        unmatched: (j['unmatched'] as List)
            .map((e) => UnmatchedIngredient.fromJson(e as Map<String, dynamic>))
            .toList(),
        estimatedTotal: (j['estimated_total'] as num?)?.toDouble(),
      );
}

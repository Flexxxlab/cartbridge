import 'package:cart_bridge/cart_bridge.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Ingredient serializes only set fields', () {
    expect(
        const Ingredient('milk').toJson(), {'name': 'milk', 'quantity': 1.0});
    expect(
        const Ingredient('eggs', quantity: 12, unit: 'each', cartQuantity: 1)
            .toJson()['cart_quantity'],
        1);
  });

  test('CartResult parses backend response', () {
    final r = CartResult.fromJson({
      'store': 'walmart',
      'cart_url': 'https://affil.walmart.com/cart/addToCart?items=1|2',
      'lines': [
        {
          'ingredient': {'name': 'milk', 'quantity': 2, 'unit': null},
          'product': {'item_id': '1', 'name': 'Milk', 'price': 3.5},
          'cart_quantity': 2,
          'note': null,
        }
      ],
      'unmatched': [
        {
          'ingredient': {'name': 'saffron', 'quantity': 1},
          'reason': 'no available product found'
        }
      ],
      'estimated_total': 7.0,
    });
    expect(r.store, CartStore.walmart);
    expect(r.hasItems, isTrue);
    expect(r.lines.single.product.price, 3.5);
    expect(r.unmatched.single.ingredient.name, 'saffron');
  });
}

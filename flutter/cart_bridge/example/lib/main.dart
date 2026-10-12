import 'package:cart_bridge/cart_bridge.dart';
import 'package:flutter/material.dart';

// Pass at build time: flutter run --dart-define=CB_API_KEY=cb_... --dart-define=CB_BASE_URL=http://10.0.2.2:8000
/// CartBridge API key, supplied at build time.
const apiKey = String.fromEnvironment('CB_API_KEY');

/// CartBridge server URL, supplied at build time.
const baseUrl =
    String.fromEnvironment('CB_BASE_URL', defaultValue: 'http://10.0.2.2:8000');

void main() => runApp(const MaterialApp(home: RecipePage()));

/// A sample recipe with a button that sends its ingredients to CartBridge.
class RecipePage extends StatefulWidget {
  /// Creates the page.
  const RecipePage({super.key});

  @override
  State<RecipePage> createState() => _RecipePageState();
}

class _RecipePageState extends State<RecipePage> {
  final _bridge = CartBridge(apiKey: apiKey, baseUrl: baseUrl);
  bool _loading = false;

  final _items = const [
    Ingredient('chicken breast', quantity: 2, unit: 'lb'),
    Ingredient('large eggs', quantity: 1, unit: 'each'),
    Ingredient('basmati rice', quantity: 1, unit: 'bag'),
    Ingredient('diced tomatoes', quantity: 2, unit: 'can'),
  ];

  Future<void> _shop() async {
    setState(() => _loading = true);
    try {
      final result = await _bridge.openCart(context,
          items: _items, store: CartStore.walmart);
      if (!result.hasItems && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('No items could be matched')));
      }
    } on CartBridgeException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e.message)));
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Butter chicken')),
        body: ListView(children: [
          for (final i in _items)
            ListTile(
                title: Text(i.name),
                trailing: Text('${i.quantity} ${i.unit ?? ''}')),
        ]),
        floatingActionButton: FloatingActionButton.extended(
          onPressed: _loading ? null : _shop,
          icon: _loading
              ? const SizedBox.square(
                  dimension: 18,
                  child: CircularProgressIndicator(strokeWidth: 2))
              : const Icon(Icons.shopping_cart),
          label: const Text('Shop at Walmart'),
        ),
      );
}

import 'package:flutter/material.dart';

import 'cart_webview_page.dart';
import 'client.dart';
import 'models.dart';

/// One-call API: build the cart on the backend, then open it in a WebView.
///
/// ```dart
/// final bridge = CartBridge(apiKey: 'cb_...', baseUrl: 'https://api.example.com');
/// await bridge.openCart(context, items: [
///   Ingredient('chicken breast', quantity: 2, unit: 'lb'),
///   Ingredient('large eggs', quantity: 12, unit: 'each'),
/// ]);
/// ```
class CartBridge {
  /// Creates a bridge that talks to the CartBridge server at [baseUrl].
  ///
  /// Pass [client] to supply a preconfigured [CartBridgeClient]; [apiKey] and
  /// [baseUrl] are then not used.
  CartBridge(
      {required String apiKey,
      required String baseUrl,
      CartBridgeClient? client})
      : client = client ?? CartBridgeClient(apiKey: apiKey, baseUrl: baseUrl);

  /// The underlying client, for calls that don't need the WebView page.
  final CartBridgeClient client;

  /// Returns the [CartResult] (or throws [CartBridgeException]).
  /// If nothing could be matched, no WebView is opened and the result is returned as-is.
  Future<CartResult> openCart(
    BuildContext context, {
    required List<Ingredient> items,
    CartStore store = CartStore.walmart,
    String? userAgent,
  }) async {
    final result = await client.createCart(items: items, store: store);
    if (!result.hasItems || !context.mounted) return result;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => CartWebViewPage(
          cartUrl: result.cartUrl!,
          store: result.store,
          unmatched: result.unmatched,
          userAgent: userAgent,
        ),
      ),
    );
    return result;
  }
}

# cart_bridge

Turn a list of ingredients into a filled Walmart cart and open it in a WebView.

```dart
final bridge = CartBridge(apiKey: 'cb_...', baseUrl: 'https://your-server');
await bridge.openCart(context, items: [
  Ingredient('chicken breast', quantity: 2, unit: 'lb'),
  Ingredient('eggs', cartQuantity: 1),
]);
```

Needs a running CartBridge server (see the repo root README). Don't ship a real
API key inside a published app. Point `baseUrl` at your own server, which holds the key.

Lower level: `CartBridgeClient.createCart(...)` returns a `CartResult` with `cartUrl`,
`lines` and `unmatched`.

Android needs the INTERNET permission. See the repo README for platform notes.

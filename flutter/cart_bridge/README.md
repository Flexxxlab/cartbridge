# cart_bridge

Turn a list of ingredients into a filled grocery cart. Send ingredient names and
quantities to a [CartBridge](https://github.com/Flexxxlab/cartbridge) server and get
back a store cart link, then open it in an in-app WebView or hand it to the store's app.
Walmart is supported today.

## Features

- **One call to a filled cart.** `CartBridge.openCart` builds the cart on the server and
  opens it in a WebView.
- **Sensible quantities.** Count-like units (`each`, `can`, none) add that many items;
  weight and volume units (`lb`, `oz`, `cup`) add one package with an explanatory note.
- **Transparent matching.** Every result lists what was matched, what could not be, and
  an estimated total.
- **Checkout in the store.** Users sign in inside the WebView, or tap **Open in app** to
  continue in the Walmart app or browser.
- **Low-level client** (`CartBridgeClient`) for building your own UI.

## Requirements

- A running CartBridge server and an API key. See the
  [server documentation](https://github.com/Flexxxlab/cartbridge#readme).
- Flutter 3.24 or newer.
- Android, iOS or macOS. (The WebView plugin does not support web, Windows or Linux.)

## Installation

```yaml
dependencies:
  cart_bridge: ^0.1.0
```

```sh
flutter pub add cart_bridge
```

### Platform setup

**Android** — allow network access in `android/app/src/main/AndroidManifest.xml`:

```xml
<uses-permission android:name="android.permission.INTERNET"/>
```

To let **Open in app** reach the Walmart app on Android 11+, declare the intent you launch:

```xml
<queries>
  <intent>
    <action android:name="android.intent.action.VIEW"/>
    <data android:scheme="https"/>
  </intent>
</queries>
```

**iOS / macOS** — nothing extra for HTTPS servers.

## Usage

```dart
import 'package:cart_bridge/cart_bridge.dart';

final bridge = CartBridge(
  apiKey: 'YOUR_KEY',
  baseUrl: 'https://your-cartbridge-server.example.com',
);

final result = await bridge.openCart(
  context,
  items: const [
    Ingredient('chicken breast', quantity: 2, unit: 'lb'),
    Ingredient('large eggs', quantity: 12, unit: 'each'),
    Ingredient('olive oil'),
  ],
);

if (result.unmatched.isNotEmpty) {
  // Ingredients that could not be matched; the WebView also shows a banner.
}
```

`openCart` returns a `CartResult`. If nothing could be matched, no WebView is opened.

### Handling errors

```dart
try {
  await bridge.openCart(context, items: items);
} on CartBridgeException catch (e) {
  if (e.isUnauthorized) {
    // Invalid API key.
  } else if (e.statusCode == 429) {
    // Rate limited: e.message says how long to wait.
  } else {
    // Network error, timeout or server error: e.message has details.
  }
}
```

### Building your own UI

```dart
final client = CartBridgeClient(apiKey: 'YOUR_KEY', baseUrl: 'https://...');
final result = await client.createCart(items: items);

result.cartUrl;        // open this to add everything to the cart
result.lines;          // matched products, quantities and notes
result.unmatched;      // what could not be added, with reasons
result.estimatedTotal; // if prices were available

Navigator.push(context, MaterialPageRoute(
  builder: (_) => CartWebViewPage(cartUrl: result.cartUrl!, unmatched: result.unmatched),
));
```

### Controlling quantities

| Field | Effect |
| --- | --- |
| `quantity` + `unit` | Count-like units add that many; weight/volume units add one package |
| `cartQuantity` | Exact number of units to add (1–99), overriding the rule above |
| `itemId` | Skip search and add this exact store item |

## Security: keep your API key on a server

Anything bundled in an app can be extracted. If you ship this package in a public app,
do not embed a real CartBridge key. Point `baseUrl` at your own backend, which holds the
key and forwards the request, and pass the signed-in user's token as `apiKey`.

## Known limitations

- Walmart may show bot checks inside WebViews. Pass `userAgent` to `CartWebViewPage` if
  needed; **Open in app** is the fallback.
- Whether **Open in app** lands in the Walmart app or the browser depends on the
  device's link handling.

## Contributing and support

Issues and pull requests are welcome in the
[GitHub repository](https://github.com/Flexxxlab/cartbridge/issues).

## License

MIT. See [LICENSE](LICENSE).

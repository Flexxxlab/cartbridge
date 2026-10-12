# cart_bridge

Turn a list of ingredients into a filled grocery cart, **without running a backend or
putting a store's private key in your app**.

Walmart's Affiliate API requires every request to be signed with an RSA private key. That
key can't live safely inside a mobile app, so developers normally have to build and host a
server just to hold it. CartBridge does that part for you: you save your Walmart
credentials once in the CartBridge dashboard (stored encrypted, never shown again), and your
app calls this package with a CartBridge API key. CartBridge signs the Walmart requests on
your behalf and returns a cart link that you open in an in-app WebView or the store's app.

Walmart is supported today. **More stores are planned.** Need a specific one? See
[Stores and support](#stores-and-support).

## Get started

1. **Sign up** at [cartbridge.flexxxlab.com](https://cartbridge.flexxxlab.com/signup) and verify your email.
2. Open your [dashboard](https://cartbridge.flexxxlab.com/dashboard) and add your **Walmart
   Affiliate API credentials** (get them at [walmart.io](https://walmart.io)). They are verified
   against Walmart, stored encrypted and never shown again.
3. Create a **CartBridge API key** on the same page, and use it in your app.

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

- A free CartBridge account and API key from the [dashboard](https://cartbridge.flexxxlab.com/dashboard),
  plus your own Walmart Affiliate API credentials saved there (see [Get started](#get-started)).
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
  apiKey: 'YOUR_KEY', // from https://cartbridge.flexxxlab.com/dashboard
  baseUrl: 'https://cartbridge.flexxxlab.com',
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
final client = CartBridgeClient(
  apiKey: 'YOUR_KEY',
  baseUrl: 'https://cartbridge.flexxxlab.com',
);
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

## Security

**Your Walmart private key never touches your app.** It lives only on the CartBridge server,
encrypted at rest, and is used to sign requests there.

What your app does hold is a CartBridge API key. Treat it as a credential, but know its
limits: it can only build carts, it is rate limited per account, and you can revoke it in
the dashboard at any time. A leaked Walmart private key offers none of those protections.
For apps with many anonymous users, you can instead point `baseUrl` at your own thin
backend that holds the CartBridge key, and pass the signed-in user's token as `apiKey`.

## Known limitations

- Walmart may show bot checks inside WebViews. Pass `userAgent` to `CartWebViewPage` if
  needed; **Open in app** is the fallback.
- Whether **Open in app** lands in the Walmart app or the browser depends on the
  device's link handling.

## Stores and support

Walmart is supported today and we plan to add more stores. If your app needs a store that
isn't supported yet, tell us which one and we'll prioritize it:

- Email: [helpdesk@flexxxlab.com](mailto:helpdesk@flexxxlab.com)
- Bugs and feature requests: [GitHub issues](https://github.com/Flexxxlab/cartbridge/issues)

Pull requests are welcome.

## License

MIT. See [LICENSE](LICENSE).

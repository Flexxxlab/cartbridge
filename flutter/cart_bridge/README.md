# cart_bridge

[![pub package](https://img.shields.io/pub/v/cart_bridge.svg)](https://pub.dev/packages/cart_bridge)
[![pub points](https://img.shields.io/pub/points/cart_bridge)](https://pub.dev/packages/cart_bridge/score)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Add "Send to Walmart cart" to your Flutter app in a few lines, with no backend to build.**

Give `cart_bridge` a list of ingredients. It finds matching products, fills a Walmart cart, and
opens it in your app so the user can check out.

```dart
await CartBridge(apiKey: 'YOUR_API_KEY').openCart(context, items: const [
  Ingredient('chicken breast', quantity: 2, unit: 'lb'),
  Ingredient('large eggs', quantity: 12, unit: 'each'),
  Ingredient('olive oil'),
]);
```

## Why cart_bridge

- **No server to build.** Walmart's API needs every request signed with a private key, which
  can't be stored safely in a mobile app. Normally that means building and hosting a backend.
  CartBridge does it for you.
- **Your Walmart key stays off the device.** You add it once in the CartBridge dashboard, where
  it is stored encrypted and never shown again. Your app only holds a CartBridge key, which can
  only build carts, is rate limited, and can be revoked at any time.
- **A complete cart flow.** Product matching, sensible quantities, a ready-made cart screen, and
  a hand-off to the Walmart app.
- **More stores are coming.** Walmart today; [tell us](#support) which store you need next.

## Setup

### 1. Create your free account

Sign up at **[cartbridge.flexxxlab.com](https://cartbridge.flexxxlab.com/signup)** and confirm
your email address.

### 2. Connect your Walmart account

CartBridge uses your own Walmart Affiliate API credentials:

1. Register at [walmart.io](https://walmart.io) and request access to the Affiliate API.
2. Create an RSA key pair:

   ```sh
   openssl genrsa -out walmart_private_key.pem 2048
   openssl rsa -in walmart_private_key.pem -pubout -out walmart_public_key.pem
   ```

3. Upload `walmart_public_key.pem` on walmart.io, and note your **Consumer ID** and
   **key version**.
4. In your [CartBridge dashboard](https://cartbridge.flexxxlab.com/dashboard), paste the Consumer
   ID, key version and the contents of `walmart_private_key.pem`. CartBridge checks them with
   Walmart before saving.

Keep `walmart_private_key.pem` out of your app and out of source control.

### 3. Create an API key

On the same [dashboard](https://cartbridge.flexxxlab.com/dashboard), create an API key and copy it.
It is shown only once. The dashboard also shows your rate limits and current usage.

### 4. Add the package

```sh
flutter pub add cart_bridge
```

**Android:** in `android/app/src/main/AndroidManifest.xml`, allow internet access and let the
**Open in app** button launch links:

```xml
<manifest ...>
  <uses-permission android:name="android.permission.INTERNET"/>
  <queries>
    <intent>
      <action android:name="android.intent.action.VIEW"/>
      <data android:scheme="https"/>
    </intent>
  </queries>
  ...
</manifest>
```

**iOS and macOS:** no extra setup.

## Usage

### Open a cart

```dart
import 'package:cart_bridge/cart_bridge.dart';

final bridge = CartBridge(apiKey: 'YOUR_API_KEY');

Future<void> addToWalmart(BuildContext context) async {
  final result = await bridge.openCart(context, items: const [
    Ingredient('chicken breast', quantity: 2, unit: 'lb'),
    Ingredient('large eggs', quantity: 12, unit: 'each'),
    Ingredient('basmati rice'),
  ]);

  if (!result.hasItems) {
    // Nothing matched, so no cart screen was opened.
  }
}
```

`openCart` shows a full-screen Walmart cart. From there, your user can:

- sign in and check out right in the app, or
- tap **Open in app** to continue in the Walmart app or browser.

Any ingredients that couldn't be matched are listed in a banner on the cart screen.

### Handle errors

```dart
try {
  await bridge.openCart(context, items: items);
} on CartBridgeException catch (e) {
  if (e.isMissingStoreCredentials) {
    // Add your Walmart credentials in the CartBridge dashboard.
  } else if (e.isRateLimited) {
    // Too many requests. e.message says how long to wait.
  } else if (e.isUnauthorized) {
    // The API key is wrong or was revoked.
  } else {
    // Network problem or timeout. e.message has details.
  }
}
```

### Control quantities

| You pass | What gets added |
| --- | --- |
| `Ingredient('eggs', quantity: 12, unit: 'each')` | 12 items (count units: `each`, `can`, `bag`, or none) |
| `Ingredient('chicken', quantity: 2, unit: 'lb')` | 1 package, with a note (weight and volume units) |
| `Ingredient('eggs', cartQuantity: 1)` | Exactly 1, whatever the quantity says |
| `Ingredient('bread', itemId: '10315355')` | That exact Walmart item, skipping search |

The same product requested twice is merged into one line.

### Build your own screen

Use `CartBridgeClient` when you want your own review screen before opening the cart:

```dart
final client = CartBridgeClient(apiKey: 'YOUR_API_KEY');
final result = await client.createCart(items: items);

for (final line in result.lines) {
  print('${line.cartQuantity} × ${line.product.name}  ${line.product.price ?? ''}');
}
print('Estimated total: ${result.estimatedTotal}');

if (result.cartUrl != null) {
  Navigator.of(context).push(MaterialPageRoute(
    builder: (_) => CartWebViewPage(
      cartUrl: result.cartUrl!,
      unmatched: result.unmatched,
    ),
  ));
}
```

## Rate limits

You choose your own limits. On your [dashboard](https://cartbridge.flexxxlab.com/dashboard),
set rules such as *10 requests per minute* or *1,000 per day* to protect your Walmart quota from
a runaway app, and watch live usage. Limits apply across all of your API keys.

New accounts start at **20 requests per 5 minutes and 500 per day**, and you can raise them up
to **100 per 5 minutes and 5,000 per day**. When a limit is reached,
`CartBridgeException.isRateLimited` is `true` and the message says how long to wait. Need more?
[Contact us](#support).

## Keeping your API key safe

Anything shipped inside an app can be extracted, so treat the CartBridge API key like any other
credential. If it leaks, revoke it in the dashboard and create a new one; your Walmart key is
not affected. For large public apps, you can route requests through your own backend instead:
pass `baseUrl` pointing at your server and keep the CartBridge key there.

## Platform support

| Android | iOS | macOS | Web | Windows | Linux |
| :-: | :-: | :-: | :-: | :-: | :-: |
| ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |

The cart screen uses [`webview_flutter`](https://pub.dev/packages/webview_flutter), which
supports Android, iOS and macOS.

## FAQ

**Do I need my own server?**
No. CartBridge hosts the part that holds your Walmart key and talks to Walmart.

**Where is my Walmart private key stored?**
Only on CartBridge's server, encrypted. It is never sent to your app and can't be viewed again
after you save it. You can remove it from the dashboard at any time.

**Which stores are supported?**
Walmart (US) today. More are planned, so [let us know](#support) which store your app needs.

**What if Walmart shows a bot check in the cart screen?**
Users can tap **Open in app** to continue in the Walmart app or browser. You can also pass a
custom `userAgent` to `CartWebViewPage`.

## Support

- Email: [helpdesk@flexxxlab.com](mailto:helpdesk@flexxxlab.com), including requests for new stores
- Bugs and feature requests: [GitHub issues](https://github.com/Flexxxlab/cartbridge/issues)
- Account and API keys: [cartbridge.flexxxlab.com](https://cartbridge.flexxxlab.com/dashboard)

## License

MIT. See [LICENSE](LICENSE). Made by [Flexxxlab](https://us.flexxxlab.com/).

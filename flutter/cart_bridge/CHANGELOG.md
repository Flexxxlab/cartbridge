## 0.1.0

- First release.
- `CartBridge.openCart`: build a Walmart cart from ingredients and open it in a WebView.
- `CartBridgeClient` for custom UIs; defaults to the hosted service at cartbridge.flexxxlab.com.
- `CartWebViewPage` with an **Open in app** hand-off and a banner for unmatched ingredients.
- `CartBridgeException` helpers: `isUnauthorized`, `isMissingStoreCredentials`, `isRateLimited`.

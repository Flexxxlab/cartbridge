# CartBridge

Send a list of ingredients, get back a store cart link. Walmart first.

## Use it

```bash
curl -X POST https://your-server/v1/cart \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d '{"store":"walmart","items":[{"name":"chicken breast","quantity":2,"unit":"lb"},{"name":"eggs"}]}'
```

You get a `cart_url`. Open it and the items are in the Walmart cart.

In Flutter:

```dart
final bridge = CartBridge(apiKey: 'cb_...', baseUrl: 'https://your-server');
await bridge.openCart(context, items: [Ingredient('chicken breast', quantity: 2, unit: 'lb')]);
```

Don't put a real API key in a published app. Call CartBridge from your own server instead.

## Run it

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env     # leave WALMART_PROVIDER=mock to try it without Walmart keys
uvicorn app.main:app --reload
```

Open http://localhost:8000, sign up, create an API key. Tests: `cd tests && pytest -q`.
Enable the secret-scan hook: `git config core.hooksPath .githooks`.

## Walmart keys

Set `WALMART_PROVIDER=affiliate`, `WALMART_CONSUMER_ID`, `WALMART_KEY_VERSION` and
`WALMART_PRIVATE_KEY_PATH` in `.env`. Never commit `.env` or `.pem` files.

## Limits

2 cart requests per 5 minutes and 6 per day per account (change in `.env`).

## Layout

- `backend/`: FastAPI server and signup site
- `flutter/cart_bridge/`: Flutter package
- `deploy/`: Docker + Caddy files for production

## License

MIT. See `LICENSE`.

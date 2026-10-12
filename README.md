# CartBridge

Turn a list of ingredients into a filled grocery cart, **without running your own backend or
putting a store's private key in your app**.

Walmart's Affiliate API requires every request to be signed with an RSA private key, which
can't be stored safely in a mobile app. CartBridge holds that key (encrypted) on the server,
signs the requests for you, and returns a cart link. Walmart is supported today, and more
stores are planned (see [Stores and support](#stores-and-support)).

- **Server:** FastAPI app with a sign-up site, API keys and a `/v1/cart` endpoint.
- **Flutter package:** [`cart_bridge`](flutter/cart_bridge) opens the cart in a WebView or the store's app.

## Get started

1. **Sign up** at [cartbridge.flexxxlab.com](https://cartbridge.flexxxlab.com/signup) and verify your email.
2. Open your [dashboard](https://cartbridge.flexxxlab.com/dashboard) and add your **Walmart
   Affiliate API credentials** (get them at [walmart.io](https://walmart.io)). They are verified
   against Walmart, stored encrypted and never shown again.
3. Create a **CartBridge API key** on the same page, and use it in your app.

## How it works

1. Your app sends `POST /v1/cart` with ingredients and an API key.
2. The server searches the store, picks the first in-stock match for each ingredient, works
   out a sensible quantity, and returns a cart link such as
   `https://affil.walmart.com/cart/addToCart?items=ITEMID|QTY,ITEMID|QTY`.
3. Opening the link (in a WebView, the browser or the Walmart app) fills the cart. The user
   signs in and checks out on the store's own site.

## Try it

With your API key from the [dashboard](https://cartbridge.flexxxlab.com/dashboard):

```sh
curl -X POST https://cartbridge.flexxxlab.com/v1/cart \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"store":"walmart","items":[
        {"name":"chicken breast","quantity":2,"unit":"lb"},
        {"name":"large eggs","quantity":12,"unit":"each"}]}'
```

The response contains a `cart_url`. Open it and the items are in the Walmart cart. Interactive
API docs are at [/docs](https://cartbridge.flexxxlab.com/docs).

## Rate limits

Every account has limits on cart requests, applied across all of its API keys:

| Account type | Default limits |
| --- | --- |
| Your own Walmart credentials | 20 per 5 minutes, 500 per day |
| Operator-granted access to CartBridge's Walmart credentials | Custom, set per account |

Your dashboard shows your limits and live usage. When a limit is hit the API returns `429`
with a `Retry-After` header saying how many seconds to wait. Only `/v1/cart` is limited.

## API

Authenticate with `Authorization: Bearer cb_...` or `X-API-Key: cb_...`.

| Endpoint | Description |
| --- | --- |
| `POST /v1/cart` | Build a cart from ingredients |
| `GET /v1/me` | Account info, including which Walmart credentials the account uses |
| `GET /v1/stores` | Supported stores |

**Request** to `/v1/cart`:

```json
{
  "store": "walmart",
  "items": [
    { "name": "chicken breast", "quantity": 2, "unit": "lb" },
    { "name": "paper towels", "item_id": "123456", "cart_quantity": 3 }
  ]
}
```

**Response:** `cart_url`, `lines` (matched products and quantities), `unmatched`
(ingredients that could not be added, with reasons) and `estimated_total`.

**Quantity rules**

- Count-like units (`each`, `can`, `bag`, none) add `ceil(quantity)` items.
- Weight and volume units (`lb`, `oz`, `cup`, `g`) add one package, with a `note`.
- `cart_quantity` sets an exact count; `item_id` skips the search.
- The same product requested twice is merged (quantities summed, maximum 99).

**Errors:** `401` invalid key, `403` no Walmart credentials on the account, `429` rate limit
exceeded (see the `Retry-After` header), `400` invalid request.

## Walmart credentials

CartBridge calls the Walmart Affiliate API, and every request is signed with an RSA private
key. There are two ways an account gets credentials:

- **Bring your own.** Each developer enters their own consumer ID, key version and private
  key in the dashboard. They are verified against Walmart before saving, stored encrypted,
  and never shown again.
- **Operator-granted.** The server operator can let specific accounts use the server's own
  credentials: `python -m app.admin grant <username>`. See `python -m app.admin --help`.

Accounts without either get a `403`. To get credentials, register at
[walmart.io](https://walmart.io) and upload your public key.

Check Walmart's current API terms before offering this service to others.

## Configuration

Set these in `backend/.env` (see `.env.example`).

| Variable | Purpose |
| --- | --- |
| `BASE_URL` | Public URL of the server (`https://...` enables secure cookies) |
| `SECRET_KEY` | Signs session cookies. **Required in production.** |
| `ADMIN_USERNAMES` | Comma-separated usernames allowed to open `/admin` (edit limits, grant platform access) |
| `ENCRYPTION_KEY` | Encrypts stored Walmart credentials. Keep it safe: they cannot be decrypted without it. |
| `DATABASE_URL` | SQLAlchemy URL (default: SQLite file) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Email for verification links. Empty `SMTP_HOST` prints emails to the console. |
| `WALMART_PROVIDER` | `mock` (fake products) or `affiliate` |
| `WALMART_CONSUMER_ID`, `WALMART_KEY_VERSION`, `WALMART_PRIVATE_KEY_PATH` | The server's own Walmart credentials, for operator-granted accounts |
| `CART_LIMIT_PER_WINDOW`, `CART_WINDOW_SECONDS`, `CART_LIMIT_PER_DAY` | Default limits for operator-granted accounts |
| `OWN_KEY_LIMIT_PER_WINDOW`, `OWN_KEY_LIMIT_PER_DAY` | Default limits for accounts using their own credentials |

Never commit `.env` or `.pem` files. `.gitignore` and a pre-commit hook guard against it;
enable the hook with `git config core.hooksPath .githooks`.

## Managing limits (operators)

Usernames in `ADMIN_USERNAMES` get an **Admin** page at `/admin` to grant or revoke platform
access and edit an account's limits. Tiers are `window-seconds:max-requests` pairs, for example
5 per 2 minutes, 10 per hour and 20 per day:

```
120:5,3600:10,86400:20
```

The same is available from the command line:

```sh
python -m app.admin grant <username> --limit 120:5 --limit 3600:10 --limit 86400:20
```

## Self-hosting

The server is open source. `deploy/` contains a Docker Compose file and a Caddy config that serves the app over HTTPS
with automatic certificates. Edit the hostname in `deploy/Caddyfile`, create `.env` and the
Walmart key file on the server (see `deploy/docker-compose.prod.yml`), then:

```sh
DEPLOY_HOST=my-server deploy/deploy.sh
```

Production checklist: strong `SECRET_KEY` and `ENCRYPTION_KEY`, a real SMTP provider, HTTPS,
regular backups of the database volume, and Postgres if you expect real traffic.

## Not yet included

Password reset, Alembic migrations, per-IP limits on sign-up and login, and stores other
than Walmart. Adding a store means implementing `StoreProvider` in `backend/app/stores/`.

## Project layout

```
backend/              FastAPI server, templates, tests
flutter/cart_bridge/  Flutter package (published as `cart_bridge`)
deploy/               Docker Compose + Caddy deployment files
scripts/, .githooks/  Secret-scanning pre-commit hook
```

## Stores and support

Walmart is supported today. If you need another store, email [helpdesk@flexxxlab.com](mailto:helpdesk@flexxxlab.com)
and tell us which one. Bugs and feature requests go to
[GitHub issues](https://github.com/Flexxxlab/cartbridge/issues).

## Security

Please report vulnerabilities privately. See [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).

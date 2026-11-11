# CartBridge — project context

Ingredient list + store → filled store cart. Walmart is the first store.

- `backend/` — FastAPI. Jinja2 site (sign up with username/email/password → email verification → create/revoke API keys), and `/v1/cart`, `/v1/me`, `/v1/stores` authenticated with `Authorization: Bearer cb_...` or `X-API-Key`. SQLite via SQLAlchemy 2.0, transactional email via Resend HTTP API (`RESEND_API_KEY`; else SMTP; else logs only), scrypt password hashes, only SHA-256 hashes of API keys stored, CSRF tokens on all forms.
- `backend/app/stores/walmart.py` — `WalmartAffiliateProvider` (walmart.io Affiliate API v2 `/search`, RSA-SHA256 signed headers) and `WalmartMockProvider`. Cart link: `https://affil.walmart.com/cart/addToCart?items=ID|QTY,...`.
- `backend/app/cart.py` — picks first in-stock match per ingredient; count units → ceil(qty), weight/volume → 1 package with a note; merges duplicate products; `item_id` / `cart_quantity` overrides.
- `flutter/cart_bridge/` — Flutter library: `CartBridgeClient`, `CartBridge.openCart(context, items: ...)`, `CartWebViewPage` (webview_flutter; "Open in app" launches the cart link externally via url_launcher; refresh loads the plain cart page so items aren't re-added). Example app in `example/` (run `flutter create .` there first).

## Status (2026-10-23)
- Tests run: `cd backend/tests && pytest -q` -> 40 passed (venv from `requirements-dev.txt`).
- Local commits on main, NOT pushed and NOT deployed (repo is public; deploys are owner-run, runbooks in `~/HQ/plans/runbooks/2026-10-23-cartbridge-*.md`).
- Self-serve (plan `~/HQ/plans/2026-10-23-self-serve-duck-cartbridge.md`): `users.plan` (default `free`) + plan table in `app/plans.py`
  (Free: 10 req/5 min + 200/calendar month, bring your own Walmart key; Pro: operator-assigned). Monthly counter table `usage_monthly`.
  Operator-granted `PlatformAccess` accounts (PressPot) keep their own grants and have no monthly cap.
- Per-IP throttle on signup/login/resend (`app/throttle.py`, table `auth_attempts`, SEC-021). Needs uvicorn `--forwarded-allow-ips "*"` behind Caddy (in Dockerfile).
- Email (2026-11-01, committed locally, NOT deployed; Reviewer pending): `app/emailer.py` (Resend), `app/auth_email.py` (tokens + templates), verify 24 h / reset 1 h single-use hashed tokens, `/forgot` + `/reset`, `users.session_version` logs out sessions on reset, `python -m app.send_verifications [--send]` (default dry run). Runbook `~/HQ/plans/runbooks/2026-11-01-cartbridge-resend-env.md`. Tests 66; /verify is GET confirm page + POST; reset revokes API keys; reset links are not voided by new requests. Without a key the old behaviour remains:
- No key configured: tokens are logged; the notice "Verification emails can take longer than usual. For immediate access, email helpdesk@flexxxlab.com." is shown. Owner verifies by hand: `/admin` Verify button or `python -m app.admin verify <user|email>`.
- Shared strings/page template for Duck: `docs/self-serve-ux.md` (source in `app/ux.py`). Public pages + SEO files in `app/pages.py`, `app/seo.py`, templates.
- Migrations: no Alembic; `python -m app.migrate` (idempotent, also run at startup). Back up first: `deploy/backup-sqlite.sh`, `deploy/restore-test.sh`.
- Admin CLI: `users`, `keys`, `verify`, `plan`, `move-key`, `delete-user --yes` (SQLite doesn't enforce cascades; delete-user removes children by hand).
- Lighthouse (local): SEO 100 on /, /features, /getting-started, /faq; accessibility 91-92.
- Still open: SMTP, Stripe, prod runbooks not yet run, smoke users + PressPot move, off-server backup copy, legal review of terms/privacy text.

## Next steps
1. `cd backend && pip install -r requirements-dev.txt && cd tests && pytest -q`
2. Fill `backend/.env` from `.env.example`: `WALMART_PROVIDER=affiliate`, `WALMART_CONSUMER_ID`, `WALMART_KEY_VERSION`, `WALMART_PRIVATE_KEY_PATH`. Never commit `*.pem` or `.env`.
3. Verify keys against `https://developer.api.walmart.com/api-proxy/service/affil/product/v2/taxonomy`.
4. Run `uvicorn app.main:app --reload`, sign up, create an API key, call `/v1/cart`, open `cart_url` in a browser to confirm items land in the cart.
5. Tune product matching against real search results (field names, availability, picking the best match).
6. `cd flutter/cart_bridge && flutter pub get && flutter analyze && flutter test`, then run the example on a device.

## Open questions / risks
- Walmart affiliate terms may restrict redistributing API data to third-party developers (the API-key resale model). Check before launch.
- WebView bot checks on walmart.com; whether "Open in app" opens the Walmart app or the browser.
- Not built: payments, Alembic migrations.

## From HQ index (2026-10-19)

- Path: `/Users/mohamedirshad/Developer/cartbridge` · Aliases: cart bridge, cart_bridge, walmart cart
- What: ingredient list + store -> filled cart link (Walmart first). FastAPI/SQLAlchemy/SQLite backend + Flutter pkg `flutter/cart_bridge` (pub.dev).
- Run: `uvicorn app.main:app --reload` (in backend/). Test: `cd backend && pytest`. Pre-commit secret hook in `.githooks`.
- Git: Flexxxlab/cartbridge, `main`. Live at cartbridge.flexxxlab.com (per developer-context.md; deploy: `~/HQ/bin/publish cartbridge`, wraps `~/HQ/bin/deploy/cartbridge.sh`). Status: very active.
- Landing promo video (2026-11-09, local branch feat/promo-videos): `backend/app/static/` (mounted at `/static`: `promo-video.{js,css}`, `cartbridge_promo.mp4` + poster, copy of `~/Developer/portfolio/media/videos/cartbridge/out/`), markup in `templates/home.html` via the new `{% block head %}` in `base.html`. Ships in the Docker image (`COPY app`); no deploy change.

## Tool-specific config (don't edit unless asked)
Shared instructions live in this file. Shared playbooks live in `~/HQ/playbooks/`.

| Tool | Location | Contains |
|---|---|---|
| Claude Code | `~/HQ/.claude/` | skill wrappers |
| Antigravity CLI | `~/HQ/.agents/` | skill wrappers |

- Never modify another tool's config to make your own task work; tell the owner instead.
- When changing a shared playbook, check the wrappers that reference it.

## Shared memory
Persistent notes live in `docs/agent/memory.md`. Read it at session start. When the owner says "remember X", append a dated bullet there, not to tool-private memory.


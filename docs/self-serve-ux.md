# Self-serve UX: shared strings and page template (CartBridge, copied by Duck)

Source of truth in code: `backend/app/ux.py` (strings), `backend/app/plans.py` (plan table),
`backend/app/templates/base.html` (layout, header, footer). Copy the strings verbatim; swap only the product name.

## Fixed strings (verbatim)

| Where | Text |
| --- | --- |
| After signup ("Check your email" screen, title) | `Check your email` |
| After signup (body) | `We created your account for <email> and sent a verification link.` |
| Notice (only while no email provider is configured), after signup, on unverified login, after resend, FAQ, contact | `Verification emails can take longer than usual. For immediate access, email helpdesk@flexxxlab.com.` |
| Unverified dashboard heading | `Verify your email` (with a "Resend verification email" button) |
| Forgot password (login page), only while no email provider is configured | `Forgot your password? Email helpdesk@flexxxlab.com` (with a Resend key: a "Forgot your password?" link to `/forgot`) |
| Paid call to action (button, mailto:helpdesk@flexxxlab.com) | `Need more? Contact us to buy` |
| Signup terms line | `By signing up you agree to the Terms and the Privacy Policy.` (links to /terms and /privacy) |
| Resend page | `A new verification link was sent to <email>.` plus the notice |

Email is not sent yet (no SMTP). Tokens are logged by the server; the operator verifies the account by hand
(CartBridge `/admin` -> Verify, or `python -m app.admin verify <username|email>`).

## Over-limit message (one shape, API and UI)

```
Rate limit exceeded (<limit>) on the <Plan> plan. Try again in <duration>. Need more? Contact us to buy: mailto:helpdesk@flexxxlab.com
```

- `<limit>` examples: `10 requests per 5 minutes`, `200 requests per calendar month`.
- `<Plan>`: `Free`, `Pro`, or `Platform` (operator-granted accounts).
- `<duration>`: `45 seconds`, `4 minutes`, `1 day 3 hours` (two largest units).
- API: HTTP 429, JSON `{"detail": "<message>"}`, header `Retry-After: <seconds>`.
- UI: the same message in a notice under the usage table. Per-IP throttle (signup/login/resend), HTTP 429 page:
  `Too many <sign-up attempts|login attempts|verification requests> from your network. Try again in <duration>. Need help? Email helpdesk@flexxxlab.com.`

## Plans

| Plan | Limits |
| --- | --- |
| Free | bring your own Walmart key; 10 requests per 5 minutes; 200 requests per calendar month (UTC) |
| Pro | assigned by the operator after "Contact us to buy"; no prices shown anywhere |

Users have a `plan` field (default `free`); limits come from the plan table. Duck's equivalent limits are apps per
user and pages per app (Free: 1 app with 1 page).

## Screens, in order

1. Sign up: username (CartBridge), email, password, confirm, terms/privacy line.
2. Check your email: confirmation line + the notice.
3. Log in before verification: dashboard shows "Verify your email", the notice and "Resend verification email".
4. Verified dashboard: plan card ("Your plan: Free", limits, "Need more? Contact us to buy" button), API keys / apps,
   usage vs limits table with next-reset time, quick start.
5. Over limit: the shared message.

## Page template notes (public pages)

- One layout (`base.html`): header (Features, Docs, Pricing, Log in / Sign up free), content in cards, one footer.
- Footer on every page, in this order: `Need more? Contact us to buy: helpdesk@flexxxlab.com` line; links
  Docs, API reference, Features, Pricing, FAQ, Terms, Privacy, Contact; GitHub, Security, license; copyright.
- Public pages: `/` (landing), `/features`, `/getting-started`, `/faq`, `/pricing`, `/contact`, `/terms`, `/privacy`, `/signup`.
- CTAs: primary `Get started` (Duck: `Try the demo`), secondary `Contact`.
- Every indexable page has: unique `<title>` and meta description, `<html lang="en">`, canonical (`BASE_URL` + path),
  Open Graph + Twitter tags, JSON-LD `@graph` with `SoftwareApplication` (free Offer) + `Organization`.
  Pages behind login or one-off messages carry `<meta name="robots" content="noindex">`.
- Files: `/robots.txt` (Allow /, Disallow dashboard/admin/keys/verify/login/v1, Sitemap line), `/sitemap.xml`
  (all public pages), `/llms.txt` (summary, REST + SDK quickstart, plans, link list), `/favicon.svg`.
- Search targets (CartBridge): "Walmart cart API", "Flutter Walmart add to cart", "grocery cart link API". Put them in
  titles, H1/H2 and the first paragraph, as real text.
- Terms/Privacy are plain-language drafts dated 23 October 2026; have them reviewed before relying on them.

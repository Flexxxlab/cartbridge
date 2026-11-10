"""Search/AI-discovery bits: JSON-LD, robots.txt, sitemap.xml, llms.txt."""
import html as _html
import json
import re

from .config import get_settings
from .plans import PLANS

DEFAULT_DESCRIPTION = ("CartBridge is a Walmart cart API: send a list of ingredients, get back a Walmart "
                       "add-to-cart link. Flutter package and REST API, free plan, no backend to build.")

# (path, changefreq, priority) for every indexable page.
SITEMAP = [
    ("/", "weekly", "1.0"), ("/features", "monthly", "0.8"), ("/getting-started", "monthly", "0.9"),
    ("/faq", "monthly", "0.7"), ("/pricing", "monthly", "0.8"), ("/signup", "monthly", "0.6"),
    ("/video", "monthly", "0.6"), ("/contact", "yearly", "0.4"), ("/terms", "yearly", "0.3"), ("/privacy", "yearly", "0.3"),
]


YOUTUBE_CHANNEL_URL = "https://www.youtube.com/@FlexxxlabApps"
VIDEO_YOUTUBE_ID = "3vBvvGveLAo"
VIDEO_TITLE = "CartBridge quick peek: ingredients in, a filled Walmart cart out"
VIDEO_DESCRIPTION = ("A 33-second look at CartBridge, the Walmart cart API. Send a list of ingredients from Flutter or one REST "
                     "call and get back a Walmart add-to-cart link, with your private Walmart key kept out of the app. "
                     "See it filling the cart inside PressPot.")


def video_jsonld() -> str:
    """VideoObject for the promo video (duration measured with ffprobe: 33.13 s), safe inside a <script> tag."""
    site = get_settings().base_url.rstrip("/")
    video = {"@context": "https://schema.org", "@type": "VideoObject", "name": VIDEO_TITLE,
             "description": VIDEO_DESCRIPTION, "thumbnailUrl": [f"{site}/static/cartbridge_promo_poster.jpg"],
             "uploadDate": "2026-11-10T00:39:13-05:00", "duration": "PT33S",
             "contentUrl": f"{site}/static/cartbridge_promo.mp4",
             "embedUrl": f"https://www.youtube.com/embed/{VIDEO_YOUTUBE_ID}", "url": f"{site}/video", "inLanguage": "en"}
    return json.dumps(video, ensure_ascii=False).replace("<", "\\u003c")


def jsonld() -> str:
    """SoftwareApplication + Organization, safe to embed in a <script> tag."""
    s = get_settings()
    site = s.base_url.rstrip("/")
    org = {"@type": "Organization", "@id": f"{s.company_url}#org", "name": s.company_name, "url": s.company_url,
           "email": s.support_email, "logo": "https://flexxxlab.com/icon-512.png",
           "sameAs": [s.source_url, YOUTUBE_CHANNEL_URL]}
    app = {"@type": "SoftwareApplication", "@id": f"{site}/#app", "name": s.app_name, "url": f"{site}/",
           "applicationCategory": "DeveloperApplication", "operatingSystem": "Web, Android, iOS",
           "description": DEFAULT_DESCRIPTION, "license": "https://opensource.org/licenses/MIT",
           "publisher": {"@id": org["@id"]},
           "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD", "name": "Free plan",
                      "description": f"Bring your own Walmart key. {describe_free()}"}}
    return json.dumps({"@context": "https://schema.org", "@graph": [app, org]}, ensure_ascii=False).replace("<", "\\u003c")


def describe_free() -> str:
    from .ratelimit import describe_plan
    return describe_plan(PLANS["free"])


def robots_txt() -> str:
    site = get_settings().base_url.rstrip("/")
    return ("User-agent: *\nAllow: /\nDisallow: /dashboard\nDisallow: /admin\nDisallow: /keys\n"
            "Disallow: /verify\nDisallow: /login\nDisallow: /v1/\n\n"
            f"Sitemap: {site}/sitemap.xml\n")


def sitemap_xml() -> str:
    site = get_settings().base_url.rstrip("/")
    urls = "".join(f"<url><loc>{site}{p if p != '/' else '/'}</loc><changefreq>{f}</changefreq>"
                   f"<priority>{pr}</priority></url>" for p, f, pr in SITEMAP)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n'


def llms_txt() -> str:
    s = get_settings()
    site = s.base_url.rstrip("/")
    return f"""# {s.app_name}

> {s.app_name} is a Walmart cart API. Send a list of ingredients (name, quantity, unit) and get back matched
> Walmart products plus a Walmart add-to-cart link. Use it from a Flutter app (the `cart_bridge` package on
> pub.dev) or any backend over REST. You bring your own Walmart Affiliate API key; it is stored encrypted and
> never shown again, so no Walmart private key ships inside your app.

## Quickstart (REST)

1. Sign up: {site}/signup (email verification, then log in).
2. Dashboard: add your Walmart Affiliate credentials (walmart.io) and create a {s.app_name} API key (`cb_...`).
3. Call the API:

```
curl -X POST {site}/v1/cart \\
  -H "Authorization: Bearer cb_YOUR_KEY" -H "Content-Type: application/json" \\
  -d '{{"store":"walmart","items":[{{"name":"chicken breast","quantity":2,"unit":"lb"}},{{"name":"large eggs","quantity":12,"unit":"each"}}]}}'
```

The response has `cart_url` (open it in a WebView, browser or the Walmart app to fill the cart), `lines`,
`unmatched` and `estimated_total`.

## Quickstart (Flutter)

```
flutter pub add cart_bridge
```

```dart
await CartBridge(apiKey: 'YOUR_API_KEY').openCart(context, items: const [
  Ingredient('chicken breast', quantity: 2, unit: 'lb'),
  Ingredient('large eggs', quantity: 12, unit: 'each'),
]);
```

## Plans and limits

- Free: bring your own Walmart key, {describe_free()}
- Over a limit the API returns HTTP 429 with a Retry-After header and a message ending "Need more? Contact us to buy".
- More: contact {s.support_email}. No prices are listed.

## Links

- [Home]({site}/): overview
- [Features]({site}/features)
- [Getting started]({site}/getting-started): Flutter and REST setup
- [FAQ]({site}/faq)
- [Pricing]({site}/pricing)
- [API reference (OpenAPI)]({site}/docs)
- [Terms]({site}/terms) and [Privacy]({site}/privacy)
- [Flutter package](https://pub.dev/packages/cart_bridge)
- [Source](https://github.com/Flexxxlab/cartbridge)
- [Watch the 33-second video]({site}/video) and [on YouTube](https://www.youtube.com/watch?v=3vBvvGveLAo)
- [Flexxxlab YouTube channel](https://www.youtube.com/@FlexxxlabApps)
- Contact: {s.support_email}
"""


# ---------- breadcrumbs and FAQ ----------
CRUMB_NAMES = {"/features": "Features", "/getting-started": "Getting started", "/faq": "FAQ", "/pricing": "Pricing",
               "/video": "Video", "/contact": "Contact", "/terms": "Terms of Service", "/privacy": "Privacy Policy",
               "/signup": "Sign up"}


def breadcrumb_jsonld(path: str) -> str:
    """BreadcrumbList (Home > page) for an indexable inner page; empty string for the home page or unknown paths."""
    path = path.rstrip("/")
    if not path or path not in CRUMB_NAMES:
        return ""
    site = get_settings().base_url.rstrip("/")
    data = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": f"{site}/"},
        {"@type": "ListItem", "position": 2, "name": CRUMB_NAMES[path], "item": f"{site}{path}"}]}
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def faq_items(free_text: str, email_enabled: bool, contact_url: str, support_email: str) -> list[dict]:
    """Visible FAQ entries ('html' is rendered on the page, 'text' is the same words for FAQPage JSON-LD)."""
    verify = ("Check your spam folder, then log in and press \u201cResend verification email\u201d (3 per hour). Still nothing? "
              f'Email <a href="{contact_url}">{support_email}</a>.' if email_enabled else
              "Verification emails can take longer than usual. For immediate access, email "
              f'<a href="{contact_url}">{support_email}</a>.')
    rows = [
        ("faq-what", "What is a Walmart cart API?",
         "An API that takes a shopping list and returns a Walmart cart. CartBridge matches each ingredient to a Walmart product and "
         "returns an add-to-cart link, so your app can send a shopper to a filled cart."),
        ("faq-flutter", "How do I add Walmart add to cart to a Flutter app?",
         'Run <code>flutter pub add cart_bridge</code>, then call <code>CartBridge(apiKey: ...).openCart(context, items: ...)</code>. '
         'See <a href="/getting-started">Getting started</a>.'),
        ("faq-server", "Do I need my own server?",
         "No. CartBridge holds the part that signs requests with your Walmart key and talks to Walmart."),
        ("faq-account", "Do I need a Walmart account?",
         'Yes. You bring your own Walmart Affiliate API credentials from <a href="https://walmart.io" rel="noopener">walmart.io</a>. '
         "Walmart applies its own terms and quotas to them."),
        ("faq-link", "What is a grocery cart link?",
         "A URL such as <code>https://affil.walmart.com/cart/addToCart?items=ITEMID|QTY,...</code>. Opening it adds the items to the "
         "shopper's Walmart cart. They sign in and check out on Walmart."),
        ("faq-key", "Is my Walmart private key safe?",
         "It is stored encrypted, never shown again after you save it, and never sent to your app. Your app holds a CartBridge key that "
         "you can revoke at any time without touching your Walmart key."),
        ("faq-limits", "What are the limits?",
         f"Free plan: {free_text} Past a limit the API returns HTTP 429 with a <code>Retry-After</code> header. You can set stricter "
         "limits on your dashboard."),
        ("faq-cost", "How much does it cost?",
         f'The Free plan costs nothing. For more, <a href="{contact_url}">contact us to buy</a>. See <a href="/pricing">pricing</a>.'),
        ("faq-verify", "My verification email did not arrive.", verify),
        ("faq-password", "I forgot my password.", f'Email <a href="{contact_url}">{support_email}</a>.'),
        ("faq-stores", "Which stores are supported?",
         'Walmart today. <a href="/contact">Tell us</a> which store you need next.'),
    ]
    return [{"id": i, "q": q, "html": h, "text": " ".join(_html.unescape(re.sub(r"<[^>]+>", "", h)).split())} for i, q, h in rows]


def faq_jsonld(items: list[dict]) -> str:
    data = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": it["q"], "acceptedAnswer": {"@type": "Answer", "text": it["text"]}} for it in items]}
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")

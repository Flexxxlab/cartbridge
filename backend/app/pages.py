"""Public, indexable pages and the files crawlers and AI agents look for."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from . import seo
from .db import get_db
from .plans import PLANS
from .web import current_user, render

router = APIRouter(include_in_schema=False)

# path -> (template, <title>, meta description). Titles carry the search targets.
PAGES = {
    "/features": ("features.html", "Features: Walmart cart API with Flutter and REST | CartBridge",
                  "What CartBridge does: match ingredients to Walmart products, build the add-to-cart link, keep your "
                  "Walmart key off the device, and rate limit your app."),
    "/getting-started": ("getting_started.html", "Getting started: Flutter Walmart add to cart | CartBridge",
                         "Add Walmart add to cart to a Flutter app, or call the REST API, in four steps: sign up, add "
                         "your Walmart key, create an API key, send ingredients."),
    "/faq": ("faq.html", "FAQ: Walmart cart API and grocery cart links | CartBridge",
             "Answers about the CartBridge Walmart cart API: Walmart keys, limits, quantities, grocery cart links, "
             "security and pricing."),
    "/pricing": ("pricing.html", "Pricing: free Walmart cart API plan | CartBridge",
                 "CartBridge is free with your own Walmart key: 10 requests per 5 minutes and 200 per calendar month. "
                 "Need more? Contact us to buy."),
    "/contact": ("contact.html", "Contact CartBridge | helpdesk@flexxxlab.com",
                 "Contact CartBridge for help, account verification, another store, or a plan with higher limits."),
    "/terms": ("terms.html", "Terms of Service | CartBridge", "The terms for using the CartBridge website and API."),
    "/privacy": ("privacy.html", "Privacy Policy | CartBridge",
                 "What CartBridge collects, why, how long it is kept, and how to ask for deletion."),
}


def _make(path: str, template: str, title: str, description: str):
    def view(request: Request):
        ctx = {"free": PLANS["free"], "free_text": seo.describe_free()}
        return render(request, template, indexable=True, page_title=title, description=description, **ctx)
    view.__name__ = "page" + path.replace("/", "_").replace("-", "_")
    router.add_api_route(path, view, methods=["GET"])


for _path, (_t, _title, _desc) in PAGES.items():
    _make(_path, _t, _title, _desc)


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "home.html", indexable=True, free_text=seo.describe_free(),
                  page_title="Walmart cart API for Flutter and REST | CartBridge",
                  description="Walmart cart API: send ingredients, get a Walmart add-to-cart link. Flutter package "
                              "and REST API. Free plan with your own Walmart key, no backend to build.")


@router.get("/robots.txt")
def robots():
    return PlainTextResponse(seo.robots_txt())


@router.get("/sitemap.xml")
def sitemap():
    return Response(seo.sitemap_xml(), media_type="application/xml")


@router.get("/llms.txt")
def llms():
    return PlainTextResponse(seo.llms_txt(), media_type="text/plain; charset=utf-8")


@router.get("/favicon.svg")
def favicon():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" '
           'fill="#0b63ce"/><path d="M14 20h6l5 20h20l5-14H24" fill="none" stroke="#fff" stroke-width="4" '
           'stroke-linecap="round" stroke-linejoin="round"/><circle cx="29" cy="48" r="3" fill="#fff"/>'
           '<circle cx="43" cy="48" r="3" fill="#fff"/></svg>')
    return Response(svg, media_type="image/svg+xml")

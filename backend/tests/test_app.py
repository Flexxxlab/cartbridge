import base64
from urllib.parse import unquote

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.stores.walmart import sign_walmart_request
from conftest import csrf


def test_signup_verify_login_and_keys(client, make_user):
    make_user("carol")
    page = client.get("/dashboard").text
    assert "Create API key" in page
    client.post("/logout", data={"csrf": csrf(page)})
    assert client.get("/dashboard", follow_redirects=False).status_code == 303

    page = client.get("/login").text
    bad = client.post("/login", data={"username": "carol", "password": "nope", "csrf": csrf(page)})
    assert bad.status_code == 400
    ok = client.post("/login", data={"username": "CAROL", "password": "s3cret-pass", "csrf": csrf(page)})
    assert "API keys" in ok.text


def test_duplicate_username_rejected(client, make_user):
    make_user("dave")
    page = client.get("/signup").text
    r = client.post("/signup", data=dict(username="Dave", email="x@example.com", password="12345678",
                                         password2="12345678", csrf=csrf(page)))
    assert r.status_code == 400 and "taken" in r.text


def test_unverified_cannot_create_key(client, make_user):
    make_user("erin", verify=False)
    page = client.get("/dashboard").text
    assert "Resend verification" in page
    assert client.post("/keys", data={"name": "x", "csrf": csrf(page)}).status_code == 403


def test_csrf_required(client):
    client.get("/login")
    assert client.post("/login", data={"username": "a", "password": "b", "csrf": "wrong"}).status_code == 400


def test_api_requires_key(client):
    assert client.post("/v1/cart", json={"items": [{"name": "milk"}]}).status_code == 401
    assert client.get("/v1/me", headers={"X-API-Key": "cb_fake"}).status_code == 401


def test_cart(client, api_key):
    h = {"Authorization": f"Bearer {api_key}"}
    assert client.get("/v1/me", headers=h).json()["username"] == "bob"
    r = client.post("/v1/cart", headers=h, json={"store": "walmart", "items": [
        {"name": "chicken breast", "quantity": 2, "unit": "lb"},
        {"name": "large eggs", "quantity": 2.5, "unit": "each"},
        {"name": "Large Eggs", "quantity": 1},          # same product -> merged
        {"name": "zzz unobtainium"},                      # unmatched
        {"name": "custom", "item_id": "123456", "cart_quantity": 3},
    ]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["lines"]) == 4 and len(d["unmatched"]) == 1
    assert d["lines"][0]["cart_quantity"] == 1 and d["lines"][0]["note"]
    assert d["lines"][1]["cart_quantity"] == 3
    url = unquote(d["cart_url"])
    assert url.startswith("https://affil.walmart.com/cart/addToCart?items=")
    parts = dict(p.split("|") for p in url.split("items=")[1].split(","))
    assert parts["123456"] == "3"
    assert parts[d["lines"][1]["product"]["item_id"]] == "4"  # 3 + 1 merged
    assert len(parts) == 3


def test_cart_bad_store_and_item_id(client, api_key):
    h = {"X-API-Key": api_key}
    assert client.post("/v1/cart", headers=h, json={"store": "target", "items": [{"name": "a"}]}).status_code == 400
    r = client.post("/v1/cart", headers=h, json={"items": [{"name": "a", "item_id": "abc"}]}).json()
    assert r["cart_url"] is None and r["unmatched"][0]["reason"].startswith("invalid")


def test_revoked_key_stops_working(client, api_key):
    page = client.get("/dashboard").text
    import re
    key_id = re.search(r"/keys/(\d+)/revoke", page).group(1)
    client.post(f"/keys/{key_id}/revoke", data={"csrf": csrf(page)})
    assert client.get("/v1/me", headers={"X-API-Key": api_key}).status_code == 401


def test_walmart_signature_verifies():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sig = sign_walmart_request(key, "consumer-123", "1", "1700000000000")
    key.public_key().verify(base64.b64decode(sig), b"consumer-123\n1700000000000\n1\n",
                            padding.PKCS1v15(), hashes.SHA256())


def test_cart_rate_limits(client, api_key, monkeypatch):
    from app.config import get_settings
    h = {"Authorization": f"Bearer {api_key}"}
    body = {"items": [{"name": "milk"}]}
    assert client.post("/v1/cart", headers=h, json=body).status_code == 200
    assert client.post("/v1/cart", headers=h, json=body).status_code == 200
    r = client.post("/v1/cart", headers=h, json=body)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0 and "per 5 minutes" in r.json()["detail"]
    assert client.get("/v1/me", headers=h).status_code == 200  # only /v1/cart is limited


def test_cart_daily_limit(client, api_key, monkeypatch):
    from datetime import timedelta
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import CartRequestLog, utcnow
    h = {"Authorization": f"Bearer {api_key}"}
    with SessionLocal() as db:  # 5 earlier requests today, all outside the 5-minute window
        for i in range(5):
            db.add(CartRequestLog(user_id=1, created_at=utcnow() - timedelta(hours=1 + i)))
        db.commit()
    assert client.post("/v1/cart", headers=h, json={"items": [{"name": "milk"}]}).status_code == 200
    r = client.post("/v1/cart", headers=h, json={"items": [{"name": "milk"}]})
    assert r.status_code == 429 and "per day" in r.json()["detail"]

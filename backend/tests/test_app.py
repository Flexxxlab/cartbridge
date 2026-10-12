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
    monkeypatch.setattr(get_settings(), "own_key_limit_per_window", 2)
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
    monkeypatch.setattr(get_settings(), "own_key_limit_per_day", 6)
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


# ---------- per-developer Walmart credentials ----------
def _rsa_pem() -> str:
    from cryptography.hazmat.primitives import serialization
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


def _save_creds(client, pem, consumer_id="dev-consumer-1", key_version="2"):
    page = client.get("/dashboard").text
    return client.post("/walmart", data=dict(consumer_id=consumer_id, key_version=key_version,
                                             private_key=pem, publisher_id="", csrf=csrf(page)))


def test_save_credentials_encrypted_and_never_shown(client, api_key):
    pem = _rsa_pem()
    r = _save_creds(client, pem)
    assert r.status_code == 200 and "verified and saved" in r.text
    assert "dev-consumer-1" in r.text
    assert pem.splitlines()[1] not in r.text  # key body is never echoed back
    from app.db import SessionLocal
    from app.models import WalmartCredential
    with SessionLocal() as db:
        row = db.query(WalmartCredential).one()
        assert "PRIVATE KEY" not in row.private_key_enc and row.key_version == "2"
        from app.crypto import decrypt
        assert decrypt(row.private_key_enc) == pem.strip()
    h = {"X-API-Key": api_key}
    assert client.get("/v1/me", headers=h).json()["walmart_credentials"] == "own"
    client.post("/walmart/delete", data={"csrf": csrf(client.get("/dashboard").text)})
    assert client.get("/v1/me", headers=h).json()["walmart_credentials"] == "missing"


def test_bad_credentials_rejected(client, api_key):
    assert "Could not read" in _save_creds(client, "-----" + "BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----").text
    assert "PEM private key" in _save_creds(client, "hello").text
    assert "consumer ID" in _save_creds(client, _rsa_pem(), consumer_id="").text.replace("Consumer ID", "consumer ID")


def test_cart_uses_own_credentials_and_blocks_without(client, api_key, monkeypatch):
    from app import providers
    from app.config import get_settings
    from app.stores import WalmartMockProvider
    monkeypatch.setattr(get_settings(), "walmart_provider", "affiliate")
    h = {"X-API-Key": api_key}
    body = {"items": [{"name": "milk"}]}

    r = client.post("/v1/cart", headers=h, json=body)           # no credentials, not platform
    assert r.status_code == 403 and "Walmart credentials" in r.json()["detail"]

    used = {}

    class Fake(WalmartMockProvider):
        def __init__(self, s, **kw):
            used.update(kw); super().__init__(s); self.closed = False
        async def aclose(self): used["closed"] = True
        async def verify(self): pass
    monkeypatch.setattr(providers, "WalmartAffiliateProvider", Fake)
    monkeypatch.setattr("app.web.WalmartAffiliateProvider", Fake)
    assert _save_creds(client, _rsa_pem()).status_code == 200
    assert used["consumer_id"] == "dev-consumer-1"               # verified before saving
    used.clear()
    assert client.post("/v1/cart", headers=h, json=body).status_code == 200
    assert used["consumer_id"] == "dev-consumer-1" and used["key_version"] == "2" and used["closed"]
    assert "BEGIN" in used["private_key_pem"]


def test_platform_access_uses_server_credentials(client, api_key, monkeypatch):
    from app import providers
    from app.config import get_settings
    from app.stores import WalmartMockProvider
    monkeypatch.setattr(get_settings(), "walmart_provider", "affiliate")
    monkeypatch.setattr(providers, "get_provider", lambda store: WalmartMockProvider(get_settings()))
    h = {"X-API-Key": api_key}
    from app.admin import main
    assert main(["grant", "bob", "--limit", "120:5", "--limit", "3600:10", "--limit", "86400:20"]) == 0
    assert main(["grant", "bob", "--limit", "nonsense"]) == 2
    assert client.get("/v1/me", headers=h).json()["walmart_credentials"] == "platform"
    assert client.post("/v1/cart", headers=h, json={"items": [{"name": "milk"}]}).status_code == 200
    from app.db import SessionLocal
    from app.ratelimit import limits_for
    from app.models import User
    with SessionLocal() as db:
        assert limits_for(db, db.query(User).filter_by(username="bob").one()) == [(120, 5), (3600, 10), (86400, 20)]
    assert main(["revoke", "bob"]) == 0
    assert client.get("/v1/me", headers=h).json()["walmart_credentials"] == "missing"
    assert main(["grant", "nobody"]) == 1


def test_three_tier_limits_and_retry_after(client, api_key):
    from datetime import timedelta
    from app.admin import main
    from app.db import SessionLocal
    from app.models import CartRequestLog, utcnow
    assert main(["grant", "bob", "--limit", "120:5", "--limit", "3600:10", "--limit", "86400:20"]) == 0
    h = {"X-API-Key": api_key}
    body = {"items": [{"name": "milk"}]}
    with SessionLocal() as db:  # 9 requests 10 min ago: outside the 2-min tier, inside the hour tier
        for _ in range(9):
            db.add(CartRequestLog(user_id=1, created_at=utcnow() - timedelta(minutes=10)))
        db.commit()
    assert client.post("/v1/cart", headers=h, json=body).status_code == 200      # 10th this hour
    r = client.post("/v1/cart", headers=h, json=body)                             # 11th: hour tier
    assert r.status_code == 429 and "per hour" in r.json()["detail"]
    assert 2400 < int(r.headers["Retry-After"]) <= 3000                           # oldest ages out in ~50 min


def test_parse_and_describe_limits():
    from app.ratelimit import describe_window, parse_limits
    assert parse_limits("120:5,3600:10") == [(120, 5), (3600, 10)]
    assert [describe_window(x) for x in (120, 3600, 86400, 300, 45)] == ["2 minutes", "hour", "day", "5 minutes", "45 seconds"]
    for bad in ("x", "0:5", "100000:5", "60:-1"):
        try:
            parse_limits(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_dashboard_shows_limits_and_usage(client, api_key, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "own_key_limit_per_window", 2)
    h = {"X-API-Key": api_key}
    client.post("/v1/cart", headers=h, json={"items": [{"name": "milk"}]})
    page = client.get("/dashboard").text
    assert "Rate limits" in page and "per 5 minutes" in page and "per day" in page
    assert "/admin" not in page                       # not an admin
    assert client.get("/admin").status_code == 404


def test_admin_can_edit_limits_and_grant(client, api_key, monkeypatch):
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import PlatformAccess
    from app.ratelimit import limits_for
    monkeypatch.setattr(get_settings(), "admin_usernames", "Bob")
    assert "/admin" in client.get("/dashboard").text
    page = client.get("/admin").text
    assert "Accounts, limits" in page
    post = lambda **kw: client.post("/admin/access", data=dict(csrf=csrf(client.get("/admin").text), user_id=1, **kw))
    assert "Granted bob" in post(action="grant", limits="120:5, 3600:10, 86400:20").text
    with SessionLocal() as db:
        from app.models import User
        assert limits_for(db, db.get(User, 1)) == [(120, 5), (3600, 10), (86400, 20)]
    assert "must look like" in post(action="save", limits="nonsense").text
    assert "Updated bob" in post(action="save", limits="").text        # empty -> server defaults
    assert "Revoked" in post(action="revoke").text
    with SessionLocal() as db:
        assert db.get(PlatformAccess, 1) is None
    bad = client.post("/admin/access", data=dict(csrf="x", user_id=1, action="grant"))
    assert bad.status_code == 400                                       # CSRF enforced


def test_admin_requires_allowlist(client, api_key, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "admin_usernames", "someone_else")
    assert client.get("/admin").status_code == 404
    assert client.post("/admin/access", data=dict(csrf=csrf(client.get("/dashboard").text),
                                                  user_id=1, action="grant")).status_code == 404


def test_footer_on_every_page(client, make_user):
    def check(html):
        assert "mailto:helpdesk@flexxxlab.com" in html
        assert 'href="https://us.flexxxlab.com/"' in html
        assert "/docs" in html and "github.com/Flexxxlab/cartbridge" in html and "&copy;" in html
    for path in ("/", "/signup", "/login"):
        check(client.get(path).text)
    make_user("carol")
    check(client.get("/dashboard").text)


# ---------- self-service limits ----------
def _set_limits(client, rows, action="save"):
    data = {"csrf": csrf(client.get("/dashboard").text), "action": action}
    for i, (count, window) in enumerate(rows):
        data[f"count_{i}"], data[f"window_{i}"] = str(count), str(window)
    return client.post("/limits", data=data)


def test_user_sets_own_limits(client, api_key):
    h = {"X-API-Key": api_key}
    body = {"items": [{"name": "milk"}]}
    page = client.get("/dashboard").text
    assert "Set your limits" in page and "using the defaults" in page
    assert "Limits saved" in _set_limits(client, [(1, 60)]).text
    assert client.post("/v1/cart", headers=h, json=body).status_code == 200
    r = client.post("/v1/cart", headers=h, json=body)
    assert r.status_code == 429 and "1 requests per minute" in r.json()["detail"]
    assert "using your own limits" in client.get("/dashboard").text
    assert "reset to the defaults" in _set_limits(client, [], action="reset").text


def test_user_limits_cannot_exceed_ceiling(client, api_key, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "own_key_max_per_window", 3)
    r = _set_limits(client, [(1000, 300)])
    assert "account maximum still applies: 3 per 5 minutes" in r.text
    h = {"X-API-Key": api_key}
    codes = [client.post("/v1/cart", headers=h, json={"items": [{"name": "milk"}]}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_granted_account_can_only_tighten(client, api_key):
    from app.admin import main
    from app.db import SessionLocal
    from app.models import User
    from app.ratelimit import limits_for
    assert main(["grant", "bob", "--limit", "120:5", "--limit", "86400:20"]) == 0
    _set_limits(client, [(50, 120)])
    with SessionLocal() as db:
        assert limits_for(db, db.get(User, 1)) == [(120, 5), (86400, 20)]
    _set_limits(client, [(2, 120), (10, 3600)])
    with SessionLocal() as db:
        assert limits_for(db, db.get(User, 1)) == [(120, 2), (3600, 10), (86400, 20)]


def test_limits_form_validation(client, api_key):
    assert "a number from 1" in _set_limits(client, [("abc", 60)]).text
    assert "a number from 1" in _set_limits(client, [(5, 7)]).text            # window not offered
    assert "at least one limit" in _set_limits(client, [("", 60)]).text
    assert client.post("/limits", data={"csrf": "bad", "action": "save"}).status_code == 400

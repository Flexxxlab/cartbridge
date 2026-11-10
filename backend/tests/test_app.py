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


def test_cart_rate_limits(client, api_key):
    """Free plan: 10 requests per 5 minutes."""
    h = {"Authorization": f"Bearer {api_key}"}
    body = {"items": [{"name": "milk"}]}
    for _ in range(10):
        assert client.post("/v1/cart", headers=h, json=body).status_code == 200
    r = client.post("/v1/cart", headers=h, json=body)
    detail = r.json()["detail"]
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    # the shared over-limit message shape
    assert "10 requests per 5 minutes" in detail and "on the Free plan" in detail
    assert "Need more? Contact us to buy: mailto:helpdesk@flexxxlab.com" in detail
    assert client.get("/v1/me", headers=h).status_code == 200  # only /v1/cart is limited


def test_cart_monthly_limit(client, api_key):
    """Free plan: 200 requests per calendar month, counted in usage_monthly."""
    from app.db import SessionLocal
    from app.models import UsageMonthly, utcnow
    from app.ratelimit import month_key
    h = {"Authorization": f"Bearer {api_key}"}
    with SessionLocal() as db:  # 199 used this month
        db.add(UsageMonthly(user_id=1, month=month_key(utcnow()), count=199))
        db.commit()
    assert client.post("/v1/cart", headers=h, json={"items": [{"name": "milk"}]}).status_code == 200
    r = client.post("/v1/cart", headers=h, json={"items": [{"name": "milk"}]})
    detail = r.json()["detail"]
    assert r.status_code == 429 and "200 requests per calendar month" in detail and "Free plan" in detail
    assert "Contact us to buy" in detail and int(r.headers["Retry-After"]) > 3600
    with SessionLocal() as db:
        assert db.get(UsageMonthly, (1, month_key(utcnow()))).count == 200
    page = client.get("/dashboard").text  # the dashboard shows the same message
    assert "200 requests per calendar month" in page and "Contact us to buy" in page


def test_month_rollover_helpers():
    from datetime import datetime
    from app.ratelimit import month_key, next_month_start
    assert next_month_start(datetime(2026, 12, 31, 23)) == datetime(2027, 1, 1)
    assert next_month_start(datetime(2026, 10, 23)) == datetime(2026, 11, 1)
    assert month_key(datetime(2026, 3, 9)) == "2026-03"


def test_pro_plan_has_higher_limits_and_platform_ignores_plan(client, api_key):
    from app.db import SessionLocal
    from app.models import UsageMonthly, User, utcnow
    from app.ratelimit import limits_for, month_key, monthly_limit_for
    from app.admin import main
    with SessionLocal() as db:
        u = db.get(User, 1)
        assert u.plan == "free" and monthly_limit_for(db, u) == 200
        u.plan = "pro"
        db.commit()
        assert limits_for(db, u) == [(300, 100), (86400, 5000)] and monthly_limit_for(db, u) == 100_000
    assert main(["grant", "bob", "--limit", "120:5"]) == 0       # operator grant: own limits, no monthly cap
    with SessionLocal() as db:
        u = db.get(User, 1)
        assert limits_for(db, u) == [(120, 5)]
        assert monthly_limit_for(db, u) is None


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
    h = {"X-API-Key": api_key}
    client.post("/v1/cart", headers=h, json={"items": [{"name": "milk"}]})
    page = client.get("/dashboard").text
    assert "Rate limits" in page and "per 5 minutes" in page and "per calendar month" in page
    assert "Free" in page and "Contact us to buy" in page and 'href="mailto:helpdesk@flexxxlab.com"' in page
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
    from dataclasses import replace
    from app.plans import PLANS
    monkeypatch.setitem(PLANS, "free", replace(PLANS["free"], tiers=((300, 3),)))
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


# ---------- self-serve: notices, throttle, plans, admin verify ----------
NOTICE = "Verification emails can take longer than usual. For immediate access, email helpdesk@flexxxlab.com."


def test_signup_shows_pending_notice_and_login_unverified_shows_it_with_resend(client, make_user):
    page = client.get("/signup").text
    assert 'href="/terms"' in page and 'href="/privacy"' in page
    r = client.post("/signup", data=dict(username="fay", email="fay@example.com", password="s3cret-pass",
                                         password2="s3cret-pass", csrf=csrf(page)))
    assert "Check your email" in r.text and NOTICE in r.text
    page = client.get("/dashboard").text
    client.post("/logout", data={"csrf": csrf(page)})
    page = client.get("/login").text
    assert "Email helpdesk@flexxxlab.com" in page          # forgot password
    r = client.post("/login", data={"username": "fay", "password": "s3cret-pass", "csrf": csrf(page)})
    assert NOTICE in r.text and "Resend verification email" in r.text and "Create API key" not in r.text


def test_signup_throttle_429(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "throttle_signup_max", 2)
    for i in range(2):
        page = client.get("/signup").text
        r = client.post("/signup", data=dict(username=f"u{i}x", email=f"u{i}@example.com",
                                             password="s3cret-pass", password2="s3cret-pass", csrf=csrf(page)))
        assert r.status_code == 200
    page = client.get("/signup").text
    r = client.post("/signup", data=dict(username="u3x", email="u3@example.com", password="s3cret-pass",
                                         password2="s3cret-pass", csrf=csrf(page)))
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert "Too many sign-up attempts" in r.text and "helpdesk@flexxxlab.com" in r.text
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        assert db.query(User).count() == 2                    # the throttled signup created nothing


def test_login_and_resend_throttle_429(client, make_user, monkeypatch):
    from app.config import get_settings
    make_user("gus", verify=False)
    monkeypatch.setattr(get_settings(), "throttle_login_max", 3)
    monkeypatch.setattr(get_settings(), "throttle_resend_max", 1)
    page = client.get("/dashboard").text
    assert client.post("/verify/resend", data={"csrf": csrf(page)}).status_code == 200
    r = client.post("/verify/resend", data={"csrf": csrf(page)})
    assert r.status_code == 429 and "Retry-After" in r.headers
    page = client.get("/login").text
    codes = [client.post("/login", data={"username": "gus", "password": "wrong-pass", "csrf": csrf(page)}).status_code
             for _ in range(4)]
    assert codes == [400, 400, 400, 429]
    # even the right password is refused while throttled
    assert client.post("/login", data={"username": "gus", "password": "s3cret-pass", "csrf": csrf(page)}).status_code == 429


def test_throttle_is_per_ip_and_window_expires(client):
    from datetime import timedelta
    from app.db import SessionLocal
    from app.models import AuthAttempt, utcnow
    from app.throttle import retry_after
    with SessionLocal() as db:
        for _ in range(5):
            assert retry_after(db, "1.1.1.1", "signup") == 0
        assert retry_after(db, "1.1.1.1", "signup") > 0
        assert retry_after(db, "2.2.2.2", "signup") == 0       # another IP is unaffected
        for row in db.query(AuthAttempt).filter_by(ip="1.1.1.1").all():
            row.created_at = utcnow() - timedelta(hours=2)
        db.commit()
        assert retry_after(db, "1.1.1.1", "signup") == 0       # old attempts age out


def test_admin_verify_and_plan_and_cli(client, make_user, monkeypatch):
    from app.admin import main
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import User
    make_user("admin1")                                         # id 1, verified
    monkeypatch.setattr(get_settings(), "admin_usernames", "admin1")
    make_user("henry", verify=False)                            # id 2
    page = client.get("/login").text
    client.post("/login", data={"username": "admin1", "password": "s3cret-pass", "csrf": csrf(page)})
    page = client.get("/admin").text
    assert "waiting for verification" in page
    post = lambda **kw: client.post("/admin/access", data=dict(csrf=csrf(client.get("/admin").text), **kw))
    assert "Verified henry" in post(user_id=2, action="verify").text
    assert "now on the Pro plan" in post(user_id=2, action="plan", plan="pro").text
    assert "Unknown plan" in post(user_id=2, action="plan", plan="gold").text
    with SessionLocal() as db:
        u = db.get(User, 2)
        assert u.is_verified and u.plan == "pro"
    assert main(["plan", "henry", "free"]) == 0 and main(["users"]) == 0


def test_cli_verify_move_key_delete(client, api_key, make_user):
    from app.admin import main
    from app.db import SessionLocal
    from app.models import ApiKey, PlatformAccess, User
    make_user("presspot", verify=False)
    assert main(["verify", "presspot@example.com"]) == 0 and main(["verify", "nobody"]) == 1
    assert main(["grant", "bob", "--limit", "120:5"]) == 0
    with SessionLocal() as db:
        prefix = db.query(ApiKey).one().prefix
    assert main(["keys"]) == 0
    assert main(["move-key", prefix, "presspot"]) == 0
    with SessionLocal() as db:
        pp = db.query(User).filter_by(username="presspot").one()
        assert db.query(ApiKey).one().user_id == pp.id and db.get(PlatformAccess, pp.id).limits == "120:5"
        assert db.get(PlatformAccess, 1) is None
    h = {"X-API-Key": api_key}                                  # the key value still works
    assert client.get("/v1/me", headers=h).json()["username"] == "presspot"
    assert main(["delete-user", "presspot", "--yes"]) == 2      # owns the key + grant: refused
    assert main(["delete-user", "bob"]) == 2                    # needs --yes
    assert main(["delete-user", "bob", "--yes"]) == 0
    with SessionLocal() as db:
        assert db.query(User).filter_by(username="bob").first() is None


def test_delete_user_refused_with_grant_or_key_unless_force(client, api_key):
    from app.admin import main
    from app.db import SessionLocal
    from app.models import User
    assert main(["delete-user", "bob", "--yes"]) == 2           # owns an active key
    assert main(["revoke", "bob"]) == 0
    assert main(["grant", "bob"]) == 0
    assert main(["delete-user", "bob", "--yes"]) == 2           # owns a platform grant
    with SessionLocal() as db:
        assert db.query(User).filter_by(username="bob").first() is not None
    assert main(["delete-user", "bob", "--yes", "--force"]) == 0
    with SessionLocal() as db:
        assert db.query(User).filter_by(username="bob").first() is None


def test_move_key_aborts_if_target_has_grant_unless_force(client, api_key, make_user):
    from app.admin import main
    from app.db import SessionLocal
    from app.models import ApiKey, PlatformAccess
    make_user("presspot", verify=False)
    assert main(["grant", "bob", "--limit", "120:5"]) == 0
    assert main(["grant", "presspot"]) == 0
    with SessionLocal() as db:
        prefix = db.query(ApiKey).one().prefix
    assert main(["move-key", prefix, "presspot"]) == 2          # target already has a grant
    with SessionLocal() as db:
        assert db.query(ApiKey).one().user_id == 1 and db.get(PlatformAccess, 1).limits == "120:5"
    assert main(["move-key", prefix, "presspot", "--force"]) == 0
    with SessionLocal() as db:
        assert db.query(ApiKey).one().user_id == 2 and db.get(PlatformAccess, 1) is not None  # grant stayed


def test_monthly_counter_first_insert_increment_and_race(client):
    from app.db import SessionLocal
    from app.models import UsageMonthly
    from app.ratelimit import _bump_monthly
    with SessionLocal() as db:
        assert db.get(UsageMonthly, (7, "2026-10")) is None
        _bump_monthly(db, 7, "2026-10"); db.commit()
        assert db.get(UsageMonthly, (7, "2026-10")).count == 1
        _bump_monthly(db, 7, "2026-10"); db.commit()
        db.expire_all()
        assert db.get(UsageMonthly, (7, "2026-10")).count == 2
    # lost race: our UPDATE saw no row, but another request inserted it before our INSERT
    with SessionLocal() as other:
        other.add(UsageMonthly(user_id=8, month="2026-10", count=1)); other.commit()
    with SessionLocal() as db:
        real, calls = db.execute, []
        def racing(stmt, *a, **k):
            if not calls:
                calls.append(1)
                return type("R", (), {"rowcount": 0})()
            return real(stmt, *a, **k)
        db.execute = racing
        _bump_monthly(db, 8, "2026-10"); db.commit()
    with SessionLocal() as db:
        assert db.get(UsageMonthly, (8, "2026-10")).count == 2


def test_public_pages_seo_and_footer(client):
    import json, re
    for path in ("/", "/features", "/getting-started", "/faq", "/pricing", "/contact", "/terms", "/privacy", "/signup"):
        r = client.get(path)
        assert r.status_code == 200, path
        html = r.text
        assert '<html lang="en">' in html and re.search(r'<title>[^<]{10,}</title>', html)
        assert re.search(r'<meta name="description" content="[^"]{40,}">', html), path
        want = "http://testserver/" if path == "/" else f"http://testserver{path}"
        assert f'<link rel="canonical" href="{want}">' in html, path
        assert 'property="og:title"' in html and "application/ld+json" in html
        ld = json.loads(re.search(r'application/ld\+json">(.*?)</script>', html, re.S).group(1))
        assert {n["@type"] for n in ld["@graph"]} == {"SoftwareApplication", "Organization"}
        for link in ("/terms", "/privacy", "/pricing", "/getting-started", "/contact"):   # shared footer
            assert f'href="{link}"' in html
    assert "Walmart cart API" in client.get("/").text
    assert "Flutter Walmart add to cart" in client.get("/getting-started").text
    assert "grocery cart link" in client.get("/faq").text.lower()
    pricing = client.get("/pricing").text
    assert "10 requests per 5 minutes" in pricing and "200 requests per calendar month" in pricing
    assert "Contact us to buy" in pricing and "$" not in pricing.replace("$0", "")
    assert '<meta name="robots" content="noindex">' in client.get("/login").text


def test_robots_sitemap_llms(client):
    robots = client.get("/robots.txt")
    assert robots.status_code == 200 and "Sitemap: http://testserver/sitemap.xml" in robots.text
    assert "Disallow: /dashboard" in robots.text
    sm = client.get("/sitemap.xml")
    assert sm.status_code == 200 and "xml" in sm.headers["content-type"]
    for p in ("/features", "/getting-started", "/faq", "/pricing", "/terms", "/privacy", "/contact"):
        assert f"<loc>http://testserver{p}</loc>" in sm.text
    llms = client.get("/llms.txt")
    assert llms.status_code == 200 and "/v1/cart" in llms.text and "cart_bridge" in llms.text
    assert "helpdesk@flexxxlab.com" in llms.text and client.get("/favicon.svg").status_code == 200


def test_home_redirects_logged_in_user(client, make_user):
    make_user("ivy")
    assert client.get("/", follow_redirects=False).headers["location"] == "/dashboard"


def test_migration_is_idempotent_on_old_schema(tmp_path):
    """An old-schema DB (no users.plan, no new tables) is upgraded in place, twice, without losing rows."""
    import sqlite3
    from sqlalchemy import create_engine, inspect
    from app.migrate import migrate
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""
      CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(32) NOT NULL UNIQUE, email VARCHAR(254) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL, email_verified_at DATETIME, is_active BOOLEAN NOT NULL, created_at DATETIME NOT NULL);
      CREATE TABLE platform_access (user_id INTEGER PRIMARY KEY REFERENCES users(id));
      INSERT INTO users VALUES (1,'old','old@example.com','x','2026-01-01',1,'2026-01-01');
      INSERT INTO platform_access VALUES (1);
    """)
    con.commit(); con.close()
    eng = create_engine(f"sqlite:///{path}")
    first = migrate(eng)
    assert "added users.plan" in first and "added platform_access.limits" in first
    assert "created table usage_monthly" in first and "created table auth_attempts" in first
    assert migrate(eng) == []                                   # second run does nothing
    with eng.connect() as c:
        from sqlalchemy import text
        assert c.execute(text("SELECT username, plan FROM users")).all() == [("old", "free")]
        assert c.execute(text("SELECT count(*) FROM platform_access")).scalar() == 1
    assert "plan" in {c["name"] for c in inspect(eng).get_columns("users")}


def test_admin_by_email_verified_only(client, make_user, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "admin_usernames", "Carol@Example.com")
    make_user("carol", verify=False)
    assert client.get("/admin").status_code == 404           # unverified, email listed


def test_admin_by_email_verified_ok(client, make_user, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "admin_usernames", "Carol@Example.com")
    make_user("carol")
    assert client.get("/admin").status_code == 200


def test_admin_by_email_unlisted_refused(client, make_user, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "admin_usernames", "other@example.com")
    make_user("carol")
    assert client.get("/admin").status_code == 404


def test_home_promo_video_is_served(client):
    html = client.get("/").text
    assert 'data-promo-player' in html and 'preload="none"' in html and "autoplay" not in html
    assert client.get("/static/promo-video.js").status_code == 200
    assert client.get("/static/cartbridge_promo_poster.jpg").status_code == 200
    r = client.get("/static/cartbridge_promo.mp4", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100


def test_favicons_are_served(client):
    for url, kind in (("/favicon.ico", "image/x-icon"), ("/favicon-32.png", "image/png"),
                      ("/apple-touch-icon.png", "image/png"), ("/site.webmanifest", "application/manifest+json"),
                      ("/favicon.svg", "image/svg+xml")):
        r = client.get(url)
        assert r.status_code == 200 and r.headers["content-type"].startswith(kind), url
    assert 'href="/favicon.ico"' in client.get("/").text

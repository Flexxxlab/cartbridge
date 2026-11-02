"""Transactional email: Resend sender, verification and reset tokens, enumeration safety, rate limits."""
import json
import re
from datetime import timedelta

import httpx
import pytest

from app import emailer
from app.config import get_settings
from app.db import SessionLocal
from app.models import EmailToken, User, utcnow
from conftest import confirm_verify, csrf

KEY = "re_test_SECRET_do_not_log"
PW = "s3cret-pass"


@pytest.fixture
def resend(monkeypatch):
    """Enables Resend with a mocked HTTP transport. `sent` collects the requests (no real email)."""
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"id": "em_1"})

    monkeypatch.setattr(get_settings(), "resend_api_key", KEY)
    monkeypatch.setattr(emailer, "_transport", httpx.MockTransport(handler))
    return sent


def body(req: httpx.Request) -> dict:
    return json.loads(req.content)


def token_from(req: httpx.Request, path: str) -> str:
    return re.search(rf"{path}\?token=([\w-]+)", body(req)["text"]).group(1)


def signup(client, name="dora", verify=False, sent=None):
    page = client.get("/signup").text
    r = client.post("/signup", data=dict(username=name, email=f"{name}@example.com", password=PW,
                                         password2=PW, csrf=csrf(page)))
    assert r.status_code == 200, r.text
    return r


def login(client, name="dora", password=PW):
    page = client.get("/login").text
    return client.post("/login", data={"username": name, "password": password, "csrf": csrf(page)},
                       follow_redirects=False)


# ---------- the sender ----------
def test_sender_posts_to_resend_with_headers_and_payload(resend):
    ok = emailer.send_email("zed@example.com", "Hi", "plain", "<b>html</b>", idempotency_key="verify-abc")
    assert ok and len(resend) == 1
    req = resend[0]
    assert req.url == "https://api.resend.com/emails"
    assert req.headers["Authorization"] == f"Bearer {KEY}"
    assert req.headers["Idempotency-Key"] == "verify-abc"
    p = body(req)
    assert p["from"] == "CartBridge <helpdesk@flexxxlab.com>" and p["reply_to"] == "helpdesk@flexxxlab.com"
    assert p["to"] == ["zed@example.com"] and p["text"] == "plain" and p["html"] == "<b>html</b>"


def test_sender_failure_never_raises_and_never_logs_key(monkeypatch, caplog):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500, json={"message": "boom"})

    monkeypatch.setattr(get_settings(), "resend_api_key", KEY)
    monkeypatch.setattr(emailer, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(emailer.time, "sleep", lambda s: None)
    with caplog.at_level("DEBUG"):
        assert emailer.send_email("zed@example.com", "Hi", "plain") is False
    assert len(calls) == 2                                   # one retry on 5xx
    assert KEY not in caplog.text and "zed@example.com" not in caplog.text


def test_sender_4xx_is_not_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(get_settings(), "resend_api_key", KEY)
    monkeypatch.setattr(emailer, "_transport",
                        httpx.MockTransport(lambda r: calls.append(1) or httpx.Response(403)))
    assert emailer.send_email("zed@example.com", "Hi", "x") is False and len(calls) == 1


def test_no_key_falls_back_to_log_only_with_helpdesk_notices(client, make_user, capsys):
    assert not get_settings().email_enabled
    r = signup(client, "nokey")
    assert "Verification emails can take longer than usual" in r.text
    assert emailer.outbox[-1]["To"] == "nokey@example.com"
    out = capsys.readouterr().out
    assert "/verify?token=" in out                           # dev (http) console shows the link
    assert "Email helpdesk@flexxxlab.com" in client.get("/login").text
    page = client.get("/forgot").text
    assert "Email helpdesk@flexxxlab.com" in page and "<form" not in page.split("</h1>")[1].split("Back to")[0]
    r = client.post("/forgot", data={"email": "nokey@example.com", "csrf": csrf(client.get("/login").text)})
    assert r.status_code == 200
    with SessionLocal() as db:
        assert db.query(EmailToken).filter_by(purpose="reset").count() == 0


def test_tokens_masked_in_logs_on_https(monkeypatch, capsys, caplog):
    monkeypatch.setattr(get_settings(), "base_url", "https://cartbridge.example")
    emailer.send_email("a@example.com", "s", "link https://x/verify?token=abcdefSECRETSECRET\nend")
    out = capsys.readouterr().out
    assert "token=abcdef..." in out and "SECRETSECRET" not in out
    assert emailer.mask_email("jane@example.com") == "j***@example.com"


def test_access_log_filter_redacts_tokens():
    import logging
    from app.main import _RedactTokens
    rec = logging.LogRecord("uvicorn.access", 20, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4", "GET", "/reset?token=abcdefSECRETSECRET", "1.1", 200), None)
    _RedactTokens().filter(rec)
    assert "SECRETSECRET" not in rec.getMessage() and "token=abcdef..." in rec.getMessage()


# ---------- verification ----------
def test_signup_sends_verification_email_via_resend(client, resend):
    r = signup(client)
    assert "longer than usual" not in r.text and "24 hours" in r.text
    assert len(resend) == 1
    p = body(resend[0])
    assert p["to"] == ["dora@example.com"] and "Verify" in p["subject"]
    assert "expires in 24 hours" in p["text"] and "<a href=" in p["html"] and "CartBridge" in p["html"]
    assert resend[0].headers["Idempotency-Key"].startswith("verify-")
    tok = token_from(resend[0], "/verify")
    with SessionLocal() as db:                               # only the hash is stored
        assert db.query(EmailToken).filter_by(token_hash=tok).count() == 0
    assert client.get(f"/verify?token={tok}").status_code == 200   # GET alone (a mail scanner) uses nothing up
    assert client.get(f"/verify?token={tok}").status_code == 200
    with SessionLocal() as db:
        assert db.query(User).one().email_verified_at is None
    assert "Email verified" in confirm_verify(client, tok).text
    again = confirm_verify(client, tok)                      # single use
    assert again.status_code == 400 and "invalid or expired" in again.text
    assert again.headers["Referrer-Policy"] == "no-referrer"


def test_verification_token_expires(client, resend):
    signup(client)
    tok = token_from(resend[0], "/verify")
    with SessionLocal() as db:
        for t in db.query(EmailToken).all():
            t.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert confirm_verify(client, tok).status_code == 400
    with SessionLocal() as db:
        assert db.query(User).one().email_verified_at is None


def test_resend_voids_older_link_and_is_limited_per_account(client, resend, monkeypatch):
    signup(client)
    old = token_from(resend[0], "/verify")
    page = client.get("/dashboard").text
    assert client.post("/verify/resend", data={"csrf": csrf(page)}).status_code == 200
    assert len(resend) == 2
    new = token_from(resend[1], "/verify")
    assert client.get(f"/verify?token={old}").status_code == 400
    assert "Email verified" in confirm_verify(client, new).text


def test_resend_limit_per_account_and_ip(client, resend, monkeypatch):
    signup(client)
    page = client.get("/dashboard").text
    codes = [client.post("/verify/resend", data={"csrf": csrf(page)}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]                     # default 3/hour
    assert len(resend) == 4                                  # signup + 3 resends
    # per-account limit holds even from a different IP
    monkeypatch.setattr(get_settings(), "throttle_resend_max", 100)
    r = client.post("/verify/resend", data={"csrf": csrf(page)})
    assert r.status_code == 429 and "your account" in r.text and "Retry-After" in r.headers
    assert len(resend) == 4


# ---------- forgot / reset ----------
def forgot(client, email):
    page = client.get("/forgot").text
    return client.post("/forgot", data={"email": email, "csrf": csrf(page)})


def verified_user(client, resend, name="dora"):
    signup(client, name)
    assert "Email verified" in confirm_verify(client, token_from(resend[-1], '/verify')).text
    page = client.get("/dashboard").text
    client.post("/logout", data={"csrf": csrf(page)})
    resend.clear()


def test_forgot_response_is_identical_for_known_and_unknown(client, resend):
    verified_user(client, resend)
    a = forgot(client, "dora@example.com")
    b = forgot(client, "ghost@example.com")
    c = forgot(client, "not-an-email")
    strip = lambda r: re.sub(r'name="csrf" value="[^"]+"', "", r.text)
    assert a.status_code == b.status_code == c.status_code == 200
    assert strip(a) == strip(b) == strip(c)
    assert len(resend) == 1 and body(resend[0])["to"] == ["dora@example.com"]   # only the real account got mail


def test_reset_flow_end_to_end_invalidates_sessions_and_old_tokens(client, resend):
    verified_user(client, resend)
    # a second browser that is logged in with the old password
    from fastapi.testclient import TestClient
    from app.main import app
    other = TestClient(app)
    assert login(other).status_code == 303 and other.get("/dashboard").status_code == 200

    forgot(client, "dora@example.com")
    forgot(client, "dora@example.com")
    assert len(resend) == 2
    first, second = token_from(resend[0], "/reset"), token_from(resend[1], "/reset")
    assert body(resend[0])["subject"].startswith("Reset your")
    assert "expires in 60 minutes" in body(resend[0])["text"]

    assert client.get(f"/reset?token={second}").status_code == 200
    assert client.get(f"/reset?token={first}").status_code == 200    # older link stays valid (no lockout)
    page = client.get(f"/reset?token={second}").text
    bad = client.post("/reset", data={"token": second, "password": "short", "password2": "short", "csrf": csrf(page)})
    assert bad.status_code == 400 and "8–128" in bad.text
    r = client.post("/reset", data={"token": second, "password": "brand-new-pass", "password2": "brand-new-pass",
                                    "csrf": csrf(page)})
    assert r.status_code == 200 and "Password updated" in r.text

    assert client.post("/reset", data={"token": second, "password": "again-again-1", "password2": "again-again-1",
                                       "csrf": csrf(page)}).status_code == 400    # single use
    assert login(client, password=PW).status_code == 400
    assert login(client, password="brand-new-pass").status_code == 303
    assert other.get("/dashboard", follow_redirects=False).status_code == 303   # old session is dead
    assert client.get(f"/reset?token={first}").status_code == 400    # success voids the other pending link


def test_reset_token_expires_and_is_hashed(client, resend):
    verified_user(client, resend)
    forgot(client, "dora@example.com")
    tok = token_from(resend[0], "/reset")
    with SessionLocal() as db:
        rows = db.query(EmailToken).filter_by(purpose="reset").all()
        assert len(rows) == 1 and rows[0].token_hash != tok and len(rows[0].token_hash) == 64
        assert rows[0].expires_at - utcnow() < timedelta(minutes=61)
        rows[0].expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get(f"/reset?token={tok}").status_code == 400
    page = client.get("/forgot").text
    r = client.post("/reset", data={"token": tok, "password": "brand-new-pass", "password2": "brand-new-pass",
                                    "csrf": csrf(page)})
    assert r.status_code == 400
    assert login(client, password=PW).status_code == 303


def test_verification_link_is_not_a_reset_link(client, resend):
    signup(client)
    tok = token_from(resend[0], "/verify")
    assert client.get(f"/reset?token={tok}").status_code == 400


def test_forgot_rate_limits_per_ip_and_per_address(client, resend, monkeypatch):
    verified_user(client, resend)
    # per address: 3/hour; the 4th is silently skipped, response unchanged
    rs = [forgot(client, "dora@example.com") for _ in range(4)]
    assert [r.status_code for r in rs] == [200] * 4 and len(resend) == 3
    # an unknown address behaves the same way (limit applies to the hash of the input)
    resend.clear()
    # per IP: total 5/hour, then 429 for everyone, existing or not
    assert forgot(client, "a@example.com").status_code == 200   # 5th request from this IP
    r = forgot(client, "dora@example.com")
    assert r.status_code == 429 and "Retry-After" in r.headers and "password reset requests" in r.text
    r2 = forgot(client, "ghost@example.com")
    assert r2.status_code == 429


def test_reset_verifies_unverified_mailbox_owner(client, resend):
    signup(client, "erin")
    resend.clear()
    forgot(client, "erin@example.com")
    tok = token_from(resend[0], "/reset")
    page = client.get(f"/reset?token={tok}").text
    client.post("/reset", data={"token": tok, "password": "brand-new-pass", "password2": "brand-new-pass",
                                "csrf": csrf(page)})
    with SessionLocal() as db:
        assert db.query(User).filter_by(username="erin").one().email_verified_at is not None


# ---------- batch script ----------
def test_send_verifications_dry_run_then_send(client, resend, capsys):
    from app import send_verifications
    signup(client, "fran")
    with SessionLocal() as db:                               # signup mail was "long ago" (or only logged)
        for t in db.query(EmailToken).all():
            t.expires_at = utcnow() - timedelta(hours=1)
        db.commit()
    resend.clear()
    assert send_verifications.main([]) == 0
    out = capsys.readouterr().out
    assert "1 unverified" in out and "f***@example.com" in out and "fran@example.com" not in out
    assert resend == []                                       # default is a dry run
    from app import send_verifications as sv
    sv.PAUSE_SECONDS = 0
    assert sv.main(["--send"]) == 0
    assert len(resend) == 1 and body(resend[0])["to"] == ["fran@example.com"]
    out = capsys.readouterr().out
    assert "sent: user" in out and token_from(resend[0], "/verify") not in out


def test_send_verifications_refuses_without_key(client, capsys):
    from app import send_verifications
    signup(client, "gil")
    assert send_verifications.main(["--send"]) == 2


def test_verify_post_requires_csrf(client, resend):
    signup(client)
    tok = token_from(resend[0], "/verify")
    assert client.post("/verify", data={"token": tok, "csrf": "bad"}).status_code == 400
    assert "Email verified" in confirm_verify(client, tok).text


def test_repeated_forgot_does_not_void_pending_reset_links(client, resend):
    verified_user(client, resend)
    forgot(client, "dora@example.com")
    first = token_from(resend[0], "/reset")
    forgot(client, "dora@example.com")                       # an attacker (or the user) asks again
    second = token_from(resend[1], "/reset")
    assert client.get(f"/reset?token={first}").status_code == 200   # the first link still works
    assert client.get(f"/reset?token={second}").status_code == 200
    page = client.get(f"/reset?token={first}").text
    r = client.post("/reset", data={"token": first, "password": "brand-new-pass", "password2": "brand-new-pass",
                                    "csrf": csrf(page)})
    assert r.status_code == 200
    assert client.get(f"/reset?token={second}").status_code == 400  # a successful reset voids the rest


def test_reset_revokes_api_keys_with_notice(client, resend):
    verified_user(client, resend)
    login(client)
    page = client.get("/dashboard").text
    client.post("/keys", data={"name": "k", "csrf": csrf(page)})
    page = client.get("/dashboard").text
    client.post("/logout", data={"csrf": csrf(page)})
    forgot(client, "dora@example.com")
    tok = token_from(resend[-1], "/reset")
    page = client.get(f"/reset?token={tok}").text
    r = client.post("/reset", data={"token": tok, "password": "brand-new-pass", "password2": "brand-new-pass",
                                    "csrf": csrf(page)})
    assert "1 API key was revoked" in r.text
    from app.models import ApiKey
    with SessionLocal() as db:
        assert db.query(ApiKey).filter(ApiKey.revoked_at.is_(None)).count() == 0


def test_send_verifications_rerun_skips_recent_and_retries_failures(client, resend, monkeypatch, capsys):
    from app import send_verifications as sv
    monkeypatch.setattr(sv, "PAUSE_SECONDS", 0)
    signup(client, "hal")
    with SessionLocal() as db:                               # pretend hal's signup mail was long ago
        for t in db.query(EmailToken).all():
            t.expires_at = utcnow() - timedelta(hours=1)
        db.commit()
    resend.clear()
    fail = {"on": True}
    monkeypatch.setattr(emailer, "_transport", httpx.MockTransport(
        lambda r: httpx.Response(500) if fail["on"] else (resend.append(r) or httpx.Response(200, json={}))))
    monkeypatch.setattr(emailer.time, "sleep", lambda s: None)
    assert sv.main(["--send"]) == 1                          # send fails
    fail["on"] = False
    assert sv.main(["--send"]) == 0                          # failure was retried
    assert len(resend) == 1
    capsys.readouterr()
    assert sv.main(["--send"]) == 0 and len(resend) == 1     # third run: skipped, nobody mailed twice
    assert "0 unverified active user(s) to mail; 1 skipped" in capsys.readouterr().out

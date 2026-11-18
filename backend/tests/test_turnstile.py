import httpx
import pytest

from app import antibot
from app.config import get_settings
from conftest import ab, csrf


@pytest.fixture
def ts_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "turnstile_site_key", "site-key")
    monkeypatch.setattr(get_settings(), "turnstile_secret_key", "secret")


def _post(client, name, token=None):
    page = client.get("/signup").text
    data = dict(username=name, email=f"{name}@example.com", password="s3cret-pass", password2="s3cret-pass",
                csrf=csrf(page), **ab(page))
    if token:
        data["cf-turnstile-response"] = token
    return client.post("/signup", data=data), page


def _mock(monkeypatch, success=True, exc=None):
    calls = []

    def fake(url, data=None, timeout=None):
        calls.append(data)
        if exc:
            raise exc
        return httpx.Response(200, json={"success": success}, request=httpx.Request("POST", url))
    monkeypatch.setattr(antibot.httpx, "post", fake)
    return calls


def _exists(client, name):
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        return db.query(User).filter_by(username=name).first() is not None


def test_widget_rendered(client, ts_on):
    page = client.get("/signup").text
    assert 'class="cf-turnstile"' in page and "site-key" in page and "challenges.cloudflare.com" in page


def test_success_creates_user(client, ts_on, monkeypatch):
    calls = _mock(monkeypatch)
    r, _ = _post(client, "tsok", "tok")
    assert r.status_code == 200 and _exists(client, "tsok")
    assert calls[0]["response"] == "tok" and calls[0]["secret"] == "secret"


def test_failure_blocks(client, ts_on, monkeypatch):
    _mock(monkeypatch, success=False)
    r, _ = _post(client, "tsbad", "tok")
    assert r.status_code == 400 and "complete the check" in r.text and not _exists(client, "tsbad")


def test_missing_token_blocks(client, ts_on, monkeypatch):
    calls = _mock(monkeypatch)
    r, _ = _post(client, "tsnone")
    assert r.status_code == 400 and not _exists(client, "tsnone") and not calls


def test_network_error_fails_closed(client, ts_on, monkeypatch):
    _mock(monkeypatch, exc=httpx.ConnectError("down"))
    r, _ = _post(client, "tsnet", "tok")
    assert r.status_code == 400 and not _exists(client, "tsnet")


def test_skipped_when_unset(client, monkeypatch):
    calls = _mock(monkeypatch, success=False)
    r, page = _post(client, "tsoff")
    assert r.status_code == 200 and _exists(client, "tsoff") and not calls and "cf-turnstile" not in page

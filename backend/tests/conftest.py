import os, re, sys
from pathlib import Path

DB = Path(__file__).parent / "test.db"
if DB.exists():
    DB.unlink()
os.environ.update(DATABASE_URL=f"sqlite:///{DB}", WALMART_PROVIDER="mock", SMTP_HOST="", BASE_URL="http://testserver")
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import emailer


@pytest.fixture
def client():
    from app.db import Base, engine
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        yield c


def csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


@pytest.fixture
def make_user(client):
    def _make(username="alice", verify=True):
        page = client.get("/signup").text
        r = client.post("/signup", data=dict(username=username, email=f"{username}@example.com",
                                             password="s3cret-pass", password2="s3cret-pass", csrf=csrf(page)))
        assert r.status_code == 200, r.text
        if verify:
            body = emailer.outbox[-1].get_content()
            token = re.search(r"token=([\w-]+)", body).group(1)
            assert "verified" in client.get(f"/verify?token={token}").text
        return username
    return _make


@pytest.fixture
def api_key(client, make_user):
    make_user("bob")
    page = client.get("/dashboard").text
    r = client.post("/keys", data={"name": "test", "csrf": csrf(page)})
    return re.search(r'class="key">(cb_[\w-]+)<', r.text).group(1)

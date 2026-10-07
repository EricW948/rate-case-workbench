"""Auth gate tests: team sign-in via APP_PASSWORD."""
import pytest
from fastapi.testclient import TestClient

import main
import seed


@pytest.fixture
def locked_client(db, monkeypatch):
    seed.seed()
    monkeypatch.setenv("APP_PASSWORD", "capitol-works")
    with TestClient(main.app) as client:
        yield client


def test_open_without_password(db):
    seed.seed()
    with TestClient(main.app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "Rate Case Workbench" in r.text


def test_locked_redirects_to_login(locked_client):
    r = locked_client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_healthz_always_open(locked_client):
    assert locked_client.get("/healthz").json() == {"ok": True}


def test_login_page_renders(locked_client):
    r = locked_client.get("/login")
    assert r.status_code == 200
    assert "Team sign-in" in r.text


def test_wrong_password_rejected(locked_client):
    r = locked_client.post("/login", data={"password": "nope"})
    assert r.status_code == 401
    assert "not it" in r.text
    r2 = locked_client.get("/", follow_redirects=False)
    assert r2.status_code == 303  # still locked out


def test_correct_password_unlocks(locked_client):
    r = locked_client.post("/login", data={"password": "capitol-works"},
                           follow_redirects=False)
    assert r.status_code == 303
    assert "rcw_auth" in r.cookies
    r2 = locked_client.get("/")
    assert r2.status_code == 200
    assert "Rate Case Workbench" in r2.text


def test_logout_relocks(locked_client):
    locked_client.post("/login", data={"password": "capitol-works"})
    assert locked_client.get("/").status_code == 200
    locked_client.get("/logout")
    r = locked_client.get("/", follow_redirects=False)
    assert r.status_code == 303

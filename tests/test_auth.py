"""Logged in only with a valid token from our Supabase project."""
import time

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from api.main import app
from tests.conftest import API, token


def me(authorization: str | None):
    headers = {"Authorization": authorization} if authorization else {}
    return TestClient(app, base_url=API).get("/me", headers=headers)


def test_a_valid_token_is_the_user():
    response = me(f"Bearer {token('u1', 'anna@example.se')}")
    assert response.status_code == 200
    assert response.json() == {"email": "anna@example.se", "name": "Anna"}


@pytest.mark.parametrize("authorization", [
    None,
    "Bearer",
    "Bearer inte-en-token",
    f"Basic {token('u1', 'anna@example.se')}",
    f"Bearer {token('u1', 'anna@example.se', exp=int(time.time()) - 60)}",  # expired
    f"Bearer {token('u1', 'anna@example.se', aud='anon')}",  # the anon key's audience, not a logged-in user
    f"Bearer {token('u1', 'anna@example.se', iss='https://annat-projekt.supabase.co/auth/v1')}",
    f"Bearer {token('u1', 'anna@example.se', key=ec.generate_private_key(ec.SECP256R1()))}",  # signed by someone else
])
def test_anything_else_is_401(authorization):
    assert me(authorization).status_code == 401


def test_login_and_logout_are_gone():
    client = TestClient(app, base_url=API)
    assert client.post("/login", json={"email": "a", "password": "b"}).status_code in (404, 405)
    assert client.post("/logout").status_code in (404, 405)


def test_the_api_is_under_api():
    """On Vercel the backend gets /api/... as it is (vercel.json), so the routes must be there too."""
    assert TestClient(app).get("/folders").status_code == 404
    assert TestClient(app).get("/api/folders").status_code == 401


def test_on_vercel_without_database_url_it_says_so(monkeypatch):
    from api import db

    db.close()
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("DATABASE_URL")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        db.connect()

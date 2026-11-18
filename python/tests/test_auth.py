"""Phase B contract tests: accounts, tokens, owner visibility, library and progress.

Auth is opt-in: an instance with no ``AAB_JWT_SECRET`` keeps the single-operator behavior,
and all of Phase A's HTTP contract tests still pass unchanged against that default. These
tests build apps with a secret configured via ``dataclasses.replace``.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.api.app import create_app
from services.api.services import audio as audio_service
from services.worker.worker.main import HANDLERS
from aab_jobs import drain

SAMPLE = Path(__file__).parent / "fixtures" / "sample.txt"
SECRET = "test-jwt-secret-at-least-32-bytes-long!!"


@pytest.fixture()
def auth_settings(settings):
    return dataclasses.replace(settings, jwt_secret=SECRET)


def make_client(settings) -> TestClient:
    return TestClient(create_app(settings))


def register(client: TestClient, email: str, password: str = "password123") -> dict:
    r = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def run_jobs(client: TestClient) -> None:
    state = client.app.state
    drain(state.engine, "w_test", HANDLERS, state.settings)


def upload(client: TestClient, token: str | None = None, *,
           rights: str = "user_owned") -> dict:
    headers = auth_header(token) if token else {}
    r = client.post("/api/v1/books",
                    files={"file": ("sample.txt", SAMPLE.read_bytes(), "text/plain")},
                    data={"rights_basis": rights}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- auth disabled by default

def test_routes_return_403_when_auth_disabled(settings) -> None:
    """Without AAB_JWT_SECRET, accounts are off — machine tokens keep working."""
    client = make_client(settings)
    assert client.get("/api/v1/health").json()["auth_required"] is False
    r = client.post("/api/v1/auth/register", json={"email": "a@b.com", "password": "password123"})
    assert r.status_code == 403
    assert r.json()["code"] == "auth_disabled"
    assert client.post("/api/v1/auth/login", json={"email": "a@b.com", "password": "x"}).status_code == 403


# ---------------------------------------------------------------- register / login / me

def test_register_first_user_is_admin_and_sets_cookie(auth_settings) -> None:
    client = make_client(auth_settings)
    body = register(client, "first@example.com")
    assert body["user"]["role"] == "admin"
    assert body["user"]["email"] == "first@example.com"
    assert "aab_refresh" in client.cookies
    assert body["access_token"]
    assert body["expires_in"] == 1800
    assert "refresh_token" not in body  # httpOnly cookie only


def test_second_user_is_regular_user(auth_settings) -> None:
    client = make_client(auth_settings)
    register(client, "first@example.com")
    second = register(client, "second@example.com")
    assert second["user"]["role"] == "user"


def test_duplicate_email_returns_409(auth_settings) -> None:
    client = make_client(auth_settings)
    register(client, "dup@example.com")
    r = client.post("/api/v1/auth/register",
                    json={"email": "DUP@example.com", "password": "password123"})
    assert r.status_code == 409
    assert r.json()["code"] == "conflict"


def test_weak_password_and_bad_email_return_422(auth_settings) -> None:
    client = make_client(auth_settings)
    assert client.post("/api/v1/auth/register",
                       json={"email": "a@b.com", "password": "short"}).status_code == 422
    assert client.post("/api/v1/auth/register",
                       json={"email": "not-an-email", "password": "password123"}).status_code == 422


def test_wrong_password_is_401(auth_settings) -> None:
    client = make_client(auth_settings)
    register(client, "login@example.com")
    r = client.post("/api/v1/auth/login",
                    json={"email": "login@example.com", "password": "wrongpass"})
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


def test_login_and_me(auth_settings) -> None:
    client = make_client(auth_settings)
    register(client, "me@example.com")
    r = client.post("/api/v1/auth/login",
                    json={"email": "me@example.com", "password": "password123"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers=auth_header(token))
    assert me.status_code == 200
    assert me.json()["email"] == "me@example.com"
    assert "password_hash" not in me.json()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_invalid_jwt_is_rejected(auth_settings) -> None:
    client = make_client(auth_settings)
    r = client.get("/api/v1/auth/me", headers=auth_header("not-a-jwt"))
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


# ---------------------------------------------------------------- refresh rotation

def test_refresh_rotates_and_old_token_is_rejected(auth_settings) -> None:
    client = make_client(auth_settings)
    register(client, "rotate@example.com")
    first = client.cookies.get("aab_refresh")
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 200
    second = client.cookies.get("aab_refresh")
    assert second != first
    assert r.json()["access_token"]

    # The rotated-out token can't be replayed. A fresh client avoids a stale cookie jar.
    replay_client = make_client(auth_settings)
    replay_client.cookies.set("aab_refresh", first)
    assert replay_client.post("/api/v1/auth/refresh").status_code == 401


def test_refresh_without_cookie_is_401(auth_settings) -> None:
    client = make_client(auth_settings)
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_revokes_session(auth_settings) -> None:
    client = make_client(auth_settings)
    register(client, "logout@example.com")
    token = client.cookies.get("aab_refresh")
    assert client.post("/api/v1/auth/logout").status_code == 204
    replay_client = make_client(auth_settings)
    replay_client.cookies.set("aab_refresh", token)
    assert replay_client.post("/api/v1/auth/refresh").status_code == 401


# ---------------------------------------------------------------- owner visibility matrix

def test_private_works_visible_to_owner_admin_and_not_others(auth_settings) -> None:
    alice = register(make_client(auth_settings), "alice@example.com")
    # Use one client with two token contexts; cookie jar belongs to the last login.
    client = make_client(auth_settings)
    alice = register(client, "alice2@example.com")
    alice_h = auth_header(alice["access_token"])
    bob = register(client, "bob@example.com")
    bob_h = auth_header(bob["access_token"])

    book = upload(client, alice["access_token"], rights="user_owned")
    bid = book["book_id"]

    assert client.get(f"/api/v1/books/{bid}", headers=alice_h).status_code == 200
    assert client.get(f"/api/v1/books/{bid}", headers=bob_h).status_code == 404
    assert client.get(f"/api/v1/books/{bid}").status_code == 404

    # Alice sees her own private work in the catalog; Bob doesn't; it's never public.
    alice_ids = {b["id"] for b in client.get("/api/v1/books", headers=alice_h).json()["items"]}
    bob_ids = {b["id"] for b in client.get("/api/v1/books", headers=bob_h).json()["items"]}
    anon_ids = {b["id"] for b in client.get("/api/v1/books").json()["items"]}
    assert bid in alice_ids and bid not in bob_ids and bid not in anon_ids

    # Operator admin token sees it too.
    with_admin = dataclasses.replace(auth_settings, admin_token="opsecret")
    admin_client = make_client(with_admin)
    assert admin_client.get(f"/api/v1/books/{bid}",
                            headers={"x-admin-token": "opsecret"}).status_code == 200


def test_shareable_work_is_public_even_when_owner_set(auth_settings) -> None:
    client = make_client(auth_settings)
    user = register(client, "public@example.com")
    book = upload(client, user["access_token"], rights="public_domain_us")
    assert client.get(f"/api/v1/books/{book['book_id']}").status_code == 200
    assert book["book_id"] in {b["id"] for b in client.get("/api/v1/books").json()["items"]}


def test_media_of_private_work_is_owner_only(auth_settings) -> None:
    client = make_client(auth_settings)
    user = register(client, "media@example.com")
    h = auth_header(user["access_token"])
    book = upload(client, user["access_token"], rights="user_owned")
    run_jobs(client)

    detail = client.get(f"/api/v1/books/{book['book_id']}", headers=h).json()
    chapter_id = detail["chapters"][0]["id"]
    r = client.post(f"/api/v1/chapters/{chapter_id}/audio", headers=h)
    assert r.status_code == 202, r.text
    run_jobs(client)
    manifest = client.get(f"/api/v1/chapters/{chapter_id}/audio", headers=h).json()
    url = manifest["master_url"]

    assert client.get(url, headers=h).status_code == 200
    assert client.get(url).status_code == 404


# ---------------------------------------------------------------- writes require login

def test_writes_require_login_when_auth_enabled(auth_settings) -> None:
    client = make_client(auth_settings)
    r = client.post("/api/v1/books", files={"file": ("s.txt", SAMPLE.read_bytes())})
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


def test_signed_in_user_can_upload(auth_settings) -> None:
    client = make_client(auth_settings)
    user = register(client, "writer@example.com")
    book = upload(client, user["access_token"])
    assert book["book_id"].startswith("bk_")


# ---------------------------------------------------------------- library

def test_library_add_list_remove(auth_settings) -> None:
    client = make_client(auth_settings)
    user = register(client, "shelf@example.com")
    h = auth_header(user["access_token"])
    book = upload(client, user["access_token"], rights="public_domain_us")
    bid = book["book_id"]

    assert client.get("/api/v1/library/", headers=h).json()["total"] == 0
    add = client.post(f"/api/v1/library/works/{bid}", headers=h)
    assert add.status_code == 201
    assert add.json()["work_id"] == bid
    # Idempotent.
    assert client.post(f"/api/v1/library/works/{bid}", headers=h).status_code == 201
    listed = client.get("/api/v1/library/", headers=h).json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == bid

    assert client.delete(f"/api/v1/library/works/{bid}", headers=h).status_code == 204
    assert client.get("/api/v1/library/", headers=h).json()["total"] == 0


def test_library_requires_login(auth_settings) -> None:
    client = make_client(auth_settings)
    assert client.get("/api/v1/library/").status_code == 401


# ---------------------------------------------------------------- progress

def test_progress_upsert_get_and_book_summary(auth_settings) -> None:
    client = make_client(auth_settings)
    user = register(client, "listen@example.com")
    h = auth_header(user["access_token"])
    book = upload(client, user["access_token"], rights="public_domain_us")
    run_jobs(client)
    detail = client.get(f"/api/v1/books/{book['book_id']}", headers=h).json()
    ch1, ch2 = [c["id"] for c in detail["chapters"]]

    r = client.put(f"/api/v1/library/progress/{ch1}", headers=h,
                   json={"position_ms": 12000, "duration_ms": 60000})
    assert r.status_code == 200
    assert r.json()["position_ms"] == 12000

    # Update, not duplicate.
    r = client.put(f"/api/v1/library/progress/{ch1}", headers=h,
                   json={"position_ms": 30000, "duration_ms": 60000})
    assert r.json()["position_ms"] == 30000
    got = client.get(f"/api/v1/library/progress/{ch1}", headers=h).json()
    assert got["position_ms"] == 30000

    assert client.get(f"/api/v1/library/progress/{ch2}", headers=h).json() is None
    summary = client.get(f"/api/v1/library/works/{book['book_id']}/progress", headers=h).json()
    assert summary["work_id"] == book["book_id"]
    assert summary["last"]["chapter_id"] == ch1
    assert len(summary["chapters"]) == 1


def test_progress_is_user_scoped(auth_settings) -> None:
    client = make_client(auth_settings)
    alice = register(client, "pa@example.com")
    bob = register(client, "pb@example.com")
    book = upload(client, alice["access_token"], rights="public_domain_us")
    run_jobs(client)
    ch = client.get(f"/api/v1/books/{book['book_id']}").json()["chapters"][0]["id"]

    client.put(f"/api/v1/library/progress/{ch}", headers=auth_header(alice["access_token"]),
               json={"position_ms": 5000})
    assert client.get(f"/api/v1/library/progress/{ch}",
                      headers=auth_header(bob["access_token"])).json() is None

"""Phase D contract tests: the admin management plane.

Admin is canonical v1 only. With no secrets configured the instance is single-operator and
admin routes are open; once auth is enabled they require the operator token or an admin
account. Every mutation must append an audit row in the same transaction.
"""

from __future__ import annotations

import dataclasses
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

import aab_db as db
from services.api.app import create_app

SAMPLE = Path(__file__).parent / "fixtures" / "sample.txt"
SECRET = "test-jwt-secret-at-least-32-bytes-long!!"
OP_TOKEN = "opsecret"


@pytest.fixture()
def auth_settings(settings):
    return dataclasses.replace(settings, jwt_secret=SECRET, admin_token=OP_TOKEN)


@pytest.fixture()
def open_settings(settings):
    return settings  # no secrets: single-operator instance


def make_client(settings) -> TestClient:
    return TestClient(create_app(settings))


def register(client: TestClient, email: str) -> dict:
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 201, r.text
    return r.json()


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def op_header() -> dict:
    return {"x-admin-token": OP_TOKEN}


def make_job(engine, *, state: str = "queued", kind: str = "ingest") -> str:
    with engine.begin() as conn:
        jid, _ = db.enqueue(conn, kind=kind, target_type="work", target_id="bk_test",
                            idempotency_key=f"admin-test-{uuid.uuid4()}")
        if state == "failed":
            db.fail_job(conn, jid, code="boom", message="boom", retryable=False)
        elif state == "running":
            assert db.claim_job(conn, "w_test") is not None
        elif state in {"dead", "cancelled"}:
            conn.execute(update(db.jobs).where(db.jobs.c.id == jid).values(state=state))
    return jid


def actions(engine) -> list[dict]:
    with engine.connect() as conn:
        return db.list_admin_actions(conn, limit=50)


def upload(client: TestClient, token: str, *, rights: str = "user_owned") -> str:
    r = client.post("/api/v1/books",
                    files={"file": ("sample.txt", SAMPLE.read_bytes(), "text/plain")},
                    data={"rights_basis": rights}, headers=auth_header(token))
    assert r.status_code == 201, r.text
    return r.json()["book_id"]


# ---------------------------------------------------------------- authorisation gate

def test_admin_gate_matrix(auth_settings) -> None:
    client = make_client(auth_settings)
    anon = client.get("/api/v1/admin/overview")
    assert anon.status_code == 401
    assert anon.json()["code"] == "unauthorized"

    first = register(client, "first@example.com")
    assert first["user"]["role"] == "admin"
    assert client.get("/api/v1/admin/overview",
                      headers=auth_header(first["access_token"])).status_code == 200

    user = register(client, "regular@example.com")
    assert user["user"]["role"] == "user"
    assert client.get("/api/v1/admin/overview",
                      headers=auth_header(user["access_token"])).status_code == 401
    assert client.get("/api/v1/admin/overview", headers=op_header()).status_code == 200


def test_single_operator_instance_has_open_admin(settings) -> None:
    client = make_client(settings)
    assert client.get("/api/v1/admin/overview").status_code == 200
    assert client.get("/api/v1/admin/jobs").status_code == 200


def test_all_admin_routes_share_the_gate(auth_settings) -> None:
    client = make_client(auth_settings)
    paths = [
        ("get", "/api/v1/admin/overview"),
        ("get", "/api/v1/admin/jobs"),
        ("get", "/api/v1/admin/jobs/job_x"),
        ("post", "/api/v1/admin/jobs/job_x/retry"),
        ("post", "/api/v1/admin/jobs/job_x/cancel"),
        ("get", "/api/v1/admin/works"),
        ("patch", "/api/v1/admin/works/bk_x"),
        ("get", "/api/v1/admin/flags"),
        ("put", "/api/v1/admin/flags/k"),
        ("delete", "/api/v1/admin/flags/k"),
        ("get", "/api/v1/admin/providers"),
    ]
    for method, path in paths:
        body = {"json": {}} if method in {"post", "patch", "put"} else {}
        r = getattr(client, method)(path, **body)
        assert r.status_code == 401, (method, path, r.status_code, r.text)


# ---------------------------------------------------------------- jobs

def test_admin_job_list_filters_and_detail(settings) -> None:
    client = make_client(settings)
    engine = client.app.state.engine
    make_job(engine, state="failed", kind="ingest")
    make_job(engine, state="queued", kind="render")

    all_jobs = client.get("/api/v1/admin/jobs").json()
    assert all_jobs["total"] == 2
    assert all_jobs["limit"] == 50 and all_jobs["offset"] == 0
    assert {j["kind"] for j in all_jobs["items"]} == {"ingest", "render"}

    queued = client.get("/api/v1/admin/jobs", params={"state": "queued"}).json()
    assert queued["total"] == 1
    assert queued["items"][0]["state"] == "queued"

    kind = client.get("/api/v1/admin/jobs", params={"kind": "render"}).json()
    assert kind["total"] == 1

    page = client.get("/api/v1/admin/jobs", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 2 and len(page["items"]) == 1

    jid = all_jobs["items"][0]["id"]
    detail = client.get(f"/api/v1/admin/jobs/{jid}").json()
    assert detail["job"]["id"] == jid
    assert {e["event"] for e in detail["events"]} >= {"queued"}


def test_admin_retry_resets_job_and_appends_audit(settings) -> None:
    client = make_client(settings)
    engine = client.app.state.engine
    jid = make_job(engine, state="failed")
    with engine.begin() as conn:
        conn.execute(update(db.jobs).where(db.jobs.c.id == jid).values(
            attempts=2, error={"code": "boom", "message": "boom"}, progress=5,
            lease_owner="w_dead", lease_expires_at=db.utcnow()))

    r = client.post(f"/api/v1/admin/jobs/{jid}/retry", json={"reason": "incident fixed"})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["state"] == "queued"
    assert job["attempts"] == 0
    assert job["error"] is None
    assert job["progress"] == 0
    assert job["lease_owner"] is None

    with engine.connect() as conn:
        events = db.job_timeline(conn, jid)
        state = db.get_job(conn, jid)["state"]
    assert state == "queued"
    assert any(e["event"] == "admin_retry" and e["detail"]["from"] == "failed"
               for e in events)

    trail = actions(engine)
    assert len(trail) == 1
    assert trail[0]["action"] == "job.retry"
    assert trail[0]["target_id"] == jid
    assert trail[0]["before"] == {"state": "failed"}
    assert trail[0]["after"] == {"state": "queued"}
    assert trail[0]["reason"] == "incident fixed"
    assert trail[0]["actor"] == "operator"


def test_admin_cancel_non_running_job(settings) -> None:
    client = make_client(settings)
    engine = client.app.state.engine
    jid = make_job(engine, state="queued")

    r = client.post(f"/api/v1/admin/jobs/{jid}/cancel")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "cancelled"

    with engine.connect() as conn:
        events = db.job_timeline(conn, jid)
    assert any(e["event"] == "admin_cancel" and e["detail"]["from"] == "queued"
               for e in events)
    assert actions(engine)[0]["action"] == "job.cancel"


@pytest.mark.parametrize(
    "setup_state,action,message",
    [
        ("queued", "retry", "only failed, cancelled or dead jobs can be retried"),
        ("succeeded", "cancel", "only queued, failed or dead jobs can be cancelled"),
        ("running", "cancel", "only queued, failed or dead jobs can be cancelled"),
    ],
)
def test_admin_job_conflicts(settings, setup_state, action, message) -> None:
    client = make_client(settings)
    engine = client.app.state.engine
    if setup_state == "succeeded":
        jid = make_job(engine)
        with engine.begin() as conn:
            conn.execute(update(db.jobs).where(db.jobs.c.id == jid).values(state="succeeded"))
    else:
        jid = make_job(engine, state=setup_state)

    r = client.post(f"/api/v1/admin/jobs/{jid}/{action}")
    assert r.status_code == 409
    assert r.json()["code"] == "conflict"
    assert r.json()["message"] == message
    assert actions(engine) == []


def test_admin_job_missing_is_404(settings) -> None:
    client = make_client(settings)
    assert client.get("/api/v1/admin/jobs/job_missing").status_code == 404
    assert client.post("/api/v1/admin/jobs/job_missing/retry").status_code == 404


# ---------------------------------------------------------------- works

def test_admin_works_include_private_books_and_audit_updates(auth_settings) -> None:
    client = make_client(auth_settings)
    user = register(client, "owner@example.com")
    bid = upload(client, user["access_token"], rights="user_owned")

    # Private works are invisible to anonymous users but present in the admin catalogue.
    assert client.get(f"/api/v1/books/{bid}").status_code == 404
    admin = client.get("/api/v1/admin/works", headers=op_header())
    assert admin.status_code == 200
    body = admin.json()
    assert body["total"] == 1
    work = body["items"][0]
    assert work["id"] == bid
    assert work["shareable"] is False
    assert work["owner_id"].startswith("usr_")
    assert work["chapters"] >= 0

    r = client.patch(f"/api/v1/admin/works/{bid}", headers=op_header(),
                     json={"shareable": True, "status": "ready",
                           "reason": "rights confirmed"})
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["shareable"] is True
    assert updated["status"] == "ready"

    # The change takes effect through the normal public visibility path.
    assert client.get(f"/api/v1/books/{bid}").status_code == 200

    trail = actions(client.app.state.engine)
    assert len(trail) == 1
    assert trail[0]["action"] == "work.update"
    assert trail[0]["before"] == {"shareable": False, "status": "new"}
    assert trail[0]["after"] == {"shareable": True, "status": "ready"}
    assert trail[0]["reason"] == "rights confirmed"
    assert trail[0]["actor"] == "operator"


def test_admin_work_update_missing_is_404(settings) -> None:
    client = make_client(settings)
    r = client.patch("/api/v1/admin/works/bk_missing", json={"shareable": True})
    assert r.status_code == 404
    assert actions(client.app.state.engine) == []


# ---------------------------------------------------------------- feature flags

def test_admin_flag_crud_and_audit(settings) -> None:
    client = make_client(settings)

    assert client.get("/api/v1/admin/flags").json() == []

    created = client.put("/api/v1/admin/flags/tts.enabled",
                         json={"value": {"enabled": False}, "reason": "incident"})
    assert created.status_code == 200, created.text
    assert created.json()["key"] == "tts.enabled"
    assert created.json()["value"] == {"enabled": False}

    updated = client.put("/api/v1/admin/flags/tts.enabled", json={"value": {"enabled": True}})
    assert updated.json()["value"] == {"enabled": True}

    flags = client.get("/api/v1/admin/flags").json()
    assert len(flags) == 1
    assert flags[0] == updated.json()

    assert client.delete("/api/v1/admin/flags/tts.enabled",
                         params={"reason": "done"}).status_code == 204
    assert client.get("/api/v1/admin/flags").json() == []
    assert client.delete("/api/v1/admin/flags/tts.enabled").status_code == 404

    trail = list(reversed(actions(client.app.state.engine)))  # newest first in storage
    assert [a["action"] for a in trail] == ["flag.set", "flag.set", "flag.delete"]
    assert trail[0]["before"] == {"value": None}
    assert trail[0]["after"] == {"value": {"enabled": False}}
    assert trail[1]["before"] == {"value": {"enabled": False}}
    assert trail[1]["reason"] is None
    assert trail[2]["before"] is None


# ---------------------------------------------------------------- providers / overview

def test_admin_providers_are_read_only(settings) -> None:
    client = make_client(settings)
    r = client.get("/api/v1/admin/providers")
    assert r.status_code == 200, r.text
    providers = r.json()
    assert providers
    assert any(p["active"] for p in providers)
    assert all({"id", "model_id", "model_version", "capabilities", "presets"} <= set(p)
               for p in providers)
    assert client.post("/api/v1/admin/providers", json={}).status_code == 405


def test_admin_overview_reports_counts_and_recent_actions(auth_settings) -> None:
    client = make_client(auth_settings)
    engine = client.app.state.engine
    user = register(client, "count@example.com")
    upload(client, user["access_token"], rights="user_owned")
    jid = make_job(engine, state="failed")
    client.post(f"/api/v1/admin/jobs/{jid}/retry", headers=op_header())

    r = client.get("/api/v1/admin/overview", headers=op_header())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["users"] == 1
    assert body["queue"].get("queued", 0) >= 1
    assert body["jobs_by_state"].get("queued", 0) >= 1
    assert body["works_by_status"].get("new", 0) == 1
    assert body["provider"]["active"] is True
    assert len(body["recent_actions"]) == 1
    assert body["recent_actions"][0]["action"] == "job.retry"

"""HTTP API contract tests.

These lock the behavior the restructure had to preserve: upload → ingest → 202 → 200
manifest → range delivery, the error envelope, the privacy predicate, and both API prefixes.
The worker is driven in-process with ``aab_jobs.drain``; speech is the fake provider.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

import aab_db as db
from aab_jobs import drain
from services.api.app import create_app
from services.worker.worker.main import HANDLERS

SAMPLE = Path(__file__).parent / "fixtures" / "sample.txt"


def make_client(settings) -> TestClient:
    return TestClient(create_app(settings))


def run_jobs(client: TestClient) -> None:
    state = client.app.state
    drain(state.engine, "w_test", HANDLERS, state.settings)


def upload(client: TestClient, *, title: str = "Smoke Book",
           rights: str = "public_domain_us", headers: dict | None = None) -> dict:
    response = client.post(
        "/api/v1/books",
        files={"file": ("sample.txt", SAMPLE.read_bytes(), "text/plain")},
        data={"title": title, "rights_basis": rights},
        headers=headers or {},
    )
    assert response.status_code == 201, response.text
    return response.json()


def first_chapter(client: TestClient, book_id: str,
                  headers: dict | None = None) -> str:
    detail = client.get(f"/api/v1/books/{book_id}", headers=headers or {}).json()
    return detail["chapters"][0]["id"]


def render_chapter(client: TestClient, chapter_id: str,
                   headers: dict | None = None) -> None:
    response = client.post(f"/api/v1/chapters/{chapter_id}/audio", headers=headers or {})
    assert response.status_code == 202, response.text
    run_jobs(client)


def upload_job_id(client: TestClient, book_id: str) -> str:
    with client.app.state.engine.connect() as conn:
        revision = conn.execute(
            sa.select(db.revisions.c.id).where(db.revisions.c.work_id == book_id)
            .order_by(db.revisions.c.created_at.desc()).limit(1)
        ).scalar_one()
        job = conn.execute(
            sa.select(db.jobs.c.id).where(db.jobs.c.target_id == revision)
            .order_by(db.jobs.c.created_at.desc()).limit(1)
        ).scalar_one()
    return job


# ---------------------------------------------------------------- meta

def test_health_open_instance(settings) -> None:
    client = make_client(settings)
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["provider"] == "fake-formant"
    assert body["speech"] == "local"
    assert body["auth_required"] is False
    assert isinstance(body["queue"], dict)


def test_legacy_alias_paths(settings) -> None:
    client = make_client(settings)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health").json()["status"] == "ok"


# ---------------------------------------------------------------- upload and catalogue

def test_upload_creates_book_and_ingests(settings) -> None:
    client = make_client(settings)
    result = upload(client)
    assert result["book_id"].startswith("bk_")
    assert result["revision_id"].startswith("rev_")
    assert result["job_id"].startswith("job_")

    run_jobs(client)
    detail = client.get(f"/api/v1/books/{result['book_id']}").json()
    assert detail["work"]["status"] == "ready"
    assert [c["title"] for c in detail["chapters"]] == ["Chapter I", "Chapter II"]
    assert any(member["name"] == "Narrator" for member in detail["cast"])
    assert {c["status"] for c in detail["chapters"]} == {"not_started"}
    assert {"id", "ordinal", "title", "word_count", "status", "progress", "total"} == \
        set(detail["chapters"][0])


def test_v1_catalogue_is_paginated_legacy_is_bare(settings) -> None:
    client = make_client(settings)
    upload(client, title="Book A")
    upload(client, title="Book B")

    page = client.get("/api/v1/books?limit=1&offset=1").json()
    assert page["total"] == 2
    assert page["limit"] == 1
    assert page["offset"] == 1
    assert len(page["items"]) == 1
    assert {"id", "title", "author", "language", "status", "chapters"} == \
        set(page["items"][0])

    legacy = client.get("/api/books").json()
    assert isinstance(legacy, list) and len(legacy) == 2
    assert {"id", "title", "author", "language", "status", "chapters"} == set(legacy[0])
    assert {b["title"] for b in legacy} == {"Book A", "Book B"}


def test_upload_rejects_unsupported_format_with_envelope(settings) -> None:
    client = make_client(settings)
    response = client.post(
        "/api/v1/books",
        files={"file": ("book.pdf", b"%PDF-1.7 fake", "application/pdf")},
        data={"title": "Nope"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_input"
    assert "pdf" in body["message"].lower()


def test_upload_rejects_oversize(settings) -> None:
    client = make_client(settings)
    big = b"x" * (25 * 1024 * 1024 + 1)
    response = client.post(
        "/api/v1/books",
        files={"file": ("big.txt", big, "text/plain")},
        data={"title": "Big"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_input"


def test_empty_upload_fails_ingest_visibly(settings) -> None:
    client = make_client(settings)
    result = client.post(
        "/api/v1/books",
        files={"file": ("empty.txt", b"   \n\n  ", "text/plain")},
        data={"title": "Empty"},
    )
    assert result.status_code == 201
    book_id = result.json()["book_id"]

    run_jobs(client)
    detail = client.get(f"/api/v1/books/{book_id}").json()
    assert detail["work"]["status"] == "failed"
    assert detail["chapters"] == []

    job = client.get(f"/api/v1/jobs/{upload_job_id(client, book_id)}").json()
    assert job["state"] == "failed"
    assert job["error"]["code"] == "invalid_input"


def test_upload_rejects_no_file(settings) -> None:
    client = make_client(settings)
    response = client.post("/api/v1/books", data={"title": "No file"})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


# ---------------------------------------------------------------- render flow

def test_request_render_poll_render_download(settings) -> None:
    client = make_client(settings)
    book_id = upload(client)["book_id"]
    run_jobs(client)
    chapter_id = first_chapter(client, book_id)

    first = client.post(f"/api/v1/chapters/{chapter_id}/audio")
    assert first.status_code == 202
    assert first.json()["status"] == "queued"

    run_jobs(client)

    # A second request for a ready chapter re-renders nothing and reports readiness.
    again = client.post(f"/api/v1/chapters/{chapter_id}/audio")
    assert again.status_code == 202
    assert again.json()["status"] == "ready"

    manifest_response = client.get(f"/api/v1/chapters/{chapter_id}/audio")
    assert manifest_response.status_code == 200
    manifest = manifest_response.json()
    assert manifest["complete"] is True
    assert manifest["segment_count"] == manifest["rendered_count"] > 0
    assert manifest["master_url"].startswith("/media/")
    assert all(s["render_key"].startswith("rk1:") for s in manifest["segments"])
    assert {"Elizabeth", "Darcy"} <= {s["speaker"] for s in manifest["segments"]}


def test_pending_chapter_returns_202(settings) -> None:
    client = make_client(settings)
    book_id = upload(client)["book_id"]
    run_jobs(client)
    second = client.get(f"/api/v1/books/{book_id}").json()["chapters"][1]["id"]

    pending = client.get(f"/api/v1/chapters/{second}/audio")
    assert pending.status_code == 202
    body = pending.json()
    assert body["status"] == "not_started"
    assert body["progress"] == 0


def test_audio_delivery_with_ranges(settings) -> None:
    client = make_client(settings)
    book_id = upload(client)["book_id"]
    run_jobs(client)
    chapter_id = first_chapter(client, book_id)
    render_chapter(client, chapter_id)

    manifest = client.get(f"/api/v1/chapters/{chapter_id}/audio").json()
    url = manifest["master_url"]

    full = client.get(url)
    assert full.status_code == 200
    assert len(full.content) > 1000

    partial = client.get(url, headers={"Range": "bytes=1000-2999"})
    assert partial.status_code == 206
    assert partial.headers["content-range"] == f"bytes 1000-2999/{len(full.content)}"
    assert len(partial.content) == 2000

    bad = client.get(url, headers={"Range": "bytes=999999-"})
    assert bad.status_code == 416
    assert bad.json()["code"] == "range_not_satisfiable"


def test_unknown_chapter_is_404_on_both_verbs(settings) -> None:
    client = make_client(settings)
    assert client.post("/api/v1/chapters/ch_does_not_exist/audio").status_code == 404
    assert client.get("/api/v1/chapters/ch_does_not_exist/audio").status_code == 404


def test_unknown_book_and_job_are_404(settings) -> None:
    client = make_client(settings)
    assert client.get("/api/v1/books/bk_missing").status_code == 404
    assert client.get("/api/v1/jobs/job_missing").status_code == 404


def test_generate_book_enqueues_every_chapter(settings) -> None:
    client = make_client(settings)
    book_id = upload(client)["book_id"]
    run_jobs(client)

    response = client.post(f"/api/v1/books/{book_id}/generate")
    assert response.status_code == 202
    body = response.json()
    assert body["chapters"] == 2
    assert body["jobs_created"] == 2

    # Idempotent: a second generate creates no new jobs.
    again = client.post(f"/api/v1/books/{book_id}/generate").json()
    assert again["jobs_created"] == 0

    run_jobs(client)
    detail = client.get(f"/api/v1/books/{book_id}").json()
    assert {c["status"] for c in detail["chapters"]} == {"ready"}


# ---------------------------------------------------------------- auth and privacy

@pytest.fixture()
def token_settings(settings):
    return dataclasses.replace(settings, admin_token="secret")


def test_token_instance_rejects_anonymous_writes(token_settings) -> None:
    client = make_client(token_settings)
    assert client.get("/api/v1/health").json()["auth_required"] is True

    no_token = client.post("/api/v1/books",
                           files={"file": ("s.txt", SAMPLE.read_bytes())})
    assert no_token.status_code == 401
    assert no_token.json()["code"] == "unauthorized"

    bad_token = client.post("/api/v1/books", headers={"x-admin-token": "nope"},
                            files={"file": ("s.txt", SAMPLE.read_bytes())})
    assert bad_token.status_code == 401

    bearer = client.post("/api/v1/books", headers={"Authorization": "Bearer secret"},
                         files={"file": ("s.txt", SAMPLE.read_bytes(), "text/plain")},
                         data={"title": "Via bearer"})
    assert bearer.status_code == 201


def test_private_work_is_invisible_to_anonymous_callers(token_settings) -> None:
    client = make_client(token_settings)
    admin = {"x-admin-token": "secret"}
    public = upload(client, title="Public Book", rights="public_domain_us", headers=admin)
    private = upload(client, title="Private Draft", rights="user_owned", headers=admin)
    run_jobs(client)

    anon_catalogue = client.get("/api/v1/books").json()
    assert [b["id"] for b in anon_catalogue["items"]] == [public["book_id"]]
    admin_catalogue = client.get("/api/v1/books", headers=admin).json()
    assert len(admin_catalogue["items"]) == 2

    assert client.get(f"/api/v1/books/{private['book_id']}").status_code == 404
    assert client.get(f"/api/v1/books/{private['book_id']}",
                      headers=admin).status_code == 200

    # Render the private chapter as admin, then check its bytes are still hidden.
    chapter_id = first_chapter(client, private["book_id"], headers=admin)
    client.post(f"/api/v1/chapters/{chapter_id}/audio", headers=admin)
    run_jobs(client)
    manifest = client.get(f"/api/v1/chapters/{chapter_id}/audio", headers=admin).json()

    assert client.get(manifest["master_url"]).status_code == 404
    assert client.get(manifest["master_url"] + "?token=wrong").status_code == 404
    assert client.get(manifest["master_url"] + "?token=secret").status_code == 200
    assert client.get(manifest["master_url"], headers=admin).status_code == 200

    # A public work's audio is playable without any token.
    public_chapter = first_chapter(client, public["book_id"], headers=admin)
    render_chapter(client, public_chapter, headers=admin)
    public_manifest = client.get(f"/api/v1/chapters/{public_chapter}/audio",
                                 headers=admin).json()
    assert client.get(public_manifest["master_url"]).status_code == 200


def test_private_manifest_and_progress_are_hidden(token_settings) -> None:
    client = make_client(token_settings)
    admin = {"x-admin-token": "secret"}
    private = upload(client, title="Private Draft", rights="user_owned", headers=admin)
    run_jobs(client)
    chapter_id = first_chapter(client, private["book_id"], headers=admin)

    assert client.post(f"/api/v1/chapters/{chapter_id}/audio").status_code == 401
    assert client.get(f"/api/v1/chapters/{chapter_id}/audio").status_code == 404
    assert client.get(f"/api/v1/chapters/{chapter_id}/audio",
                      headers=admin).status_code == 202


def test_segments_and_uploads_are_operator_only(token_settings) -> None:
    client = make_client(token_settings)
    admin = {"x-admin-token": "secret"}
    book_id = upload(client, title="Public Book", rights="public_domain_us",
                     headers=admin)["book_id"]
    run_jobs(client)
    render_chapter(client, first_chapter(client, book_id, headers=admin), headers=admin)

    with client.app.state.engine.connect() as conn:
        row = conn.execute(
            sa.select(db.assets.c.path).where(db.assets.c.kind == "audio_segment").limit(1)
        ).scalar_one()
    segment_url = "/media/" + row
    assert client.get(segment_url).status_code == 404
    assert client.get(segment_url + "?token=secret").status_code == 200


def test_media_traversal_is_blocked(settings) -> None:
    client = make_client(settings)
    escaped = settings.media_dir.parent / "secret.txt"
    escaped.write_text("private")
    try:
        response = client.get("/media/../secret.txt")
        assert response.status_code in {404, 400}   # rejected or normalised away
    finally:
        escaped.unlink(missing_ok=True)


# ---------------------------------------------------------------- web

def test_index_serves_player(settings) -> None:
    client = make_client(settings)
    response = client.get("/")
    assert response.status_code == 200
    assert "Open Audio Book" in response.text

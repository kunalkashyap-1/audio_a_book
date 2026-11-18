"""Database schema — SQLAlchemy Core, portable between SQLite and PostgreSQL.

The MVP ships one schema namespace. PostgreSQL schema-level tenancy separation
(shared/private/ops) is a defence-in-depth measure that returns when the backend moves to
Postgres; until then tenancy is enforced in the repository layer and tested there.
"""

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

users = sa.Table(
    "users", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("email", sa.String(320), nullable=False, unique=True),
    sa.Column("password_hash", sa.String(200), nullable=False),
    sa.Column("role", sa.String(20), nullable=False, server_default="user"),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

works = sa.Table(
    "works", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("title", sa.String(500), nullable=False),
    sa.Column("author", sa.String(300)),
    sa.Column("language", sa.String(12), nullable=False, server_default="en"),
    sa.Column("rights_basis", sa.String(40), nullable=False, server_default="public_domain_us"),
    sa.Column("shareable", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.Column("owner_id", sa.String(40)),
    sa.Column("status", sa.String(20), nullable=False, server_default="new"),
    sa.Column("description", sa.Text),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

editions = sa.Table(
    "editions", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("work_id", sa.String(40), sa.ForeignKey("works.id"), nullable=False),
    sa.Column("source", sa.String(40), nullable=False, server_default="upload"),
    sa.Column("external_id", sa.String(120)),
    sa.Column("language", sa.String(12), nullable=False, server_default="en"),
)

revisions = sa.Table(
    "revisions", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("work_id", sa.String(40), sa.ForeignKey("works.id"), nullable=False),
    sa.Column("edition_id", sa.String(40), sa.ForeignKey("editions.id")),
    sa.Column("source_path", sa.String(500), nullable=False),
    sa.Column("text_sha256", sa.String(64)),
    sa.Column("parser_version", sa.String(40), nullable=False, server_default="ingest-0.1"),
    sa.Column("language", sa.String(12), nullable=False, server_default="en"),
    sa.Column("word_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
    sa.Column("error", sa.Text),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

chapters = sa.Table(
    "chapters", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("revision_id", sa.String(40), sa.ForeignKey("revisions.id"), nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("title", sa.String(300)),
    sa.Column("char_start", sa.Integer, nullable=False, server_default="0"),
    sa.Column("char_end", sa.Integer, nullable=False, server_default="0"),
    sa.Column("word_count", sa.Integer, nullable=False, server_default="0"),
    sa.UniqueConstraint("revision_id", "ordinal", name="uq_chapter_ordinal"),
)

blocks = sa.Table(
    "blocks", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("chapter_id", sa.String(40), sa.ForeignKey("chapters.id"), nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("kind", sa.String(20), nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("text_hash", sa.String(64), nullable=False),
    sa.UniqueConstraint("chapter_id", "ordinal", name="uq_block_ordinal"),
)

characters = sa.Table(
    "characters", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("work_id", sa.String(40), sa.ForeignKey("works.id"), nullable=False),
    sa.Column("canonical_name", sa.String(200), nullable=False),
    sa.Column("role", sa.String(60)),
    sa.Column("description", sa.Text),
    sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
    sa.Column("status", sa.String(20), nullable=False, server_default="auto"),
    sa.UniqueConstraint("work_id", "canonical_name", name="uq_character_name"),
)

voice_profiles = sa.Table(
    "voice_profiles", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("scope", sa.String(10), nullable=False, server_default="system"),
    sa.Column("owner_id", sa.String(40)),
    sa.Column("character_id", sa.String(40), sa.ForeignKey("characters.id")),
    sa.Column("work_id", sa.String(40), sa.ForeignKey("works.id")),
    sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
    sa.Column("source_type", sa.String(20), nullable=False, server_default="preset"),
    sa.Column("reference_path", sa.String(500)),
    sa.Column("preset_id", sa.String(80)),
    sa.Column("model_family", sa.String(80), nullable=False),
    sa.Column("params", sa.JSON, nullable=False, server_default="{}"),
    sa.Column("persona", sa.JSON, nullable=False, server_default="{}"),
    sa.Column("locked", sa.Boolean, nullable=False, server_default=sa.false()),
)

narration_segments = sa.Table(
    "narration_segments", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("revision_id", sa.String(40), sa.ForeignKey("revisions.id"), nullable=False),
    sa.Column("chapter_id", sa.String(40), sa.ForeignKey("chapters.id"), nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("kind", sa.String(20), nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("text_hash", sa.String(64), nullable=False),
    sa.Column("phon_hash", sa.String(64), nullable=False),
    sa.Column("language", sa.String(12), nullable=False, server_default="en"),
    sa.Column("speaker_kind", sa.String(20), nullable=False),
    sa.Column("character_id", sa.String(40), sa.ForeignKey("characters.id")),
    sa.Column("char_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("gap_after_ms", sa.Integer, nullable=False, server_default="120"),
    sa.UniqueConstraint("chapter_id", "ordinal", name="uq_segment_ordinal"),
)

performance_directives = sa.Table(
    "performance_directives", metadata,
    sa.Column("segment_id", sa.String(40), sa.ForeignKey("narration_segments.id"),
              primary_key=True),
    sa.Column("emotion", sa.String(20), nullable=False, server_default="neutral"),
    sa.Column("intensity", sa.Integer, nullable=False, server_default="1"),
    sa.Column("pace", sa.String(10), nullable=False, server_default="normal"),
    sa.Column("style", sa.String(20), nullable=False, server_default="plain"),
    sa.Column("source", sa.String(20), nullable=False, server_default="rules"),
    sa.Column("confidence", sa.Float, nullable=False, server_default="1"),
)

render_sets = sa.Table(
    "render_sets", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("chapter_id", sa.String(40), sa.ForeignKey("chapters.id"), nullable=False),
    sa.Column("revision_id", sa.String(40), sa.ForeignKey("revisions.id"), nullable=False),
    sa.Column("scope", sa.String(10), nullable=False, server_default="system"),
    sa.Column("owner_id", sa.String(40)),
    sa.Column("policy_version", sa.String(40), nullable=False),
    sa.Column("model_family", sa.String(80), nullable=False),
    sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
    sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
    sa.Column("total", sa.Integer, nullable=False, server_default="0"),
    sa.Column("job_id", sa.String(40)),
    sa.Column("master_path", sa.String(500)),
    sa.Column("manifest_path", sa.String(500)),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.UniqueConstraint("chapter_id", "policy_version", "model_family", name="uq_render_set"),
)

assets = sa.Table(
    "assets", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("kind", sa.String(30), nullable=False),
    sa.Column("path", sa.String(500), nullable=False, unique=True),
    sa.Column("sha256", sa.String(64), nullable=False),
    sa.Column("bytes", sa.Integer, nullable=False),
    sa.Column("mime", sa.String(80), nullable=False),
    sa.Column("duration_ms", sa.Integer),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

audio_renders = sa.Table(
    "audio_renders", metadata,
    sa.Column("render_key", sa.String(80), primary_key=True),
    sa.Column("segment_id", sa.String(40), sa.ForeignKey("narration_segments.id"),
              nullable=False),
    sa.Column("asset_id", sa.String(40), sa.ForeignKey("assets.id"), nullable=False),
    sa.Column("voice_profile_id", sa.String(40), nullable=False),
    sa.Column("voice_profile_rev", sa.Integer, nullable=False),
    sa.Column("model_id", sa.String(80), nullable=False),
    sa.Column("model_version", sa.String(40), nullable=False),
    sa.Column("render_set_id", sa.String(40), nullable=False),
    sa.Column("duration_ms", sa.Integer, nullable=False),
    sa.Column("qc_status", sa.String(20), nullable=False, server_default="passed"),
    sa.Column("generated_by", sa.String(20), nullable=False, server_default="system"),
    sa.Column("shareable", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Index("ix_render_segment", "segment_id"),
    sa.Index("ix_render_set", "render_set_id"),
)

jobs = sa.Table(
    "jobs", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("kind", sa.String(40), nullable=False),
    sa.Column("target_type", sa.String(40), nullable=False),
    sa.Column("target_id", sa.String(40), nullable=False),
    sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
    sa.Column("state", sa.String(20), nullable=False, server_default="queued"),
    sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
    sa.Column("lease_owner", sa.String(40)),
    sa.Column("lease_expires_at", sa.DateTime),
    sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
    sa.Column("total", sa.Integer, nullable=False, server_default="0"),
    sa.Column("error", sa.JSON),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Column("updated_at", sa.DateTime, nullable=False),
    sa.Index("ix_jobs_claim", "state", "priority", "created_at"),
)

job_events = sa.Table(
    "job_events", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("job_id", sa.String(40), sa.ForeignKey("jobs.id"), nullable=False),
    sa.Column("event", sa.String(40), nullable=False),
    sa.Column("detail", sa.JSON),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

render_claims = sa.Table(
    "render_claims", metadata,
    sa.Column("render_key", sa.String(80), primary_key=True),
    sa.Column("job_id", sa.String(40), nullable=False),
    sa.Column("expires_at", sa.DateTime, nullable=False),
)

uploads = sa.Table(
    "uploads", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("filename", sa.String(300), nullable=False),
    sa.Column("path", sa.String(500), nullable=False),
    sa.Column("size", sa.Integer, nullable=False, server_default="0"),
    sa.Column("status", sa.String(20), nullable=False, server_default="received"),
    sa.Column("work_id", sa.String(40), sa.ForeignKey("works.id")),
    sa.Column("error", sa.Text),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

config_versions = sa.Table(
    "config_versions", metadata,
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("actor_id", sa.String(80), nullable=False),
    sa.Column("note", sa.String(500)),
    sa.Column("data", sa.JSON),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

feature_flags = sa.Table(
    "feature_flags", metadata,
    sa.Column("key", sa.String(80), primary_key=True),
    sa.Column("value", sa.JSON, nullable=False),
    sa.Column("updated_at", sa.DateTime, nullable=False),
)

admin_audit = sa.Table(
    "admin_audit", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("actor", sa.String(120), nullable=False),
    sa.Column("action", sa.String(60), nullable=False),
    sa.Column("target_type", sa.String(40), nullable=False),
    sa.Column("target_id", sa.String(80), nullable=False),
    sa.Column("before", sa.JSON),
    sa.Column("after", sa.JSON),
    sa.Column("reason", sa.String(500)),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Index("ix_admin_audit_created", "created_at"),
)

sessions = sa.Table(
    "sessions", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
    sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
    sa.Column("expires_at", sa.DateTime, nullable=False),
    sa.Column("revoked_at", sa.DateTime),
    sa.Column("created_at", sa.DateTime, nullable=False),
)

library_entries = sa.Table(
    "library_entries", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
    sa.Column("work_id", sa.String(40), sa.ForeignKey("works.id"), nullable=False),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.UniqueConstraint("user_id", "work_id", name="uq_library_user_work"),
)

playback_progress = sa.Table(
    "playback_progress", metadata,
    sa.Column("id", sa.String(40), primary_key=True),
    sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
    sa.Column("work_id", sa.String(40), sa.ForeignKey("works.id"), nullable=False),
    sa.Column("chapter_id", sa.String(40), sa.ForeignKey("chapters.id"), nullable=False),
    sa.Column("position_ms", sa.Integer, nullable=False, server_default="0"),
    sa.Column("duration_ms", sa.Integer),
    sa.Column("updated_at", sa.DateTime, nullable=False),
    sa.UniqueConstraint("user_id", "chapter_id", name="uq_progress_user_chapter"),
)

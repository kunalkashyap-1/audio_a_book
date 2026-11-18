#!/usr/bin/env python
"""Import a book without the HTTP API and render its first chapter.

    python scripts/import_book.py path/to/book.epub --title "..." --chapter 1

Runs the real worker handlers, so it exercises exactly the production path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aab_core import Settings, new_id  # noqa: E402
import aab_db as db  # noqa: E402
from aab_jobs import drain  # noqa: E402
from aab_tts import POLICY_VERSION  # noqa: E402
from services.worker.worker.jobs.common import get_provider  # noqa: E402
from services.worker.worker.main import HANDLERS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("--title")
    parser.add_argument("--author")
    parser.add_argument("--language", default="en")
    parser.add_argument("--rights", default="public_domain_us")
    parser.add_argument("--chapter", type=int, default=1,
                        help="chapter to render (1-based); 0 renders all")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"no such file: {args.file}", file=sys.stderr)
        return 1

    settings = Settings.load()
    engine = db.make_engine(settings.database_url)
    db.init_db(engine)
    provider = get_provider(settings)

    upload_id = new_id("up")
    stored = settings.media_dir / "uploads" / f"{upload_id}{args.file.suffix or '.txt'}"
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(args.file.read_bytes())

    with engine.begin() as conn:
        work = db.create_work(
            conn,
            title=args.title or args.file.stem.replace("_", " ").title(),
            author=args.author,
            language=args.language,
            rights_basis=args.rights,
        )
        revision = db.create_revision(conn, work_id=work["id"],
                                      source_path=str(stored), language=args.language)
        db.insert_upload(conn, upload_id=upload_id, filename=args.file.name,
                         path=str(stored), size=stored.stat().st_size)
        db.enqueue(conn, kind="ingest.revision", target_type="revision",
                   target_id=revision["id"], priority=10,
                   idempotency_key=f"ingest:{revision['id']}")

    print(f"book {work['id']} — ingesting…")
    drain(engine, settings.worker_id, HANDLERS, settings)

    with engine.connect() as conn:
        chapters = db.list_chapters(conn, work["id"])
    if not chapters:
        print("ingest produced no chapters", file=sys.stderr)
        return 1
    print(f"{len(chapters)} chapters, "
          f"{sum(c['word_count'] for c in chapters):,} words")

    targets = chapters if args.chapter == 0 else [chapters[min(args.chapter, len(chapters)) - 1]]
    with engine.begin() as conn:
        for chapter in targets:
            render_set = db.get_or_create_render_set(
                conn, chapter_id=chapter["id"], revision_id=chapter["revision_id"],
                policy_version=POLICY_VERSION, model_family=provider.model_id,
            )
            db.enqueue(conn, kind="tts.chapter", target_type="render_set",
                       target_id=render_set["id"], priority=10,
                       idempotency_key=f"tts:{render_set['id']}")

    print(f"rendering {len(targets)} chapter(s) with {provider.model_id}…")
    drain(engine, settings.worker_id, HANDLERS, settings)

    with engine.connect() as conn:
        for chapter in targets:
            render_set = db.active_render_set(conn, chapter["id"])
            print(f"  ch{chapter['ordinal'] + 1:>3} {chapter['title'][:50]:<50} "
                  f"{render_set['status']:<16} {render_set['progress']}/{render_set['total']}")
    print(f"\nopen http://localhost:8000  (book id {work['id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

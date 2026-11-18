"""Worker entrypoint: a loop, a signal handler, and a job registry."""

from __future__ import annotations

import logging
import signal
import sys
import time

from aab_core import Settings
from aab_db import init_db, make_engine
from aab_jobs import drain, run_once

from .jobs import ingest, tts

log = logging.getLogger("aab.worker")

HANDLERS = {
    "ingest.revision": ingest.handle,
    "tts.chapter": tts.handle,
}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    settings = Settings.load()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-14s %(message)s",
        datefmt="%H:%M:%S",
    )
    engine = make_engine(settings.database_url)
    init_db(engine)

    if "--once" in argv:
        count = drain(engine, settings.worker_id, HANDLERS, settings)
        log.info("drained", extra={"jobs": count})
        return 0

    stopping = False

    def _stop(signum, _frame):
        nonlocal stopping
        stopping = True
        log.info("signal", extra={"signal": signum})

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    log.info("worker.ready", extra={"worker": settings.worker_id})
    while not stopping:
        try:
            worked = run_once(engine, settings.worker_id, HANDLERS, settings)
        except Exception:
            log.exception("loop.error")
            time.sleep(2)
            continue
        if not worked:
            time.sleep(1.0)
    log.info("worker.stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

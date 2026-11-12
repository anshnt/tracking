"""Worker: python -m portal.worker [--once]. Claims jobs and dispatches to portal.jobs.HANDLERS."""

import logging
import signal
import sys
import time

from portal import jobs
from portal.connectors import registry
from portal.db import session_factory
from portal.handlers import load_all
from portal.worker import tasks

POLL_SECONDS = 2.0
log = logging.getLogger("portal.worker")


def drain(max_jobs: int = 1000) -> int:
    """Run due jobs until none are left. Returns how many ran."""
    n = 0
    with session_factory()() as db:
        while n < max_jobs and jobs.run_one(db):
            n += 1
    return n


def main(argv: list[str]) -> None:
    logging.basicConfig(level=logging.INFO)
    load_all()
    registry.register_configured()
    with session_factory()() as db:
        tasks.schedule(db)
    if "--once" in argv:
        log.info("ran %d jobs", drain())
        return
    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    while not stop:
        if drain() == 0:
            time.sleep(POLL_SECONDS)  # ponytail: poll loop; LISTEN/NOTIFY if latency matters


if __name__ == "__main__":
    main(sys.argv[1:])

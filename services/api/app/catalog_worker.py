"""Single-process catalog import worker; PostgreSQL row locks coordinate multiple instances."""

import logging
import signal
import time

from app.catalog.imports import execute_import
from app.core.database import get_engine

running = True


def stop(signum, frame):
    global running
    running = False


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while running:
        try:
            if not execute_import(get_engine()):
                time.sleep(1)
        except Exception as error:
            logging.error("catalog_worker_error type=%s", type(error).__name__)
            time.sleep(2)


if __name__ == "__main__":
    main()

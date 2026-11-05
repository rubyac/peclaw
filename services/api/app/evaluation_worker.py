import logging
import signal
import time

from app.core.database import get_engine
from app.evaluation.engine import execute_evaluation

running = True


def stop(signum, frame):
    global running
    running = False


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while running:
        try:
            if not execute_evaluation(get_engine()):
                time.sleep(1)
        except Exception as error:
            logging.error("evaluation_worker_error type=%s", type(error).__name__)
            time.sleep(2)


if __name__ == "__main__":
    main()

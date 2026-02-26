"""
main.py
=======
Application entry point.  Starts APScheduler in a background thread and
the Flask webhook server in the main thread.

    python main.py
"""

import logging
import signal
import sys

from app.config import PORT, init_starkbank
from app.scheduler import start_scheduler
from app.webhook import app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)


def main() -> None:  # pragma: no cover
    init_starkbank()

    scheduler = start_scheduler()

    def _shutdown(signum, frame):
        logging.getLogger(__name__).info("Shutting down …")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    app.run(host="0.0.0.0", port=PORT, debug=False)


if __name__ == "__main__":  # pragma: no cover
    main()

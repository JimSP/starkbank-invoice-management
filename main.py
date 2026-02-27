import logging
import signal
import sys

from app.config import config
from app.database import init_db 
from app.scheduler import start_scheduler
from app.queue_worker import start_worker
from app.webhook import app

logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)


def main() -> None:  # pragma: no cover

    if config.USE_MOCK_API:
        from app.mock_interceptor import setup_mock_interceptor
        setup_mock_interceptor()
    
    init_db()

    config.init_starkbank()
    start_worker()
    scheduler = start_scheduler()

    def _shutdown(signum, frame):
        logging.getLogger(__name__).info(f"Shutting down signum={signum}, frame={frame}")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    app.run(host="0.0.0.0", port=config.APP_PORT, debug=False)


if __name__ == "__main__":  # pragma: no cover
    main()

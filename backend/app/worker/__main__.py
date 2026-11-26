"""Background worker: `uv run python -m app.worker` (from backend/).

On start it re-delivers jobs that may have been lost (queued while Redis was down, or
running when a worker died), then processes the queue. RQ forks a fresh "work horse"
process per job, so a crash or a timeout kills only that job.
"""

import logging

import redis
from rq import Worker

from app.core.config import get_settings
from app.core.logs import configure_logging
from app.db.session import get_engine
from app.modules.jobs import runner
from app.worker.sweep import requeue_lost

logger = logging.getLogger("app.worker")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    logger.info("worker starting", extra={"redelivered": requeue_lost(older_than_seconds=60)})
    # The sweep opened database connections in this (parent) process. Each job runs in a
    # forked child; children must not share the parent's sockets, so empty the pool here and
    # let every child open its own connections.
    get_engine().dispose()
    # Import the handlers (pandas, scikit-learn, pypdf) once in the parent, so forked work
    # horses start with them already loaded.
    runner._handlers()
    connection = redis.Redis.from_url(settings.redis_url)
    # with_scheduler: needed for RQ's delayed retries (Retry interval).
    Worker([settings.job_queue_name], connection=connection).work(with_scheduler=True)


if __name__ == "__main__":
    main()

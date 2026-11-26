"""Re-deliver jobs that the queue may have lost. Safe to run any time: delivering a job
twice is harmless, because only one worker can claim it (see jobs.service.claim)."""

import logging

from app.db.session import get_sessionmaker
from app.modules.jobs import service as jobs
from app.worker.queue import JobQueue, get_job_queue

logger = logging.getLogger(__name__)


def requeue_lost(older_than_seconds: int, queue: JobQueue | None = None) -> int:
    queue = queue or get_job_queue()
    with get_sessionmaker()() as db:
        lost = jobs.needing_requeue(db, older_than_seconds)
        for job in lost:
            queue.enqueue(job.id, job.kind)
            logger.info("re-delivered job %s (%s, %s)", job.id, job.kind, job.status)
    return len(lost)

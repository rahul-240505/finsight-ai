"""Functions the RQ worker imports by name. Keep them thin: all logic is in the runner."""

import uuid

from app.modules.jobs.runner import run_job


def execute(job_id: str) -> str:
    return run_job(uuid.UUID(job_id))

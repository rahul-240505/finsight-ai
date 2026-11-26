"""Uploaded files waiting for the worker. Stored outside the repo's tracked files
(`uploads/` is git-ignored), owner-only permissions, named by job id, deleted when the job
finishes. Only these generated names are ever opened, so a payload can't point elsewhere."""

import os
import re
import uuid
from pathlib import Path

from app.core.config import get_settings

_NAME = re.compile(r"^[0-9a-f-]{36}\.(csv|pdf)$")


def _path(name: str) -> Path:
    if not _NAME.match(name):
        raise ValueError("invalid upload name")
    return get_settings().upload_dir / name


def save(job_id: uuid.UUID, extension: str, data: bytes) -> str:
    name = f"{job_id}.{extension}"
    directory = get_settings().upload_dir
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(_path(name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return name


def read(name: str) -> bytes:
    return _path(name).read_bytes()


def delete(name: str) -> None:
    _path(name).unlink(missing_ok=True)

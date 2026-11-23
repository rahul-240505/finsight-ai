"""Liveness and readiness probes. Unversioned: they serve infrastructure, not API clients."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.core.config import Settings, get_settings
from app.core.readiness import Check, build_checks, run_checks

router = APIRouter(tags=["ops"])


def get_readiness_checks(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Check]:
    """Separate dependency so tests can swap in fake checks without Docker."""
    return build_checks(settings)


@router.get("/ready")
def ready(
    response: Response,
    checks: Annotated[dict[str, Check], Depends(get_readiness_checks)],
) -> dict[str, object]:
    """Readiness: can we serve traffic? 503 tells a load balancer to wait, not to restart us."""
    results = run_checks(checks)
    all_ok = all(value == "ok" for value in results.values())
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if all_ok else "not_ready", "checks": results}


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up.

    Must not touch dependencies, or a short DB outage would look like a dead app and get restarted.
    """
    return {"status": "ok"}

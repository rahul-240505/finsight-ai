"""FastAPI entry point. Run: uv run uvicorn app.main:app --reload (from backend/)."""

from fastapi import APIRouter, FastAPI

from app.api import health
from app.api.v1 import answers, auth, datasets, documents, jobs, reports, risk, transactions, users
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logs import configure_logging
from app.core.middleware import install_middleware


def create_app() -> FastAPI:
    """Build a fresh app; tests call this to get an isolated instance with their own overrides."""
    app = FastAPI(title="FinSight AI", version="0.8.0")
    install_error_handlers(app)
    install_middleware(app)

    app.include_router(health.router)
    v1 = APIRouter(prefix="/api/v1")
    for module in (auth, users, datasets, transactions, risk, documents, answers, jobs, reports):
        v1.include_router(module.router)
    app.include_router(v1)
    return app


settings = get_settings()
configure_logging(settings.log_level, settings.log_json)
app = create_app()

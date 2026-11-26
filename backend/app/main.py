"""FastAPI entry point. Run: uv run uvicorn app.main:app --reload (from backend/)."""

from fastapi import APIRouter, FastAPI

from app.api import health
from app.api.v1 import auth, datasets, risk, transactions, users
from app.core.errors import install_error_handlers
from app.core.middleware import install_middleware


def create_app() -> FastAPI:
    """Build a fresh app; tests call this to get an isolated instance with their own overrides."""
    app = FastAPI(title="FinSight AI", version="0.4.0")
    install_error_handlers(app)
    install_middleware(app)

    app.include_router(health.router)
    v1 = APIRouter(prefix="/api/v1")
    for module in (auth, users, datasets, transactions, risk):
        v1.include_router(module.router)
    app.include_router(v1)
    return app


app = create_app()

"""FastAPI entry point. Run: uv run uvicorn app.main:app --reload (from backend/)."""

from fastapi import FastAPI

from app.api import health


def create_app() -> FastAPI:
    """Build a fresh app; tests call this to get an isolated instance with their own overrides."""
    app = FastAPI(title="FinSight AI", version="0.1.0")
    app.include_router(health.router)
    return app


app = create_app()

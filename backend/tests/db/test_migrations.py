"""Migrations must apply to an empty database, roll all the way back, and apply again."""

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect

from tests.conftest import alembic_config, fresh_database

pytestmark = pytest.mark.integration


def test_upgrade_downgrade_upgrade_round_trip() -> None:
    url = fresh_database("migrations")
    cfg = alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "head")
        assert {"users", "sessions", "datasets"} <= set(inspect(engine).get_table_names())
        command.downgrade(cfg, "base")
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
        command.upgrade(cfg, "head")
    finally:
        engine.dispose()

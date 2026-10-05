from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def create_db_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_timeout=2,
        connect_args={"connect_timeout": 2},
    )


def check_database(engine: Engine) -> tuple[bool, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, "ok"
    except Exception:
        return False, "unavailable"


def get_connection(engine: Engine) -> Generator[object, None, None]:
    with engine.connect() as connection:
        yield connection

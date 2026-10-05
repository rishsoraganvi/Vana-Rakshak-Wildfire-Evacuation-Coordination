from __future__ import annotations

from typing import Any

from redis import Redis
from sqlalchemy.engine import Engine
from wildfire_core.db.session import check_database


def readiness(engine: Engine, redis_client: Redis) -> dict[str, Any]:
    db_ok, db_detail = check_database(engine)
    try:
        redis_client.ping()
        redis_ok, redis_detail = True, "ok"
    except Exception:
        redis_ok, redis_detail = False, "unavailable"
    dependencies = {
        "database": {"status": "ok" if db_ok else "unavailable", "detail": db_detail},
        "redis": {"status": "ok" if redis_ok else "unavailable", "detail": redis_detail},
    }
    ready = db_ok and redis_ok
    return {"status": "ready" if ready else "not_ready", "dependencies": dependencies}

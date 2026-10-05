from __future__ import annotations

from fastapi import FastAPI, Response, status
from redis import Redis
from wildfire_core.config import Settings, load_settings
from wildfire_core.db.session import create_db_engine

from .health import readiness
from .routers.config import create_config_router


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or load_settings()
    engine = create_db_engine(resolved.database_url.get_secret_value())
    redis_client = Redis.from_url(resolved.redis_url.get_secret_value(), socket_timeout=2)
    app = FastAPI(title="Vana-Rakshak API", version="0.1.0")
    app.state.settings = resolved
    app.state.engine = engine
    app.state.redis = redis_client

    @app.get("/api/v1/health/live", tags=["health"])
    def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/api/v1/health/ready", tags=["health"])
    def ready(response: Response) -> dict[str, object]:
        result = readiness(engine, redis_client)
        if result["status"] != "ready":
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return result

    app.include_router(create_config_router(resolved), prefix="/api/v1")
    return app


app = create_app()

from __future__ import annotations

from fastapi import APIRouter
from wildfire_core.config import Settings


def create_config_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/config", tags=["config"])

    @router.get("", response_model=dict[str, object])
    def get_safe_config() -> dict[str, object]:
        return settings.safe_projection()

    return router

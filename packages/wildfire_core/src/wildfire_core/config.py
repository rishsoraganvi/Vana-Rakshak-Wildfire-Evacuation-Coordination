from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class BBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def ordered(self) -> BBox:
        if self.west >= self.east or self.south >= self.north:
            raise ValueError("bbox bounds must be ordered")
        return self

    @classmethod
    def from_value(cls, value: str | list[float] | tuple[float, ...]) -> BBox:
        values = (
            [float(item.strip()) for item in value.split(",")]
            if isinstance(value, str)
            else list(value)
        )
        if len(values) != 4:
            raise ValueError("AOI_BBOX must contain west,south,east,north")
        return cls(west=values[0], south=values[1], east=values[2], north=values[3])


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_env: str = "dev"
    log_level: str = "INFO"
    aoi_name: str
    aoi_bbox: BBox
    pilot_cluster_id: str
    weather_provider: str
    firms_sources: tuple[str, ...]
    llm_enabled: bool
    llm_provider: str
    llm_model: str
    database_url: SecretStr
    redis_url: SecretStr
    postgres_password: SecretStr = SecretStr("change_me")

    # Phase 2 additions
    groq_api_key: SecretStr = SecretStr("")
    osm_cache_path: Path = Path("data/osm/bandipur_road_graph.graphml")
    fire_ensemble_seeds: tuple[int, ...] = (42, 43, 44)
    fire_grid_resolution_m: int = 250
    dbscan_eps_deg: float = 0.01
    dbscan_min_samples: int = 3
    route_fire_penalty_near: float = 5.0
    llm_rationale_max_tokens: int = 400
    llm_request_timeout_s: int = 30

    @field_validator("aoi_bbox", mode="before")
    @classmethod
    def parse_bbox(cls, value: Any) -> Any:
        return BBox.from_value(value) if isinstance(value, (str, list, tuple)) else value

    def safe_projection(self) -> dict[str, Any]:
        return {
            "app_env": self.app_env,
            "aoi": {
                "name": self.aoi_name,
                "bbox": self.aoi_bbox.model_dump(),
                "geometry": "replaceable_placeholder_polygon",
            },
            "pilot_cluster_id": self.pilot_cluster_id,
            "weather_provider": self.weather_provider,
            "firms_sources": list(self.firms_sources),
            "llm_enabled": self.llm_enabled,
        }


_ENV_MAP = {
    "APP_ENV": "app_env",
    "LOG_LEVEL": "log_level",
    "AOI_NAME": "aoi_name",
    "AOI_BBOX": "aoi_bbox",
    "PILOT_CLUSTER_ID": "pilot_cluster_id",
    "WEATHER_PROVIDER": "weather_provider",
    "FIRMS_SOURCES": "firms_sources",
    "LLM_ENABLED": "llm_enabled",
    "LLM_PROVIDER": "llm_provider",
    "LLM_MODEL": "llm_model",
    "DATABASE_URL": "database_url",
    "REDIS_URL": "redis_url",
    "POSTGRES_PASSWORD": "postgres_password",
    "GROQ_API_KEY": "groq_api_key",
    "OSM_CACHE_PATH": "osm_cache_path",
}


def load_settings(config_path: Path | None = None) -> Settings:
    path = config_path or Path("config/defaults.yaml")
    defaults = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    values: dict[str, Any] = dict(defaults or {})
    if isinstance(values.get("firms_sources"), list):
        values["firms_sources"] = tuple(values["firms_sources"])
    if isinstance(values.get("fire_ensemble_seeds"), list):
        values["fire_ensemble_seeds"] = tuple(values["fire_ensemble_seeds"])
    for env_name, field_name in _ENV_MAP.items():
        if env_name not in os.environ:
            continue
        raw = os.environ[env_name]
        if field_name == "firms_sources":
            values[field_name] = tuple(item.strip() for item in raw.split(",") if item.strip())
        elif field_name == "llm_enabled":
            values[field_name] = raw.lower() in {"1", "true", "yes", "on"}
        elif field_name == "osm_cache_path":
            values[field_name] = Path(raw)
        else:
            values[field_name] = raw
    return Settings.model_validate(values)

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
    postgres_password: SecretStr = SecretStr("")

    # Phase 2 additions
    groq_api_key: SecretStr = SecretStr("")
    osm_cache_path: Path = Path("data/osm/bandipur_road_graph.graphml")
    fire_ensemble_seeds: tuple[int, ...] = (42, 43, 44)
    fire_grid_resolution_m: int = 250
    dbscan_eps_deg: float = 0.01
    dbscan_min_samples: int = 3
    # Superseded by route_p50_mult for Phase 3 routing; Phase 2 code reads it until plan 03-10.
    route_fire_penalty_near: float = 5.0
    llm_rationale_max_tokens: int = 400
    llm_request_timeout_s: int = 30

    # Phase 3 additions
    shelter_usable_factor: float = 0.6
    shelter_exclusion_buffer_m: int = 1000
    route_p50_mult: float = 10.0
    route_p90_mult: float = 3.0
    k_paths: int = 3
    k_paths_max_leg_s: float = 5.0
    max_snap_distance_m: int = 2000
    bpr_alpha: float = 0.15
    bpr_beta: float = 4.0
    persons_per_vehicle: float = 4.0
    evac_window_h: float = 2.0
    congestion_passes: int = 3
    lane_capacity_vph: dict[str, int] = Field(
        default_factory=lambda: {
            "motorway": 1800,
            "trunk": 1600,
            "primary": 1400,
            "secondary": 1100,
            "tertiary": 900,
            "default": 600,
        }
    )
    link_capacity_factor: float = 0.8
    conflict_max_loops: int = 3
    fix_menu_order: tuple[str, ...] = ("next_path", "rematch", "split")
    trigger_debounce_s: int = 300
    perimeter_iou_threshold: float = 0.8
    perimeter_growth_threshold: float = 0.25
    shelter_capacity_change_fraction: float = 0.10
    pilot_center_lat: float = 11.72
    pilot_center_lon: float = 76.64
    pilot_buffer_m: int = 10000
    plan_valid_for_min: int = 60
    specialist_timeout_s: int = 60
    stale_firms_min: int = 180
    weather_max_distance_km: float = 50.0
    llm_control_max_tokens: int = 256
    llm_control_temperature: float = 0.0
    shelters_seed_path: Path = Path("config/seed/shelters_bandipur.csv")
    settlements_seed_path: Path = Path("config/seed/settlements_bandipur.csv")

    @field_validator("aoi_bbox", mode="before")
    @classmethod
    def parse_bbox(cls, value: Any) -> Any:
        return BBox.from_value(value) if isinstance(value, (str, list, tuple)) else value

    @model_validator(mode="after")
    def validate_phase3_coefficients(self) -> Settings:
        if not 0 < self.shelter_usable_factor <= 1:
            raise ValueError("shelter_usable_factor must be in (0, 1]")
        if not self.route_p50_mult >= self.route_p90_mult >= 1:
            raise ValueError("route multipliers must satisfy p50 >= p90 >= 1")
        if not 1 <= self.k_paths <= 5:
            raise ValueError("k_paths must be between 1 and 5")
        if not 2 <= self.congestion_passes <= 3:
            raise ValueError("congestion_passes must be 2 or 3 (D-08)")
        if not 1 <= self.conflict_max_loops <= 3:
            raise ValueError("conflict_max_loops must be between 1 and 3 (TechSpec 6.2)")
        if sorted(self.fix_menu_order) != ["next_path", "rematch", "split"]:
            raise ValueError("fix_menu_order must be exactly next_path, rematch and split (D-09)")
        if "default" not in self.lane_capacity_vph:
            raise ValueError("lane_capacity_vph needs a 'default' key")
        if self.trigger_debounce_s < 0:
            raise ValueError("trigger_debounce_s must be >= 0")
        if not 0 < self.perimeter_iou_threshold <= 1:
            raise ValueError("perimeter_iou_threshold must be in (0, 1]")
        if self.persons_per_vehicle <= 0 or self.evac_window_h <= 0:
            raise ValueError("persons_per_vehicle and evac_window_h must be positive")
        if not 0 <= self.llm_control_temperature <= 0.2:
            raise ValueError("llm_control_temperature must be in [0, 0.2] (Rules 3)")
        return self

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
    if isinstance(values.get("fix_menu_order"), list):
        values["fix_menu_order"] = tuple(values["fix_menu_order"])
    for env_name, field_name in _ENV_MAP.items():
        if env_name not in os.environ:
            continue
        raw = os.environ[env_name]
        if not raw.strip():
            # A blank variable (e.g. LLM_MODEL= copied from a template) means "unset", so it
            # must not shadow the config/defaults.yaml value.
            continue
        if field_name == "firms_sources":
            values[field_name] = tuple(item.strip() for item in raw.split(",") if item.strip())
        elif field_name == "llm_enabled":
            values[field_name] = raw.lower() in {"1", "true", "yes", "on"}
        elif field_name == "osm_cache_path":
            values[field_name] = Path(raw)
        else:
            values[field_name] = raw
    return Settings.model_validate(values)

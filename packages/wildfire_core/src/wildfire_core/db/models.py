from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    MetaData,
    String,
    Table,
)
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.sql import func

metadata = MetaData()
data_origin = ENUM(
    "live", "replay", "simulated", "manual", name="data_origin", create_type=False
)

hotspots = Table(
    "hotspots",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("source", String, nullable=False),
    Column("acq_datetime", DateTime(timezone=True), nullable=False),
    Column("lat", Float, nullable=False),
    Column("lon", Float, nullable=False),
    Column("geom"),
    Column("brightness", Float),
    Column("frp", Float),
    Column("confidence", String),
    Column("daynight", String(1)),
    Column("scan", Float),
    Column("track", Float),
    Column("origin", data_origin, nullable=False), Column("raw", JSON),
    Column("cluster_id", UUID(as_uuid=True)),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
)
weather_observations = Table(
    "weather_observations",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("provider", String, nullable=False),
    Column("lat", Float, nullable=False),
    Column("lon", Float, nullable=False),
    Column("valid_time", DateTime(timezone=True), nullable=False),
    Column("issued_at", DateTime(timezone=True), nullable=False),
    Column("is_forecast", Boolean, nullable=False),
    Column("temperature_c", Float),
    Column("rh_pct", Float),
    Column("wind_speed_ms", Float),
    Column("wind_dir_deg", Float),
    Column("wind_gust_ms", Float),
    Column("precip_mm", Float),
    Column("origin", data_origin, nullable=False),
)

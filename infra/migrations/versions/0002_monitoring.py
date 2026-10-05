"""Create Phase 1 monitoring tables."""

from alembic import op

revision = "0002_monitoring"
down_revision = "0001_extensions_and_aoi"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE data_origin AS ENUM ('live', 'replay', 'simulated', 'manual');

        CREATE TABLE hotspots (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source text NOT NULL,
            acq_datetime timestamptz NOT NULL,
            lat double precision NOT NULL,
            lon double precision NOT NULL,
            geom geometry(Point, 4326) NOT NULL,
            brightness double precision,
            frp double precision,
            confidence text,
            daynight char(1),
            scan double precision,
            track double precision,
            origin data_origin NOT NULL DEFAULT 'live',
            raw jsonb,
            freshness_status text NOT NULL DEFAULT 'fresh',
            freshness_age_seconds double precision,
            freshness_threshold_seconds double precision,
            cluster_id uuid,
            ingested_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (source, acq_datetime, lat, lon)
        );
        CREATE INDEX ix_hotspots_geom ON hotspots USING gist (geom);
        CREATE INDEX ix_hotspots_acq_datetime ON hotspots (acq_datetime DESC);

        CREATE TABLE weather_observations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            provider text NOT NULL,
            lat double precision NOT NULL,
            lon double precision NOT NULL,
            valid_time timestamptz NOT NULL,
            issued_at timestamptz NOT NULL,
            is_forecast boolean NOT NULL,
            temperature_c double precision,
            rh_pct double precision,
            wind_speed_ms double precision,
            wind_dir_deg double precision,
            wind_gust_ms double precision,
            precip_mm double precision,
            origin data_origin NOT NULL DEFAULT 'live',
            raw jsonb,
            freshness_status text NOT NULL DEFAULT 'fresh',
            freshness_age_seconds double precision,
            freshness_threshold_seconds double precision,
            UNIQUE (provider, lat, lon, valid_time, issued_at)
        );
        CREATE INDEX ix_weather_observations_valid_time
            ON weather_observations (valid_time DESC);

        CREATE TABLE settlements (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name text NOT NULL,
            kind text,
            population integer,
            pop_source text,
            geom geometry(Point, 4326) NOT NULL,
            buffer_m integer NOT NULL DEFAULT 2000,
            osm_id bigint
        );
        CREATE INDEX ix_settlements_geom ON settlements USING gist (geom);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS settlements;
        DROP TABLE IF EXISTS weather_observations;
        DROP TABLE IF EXISTS hotspots;
        DROP TYPE IF EXISTS data_origin;
        """
    )

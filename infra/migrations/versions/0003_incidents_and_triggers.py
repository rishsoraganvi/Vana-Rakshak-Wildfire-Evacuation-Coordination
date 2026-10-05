"""Create Phase 1 incident and trigger tables."""

from alembic import op

revision = "0003_incidents_and_triggers"
down_revision = "0002_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE incident_status AS ENUM
            ('open', 'watching', 'planning', 'awaiting_review', 'active', 'resolved');
        CREATE TYPE trigger_type AS ENUM
            ('new_hotspot', 'risk_threshold', 'wind_shift', 'perimeter_change',
             'road_blocked', 'shelter_capacity_change', 'scheduled_refresh', 'manual');

        CREATE TABLE incidents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text UNIQUE NOT NULL,
            aoi_id uuid REFERENCES areas_of_interest(id),
            status incident_status NOT NULL DEFAULT 'open',
            severity smallint NOT NULL DEFAULT 1 CHECK (severity BETWEEN 1 AND 5),
            origin data_origin NOT NULL DEFAULT 'live',
            summary text,
            opened_at timestamptz NOT NULL DEFAULT now(),
            resolved_at timestamptz,
            resolved_by uuid,
            state_version integer NOT NULL DEFAULT 0
        );
        CREATE INDEX ix_incidents_status ON incidents (status);
        CREATE INDEX ix_incidents_aoi_id ON incidents (aoi_id);

        CREATE TABLE hotspot_clusters (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            incident_id uuid REFERENCES incidents(id),
            centroid geometry(Point, 4326) NOT NULL,
            hull geometry(Polygon, 4326),
            hotspot_count integer NOT NULL,
            max_frp double precision,
            first_seen timestamptz NOT NULL,
            last_seen timestamptz NOT NULL,
            dismissed boolean NOT NULL DEFAULT false,
            dismissed_by uuid,
            dismissed_reason text
        );
        CREATE INDEX ix_hotspot_clusters_centroid
            ON hotspot_clusters USING gist (centroid);
        CREATE INDEX ix_hotspot_clusters_incident_id
            ON hotspot_clusters (incident_id);
        CREATE INDEX ix_hotspot_clusters_hull
            ON hotspot_clusters USING gist (hull);

        ALTER TABLE hotspots
            ADD CONSTRAINT fk_hotspot_cluster
            FOREIGN KEY (cluster_id) REFERENCES hotspot_clusters(id);
        CREATE INDEX ix_hotspots_cluster_id ON hotspots (cluster_id);

        CREATE TABLE triggers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            incident_id uuid REFERENCES incidents(id),
            type trigger_type NOT NULL,
            details jsonb NOT NULL DEFAULT '{}'::jsonb,
            detected_at timestamptz NOT NULL DEFAULT now(),
            coalesced_into uuid REFERENCES triggers(id),
            handled_run_id uuid
        );
        CREATE INDEX ix_triggers_incident_detected
            ON triggers (incident_id, detected_at DESC);
        CREATE INDEX ix_triggers_coalesced_into ON triggers (coalesced_into);

        CREATE TABLE fire_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            incident_id uuid NOT NULL REFERENCES incidents(id),
            model_version text NOT NULL,
            params jsonb NOT NULL,
            n_simulations integer NOT NULL,
            weather_snapshot jsonb NOT NULL,
            started_at timestamptz NOT NULL,
            finished_at timestamptz,
            duration_ms integer
        );
        CREATE INDEX ix_fire_runs_incident_id ON fire_runs (incident_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS fire_runs;
        DROP TABLE IF EXISTS triggers;
        ALTER TABLE hotspots DROP CONSTRAINT IF EXISTS fk_hotspot_cluster;
        DROP TABLE IF EXISTS hotspot_clusters;
        DROP TABLE IF EXISTS incidents;
        DROP TYPE IF EXISTS trigger_type;
        DROP TYPE IF EXISTS incident_status;
        """
    )

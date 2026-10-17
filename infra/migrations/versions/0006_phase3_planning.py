"""Add Phase 3 planning schema.

Adds shelters, shelter_occupancy history, settlement external keys, the plan_versions
provenance/validation/freshness/parent columns, a DB-level immutability trigger and a minimal
road_edge_status table. Adds the 'failed' plan_status value (D-11).

Downgrade note: PostgreSQL cannot drop an enum value, so the 'failed' plan_status value is
forward-only and stays after downgrade(). Everything else is reversed.

The ALTER TYPE ... ADD VALUE statement runs first and the new literal is never used again in this
migration, because PostgreSQL forbids using a new enum value in the transaction that adds it.
"""

from alembic import op

revision = "0006_phase3_planning"
down_revision = "0005_phase2_plan_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # (a) enum value, on its own, never referenced again below
    op.execute("ALTER TYPE plan_status ADD VALUE IF NOT EXISTS 'failed'")

    # (b) shelter registry
    op.execute(
        """
        CREATE TABLE shelters (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            external_ref text NOT NULL,
            name text NOT NULL,
            kind text NOT NULL
                CHECK (kind IN ('school', 'community_hall', 'other')),
            geom geometry(Point, 4326) NOT NULL,
            capacity integer NOT NULL CHECK (capacity > 0),
            usable_factor numeric(3, 2)
                CHECK (usable_factor IS NULL OR (usable_factor > 0 AND usable_factor <= 1)),
            capacity_source text NOT NULL CHECK (length(capacity_source) > 0),
            occupancy integer NOT NULL DEFAULT 0 CHECK (occupancy >= 0),
            is_active boolean NOT NULL DEFAULT true,
            is_simulated boolean NOT NULL DEFAULT false,
            contact text,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_shelters_external_ref UNIQUE (external_ref),
            CONSTRAINT ck_shelters_occupancy_le_capacity CHECK (occupancy <= capacity)
        );
        CREATE INDEX ix_shelters_geom ON shelters USING gist (geom);
        """
    )

    # (c) append-only occupancy history
    op.execute(
        """
        CREATE TABLE shelter_occupancy (
            id bigserial PRIMARY KEY,
            shelter_id uuid NOT NULL REFERENCES shelters(id),
            incident_id uuid REFERENCES incidents(id),
            occupancy integer NOT NULL CHECK (occupancy >= 0),
            delta integer NOT NULL,
            source text NOT NULL DEFAULT 'plan',
            recorded_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_shelter_occupancy_shelter
            ON shelter_occupancy (shelter_id, recorded_at DESC);
        CREATE INDEX ix_shelter_occupancy_incident ON shelter_occupancy (incident_id);
        """
    )

    # (d) settlement seed keys
    op.execute(
        """
        ALTER TABLE settlements
            ADD COLUMN external_ref text,
            ADD COLUMN is_simulated boolean NOT NULL DEFAULT false,
            ADD CONSTRAINT uq_settlements_external_ref UNIQUE (external_ref);
        """
    )

    # (e) plan_versions provenance, validation, freshness and parent link
    op.execute(
        """
        ALTER TABLE plan_versions
            ADD COLUMN parent_plan_id uuid REFERENCES plan_versions(id),
            ADD COLUMN trigger_id uuid REFERENCES triggers(id),
            ADD COLUMN state_version integer,
            ADD COLUMN plan_schema_version text NOT NULL DEFAULT '2.0',
            ADD COLUMN validation jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN freshness jsonb NOT NULL DEFAULT '{}'::jsonb,
            ADD COLUMN provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
            ADD COLUMN diff jsonb,
            ADD COLUMN used_fallback boolean NOT NULL DEFAULT false,
            ADD COLUMN valid_until timestamptz;
        CREATE INDEX ix_plan_versions_parent_plan_id ON plan_versions (parent_plan_id);
        CREATE INDEX ix_plan_versions_trigger_id ON plan_versions (trigger_id);
        CREATE INDEX ix_plan_versions_incident_status ON plan_versions (incident_id, status);
        """
    )

    # (f) DB-level immutability: only status may change (PLAN-08)
    op.execute(
        """
        CREATE FUNCTION plan_versions_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (
                NEW.id, NEW.incident_id, NEW.version, NEW.rationale_md, NEW.is_llm_fallback,
                NEW.is_simulated, NEW.warnings, NEW.plan_data, NEW.created_at,
                NEW.parent_plan_id, NEW.trigger_id, NEW.state_version, NEW.plan_schema_version,
                NEW.validation, NEW.freshness, NEW.provenance, NEW.diff, NEW.used_fallback,
                NEW.valid_until
            ) IS DISTINCT FROM (
                OLD.id, OLD.incident_id, OLD.version, OLD.rationale_md, OLD.is_llm_fallback,
                OLD.is_simulated, OLD.warnings, OLD.plan_data, OLD.created_at,
                OLD.parent_plan_id, OLD.trigger_id, OLD.state_version, OLD.plan_schema_version,
                OLD.validation, OLD.freshness, OLD.provenance, OLD.diff, OLD.used_fallback,
                OLD.valid_until
            ) THEN
                RAISE EXCEPTION 'plan_versions rows are immutable except status'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_plan_versions_immutable
            BEFORE UPDATE ON plan_versions
            FOR EACH ROW EXECUTE FUNCTION plan_versions_immutable()
        """
    )

    # (g) minimal edge-status source for the road_blocked trigger (D-14)
    op.execute(
        """
        CREATE TABLE road_edge_status (
            id bigserial PRIMARY KEY,
            osm_u bigint NOT NULL,
            osm_v bigint NOT NULL,
            osm_key integer NOT NULL DEFAULT 0,
            status text NOT NULL
                CHECK (status IN ('open', 'congested', 'unsafe', 'blocked')),
            source text NOT NULL
                CHECK (source IN ('model', 'drone', 'manual', 'scenario')),
            incident_id uuid REFERENCES incidents(id),
            valid_from timestamptz NOT NULL DEFAULT now(),
            valid_to timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_road_edge_status_valid_range
                CHECK (valid_to IS NULL OR valid_to > valid_from)
        );
        CREATE INDEX ix_road_edge_status_edge
            ON road_edge_status (osm_u, osm_v, osm_key, valid_from DESC);
        CREATE INDEX ix_road_edge_status_incident ON road_edge_status (incident_id);
        """
    )


def downgrade() -> None:
    """Reverse everything except the forward-only 'failed' plan_status enum value."""
    op.execute(
        """
        DROP INDEX IF EXISTS ix_road_edge_status_incident;
        DROP INDEX IF EXISTS ix_road_edge_status_edge;
        DROP TABLE IF EXISTS road_edge_status;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_plan_versions_immutable ON plan_versions")
    op.execute("DROP FUNCTION IF EXISTS plan_versions_immutable()")
    op.execute(
        """
        DROP INDEX IF EXISTS ix_plan_versions_incident_status;
        DROP INDEX IF EXISTS ix_plan_versions_trigger_id;
        DROP INDEX IF EXISTS ix_plan_versions_parent_plan_id;
        ALTER TABLE plan_versions
            DROP COLUMN IF EXISTS valid_until,
            DROP COLUMN IF EXISTS used_fallback,
            DROP COLUMN IF EXISTS diff,
            DROP COLUMN IF EXISTS provenance,
            DROP COLUMN IF EXISTS freshness,
            DROP COLUMN IF EXISTS validation,
            DROP COLUMN IF EXISTS plan_schema_version,
            DROP COLUMN IF EXISTS state_version,
            DROP COLUMN IF EXISTS trigger_id,
            DROP COLUMN IF EXISTS parent_plan_id;
        ALTER TABLE settlements
            DROP CONSTRAINT IF EXISTS uq_settlements_external_ref,
            DROP COLUMN IF EXISTS is_simulated,
            DROP COLUMN IF EXISTS external_ref;
        DROP INDEX IF EXISTS ix_shelter_occupancy_incident;
        DROP INDEX IF EXISTS ix_shelter_occupancy_shelter;
        DROP TABLE IF EXISTS shelter_occupancy;
        DROP INDEX IF EXISTS ix_shelters_geom;
        DROP TABLE IF EXISTS shelters;
        """
    )

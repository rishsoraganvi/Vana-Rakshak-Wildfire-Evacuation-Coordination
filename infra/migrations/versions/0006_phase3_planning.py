"""Add Phase 3 planning schema: shelters (tracer slice)."""

from alembic import op

revision = "0006_phase3_planning"
down_revision = "0005_phase2_plan_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shelters;")

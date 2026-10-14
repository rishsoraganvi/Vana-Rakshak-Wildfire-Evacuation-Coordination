"""Add Phase 2 plan versions and Coordinator audit fields."""

from alembic import op

revision = "0005_phase2_plan_versions"
down_revision = "0004_shared_state_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE plan_status AS ENUM
            ('draft', 'pending_review', 'approved', 'rejected', 'superseded');

        CREATE TABLE plan_versions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            incident_id uuid NOT NULL REFERENCES incidents(id),
            version integer NOT NULL CHECK (version > 0),
            status plan_status NOT NULL DEFAULT 'draft',
            rationale_md text NOT NULL,
            is_llm_fallback boolean NOT NULL DEFAULT false,
            is_simulated boolean NOT NULL DEFAULT false,
            warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
            plan_data jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_plan_versions_incident_version UNIQUE (incident_id, version)
        );
        CREATE INDEX ix_plan_versions_incident_created
            ON plan_versions (incident_id, created_at DESC);

        ALTER TABLE agent_runs
            ADD COLUMN run_id uuid,
            ADD COLUMN node_name text,
            ADD COLUMN model_metadata jsonb,
            ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
        CREATE INDEX ix_agent_runs_run_id_node_name ON agent_runs (run_id, node_name);
        CREATE INDEX ix_agent_runs_created_at ON agent_runs (created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_agent_runs_created_at;
        DROP INDEX IF EXISTS ix_agent_runs_run_id_node_name;
        ALTER TABLE agent_runs
            DROP COLUMN created_at,
            DROP COLUMN model_metadata,
            DROP COLUMN node_name,
            DROP COLUMN run_id;
        DROP INDEX IF EXISTS ix_plan_versions_incident_created;
        DROP TABLE IF EXISTS plan_versions;
        DROP TYPE IF EXISTS plan_status;
        """
    )
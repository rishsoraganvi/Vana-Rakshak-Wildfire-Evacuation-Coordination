"""Create Phase 1 shared-state and audit tables."""

from alembic import op

revision = "0004_shared_state_audit"
down_revision = "0003_incidents_and_triggers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE agent_name AS ENUM
            ('coordinator', 'fire', 'weather', 'traffic_routing', 'shelter',
             'emergency_vehicle', 'drone_observation');
        CREATE TYPE run_status AS ENUM
            ('queued', 'running', 'succeeded', 'failed', 'timeout', 'skipped');

        CREATE TABLE agent_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            incident_id uuid REFERENCES incidents(id),
            trigger_id uuid REFERENCES triggers(id),
            parent_run_id uuid REFERENCES agent_runs(id),
            agent agent_name NOT NULL,
            status run_status NOT NULL DEFAULT 'queued',
            input jsonb NOT NULL DEFAULT '{}'::jsonb,
            output jsonb,
            error text,
            llm_provider text,
            llm_model text,
            tokens_in integer,
            tokens_out integer,
            started_at timestamptz,
            finished_at timestamptz,
            latency_ms integer
        );
        CREATE INDEX ix_agent_runs_incident_started
            ON agent_runs (incident_id, started_at DESC);
        CREATE INDEX ix_agent_runs_agent_status ON agent_runs (agent, status);

        ALTER TABLE triggers
            ADD CONSTRAINT fk_trigger_run
            FOREIGN KEY (handled_run_id) REFERENCES agent_runs(id);
        CREATE INDEX ix_triggers_handled_run_id ON triggers (handled_run_id);

        CREATE TABLE agent_messages (
            id bigserial PRIMARY KEY,
            run_id uuid NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
            seq integer NOT NULL,
            role text NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
            tool_name text,
            content jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (run_id, seq)
        );
        CREATE INDEX ix_agent_messages_run_id ON agent_messages (run_id);

        CREATE TABLE shared_state_snapshots (
            id bigserial PRIMARY KEY,
            incident_id uuid NOT NULL REFERENCES incidents(id),
            version integer NOT NULL,
            state jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (incident_id, version)
        );
        CREATE INDEX ix_shared_state_snapshots_incident_created
            ON shared_state_snapshots (incident_id, created_at DESC);

        CREATE TABLE audit_log (
            id bigserial PRIMARY KEY,
            actor_id uuid,
            action text NOT NULL,
            entity_type text,
            entity_id uuid,
            detail jsonb NOT NULL DEFAULT '{}'::jsonb,
            at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_audit_log_entity ON audit_log (entity_type, entity_id);
        CREATE INDEX ix_audit_log_at ON audit_log (at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS audit_log;
        DROP TABLE IF EXISTS shared_state_snapshots;
        DROP TABLE IF EXISTS agent_messages;
        ALTER TABLE triggers DROP CONSTRAINT IF EXISTS fk_trigger_run;
        DROP TABLE IF EXISTS agent_runs;
        DROP TYPE IF EXISTS run_status;
        DROP TYPE IF EXISTS agent_name;
        """
    )

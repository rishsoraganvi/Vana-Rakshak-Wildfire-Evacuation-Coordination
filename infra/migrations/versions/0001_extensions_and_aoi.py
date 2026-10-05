"""Install Phase 1 extensions and the replaceable AOI boundary."""

from alembic import op

revision = "0001_extensions_and_aoi"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        CREATE TABLE areas_of_interest (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name text NOT NULL,
            geom geometry(Polygon, 4326) NOT NULL,
            config jsonb NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute("CREATE INDEX ix_areas_of_interest_geom ON areas_of_interest USING gist (geom)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS areas_of_interest")

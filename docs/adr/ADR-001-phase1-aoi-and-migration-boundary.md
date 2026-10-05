# ADR-001: Phase 1 AOI and Migration Boundary

- **Status:** Accepted for Phase 1 foundation
- **Date:** 2026-10-01
- **Scope:** Compose, configuration, and Alembic foundation only

## Decision

Use the configurable bounding box `west=76.0, south=11.5, east=77.3, north=12.4` with a replaceable placeholder polygon. Use `bandipur` as the provisional, environment-overridable pilot cluster identifier. The authoritative park polygon and final pilot settlement choice remain open for Phase 2.

Phase 1 migrations install PostGIS, pgvector, and pgcrypto, then create only AOI, monitoring, incident/trigger, shared-state, and audit primitives. No plan, review, routing, shelter, vehicle, dissemination, or vector-dimension columns are created in this plan.

## Supply-chain pins

- Python build base: official `python:3.12-slim`, amd64 manifest digest `sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f`.
- Redis service: official `redis:7.4.2`, digest `sha256:fbdbaea47b9ae4ecc2082ecdb4e1cea81e32176ffb1dcf643d422ad07427e5d9`.
- PostgreSQL base: official `postgis/postgis:16-3.5`, amd64 manifest digest `sha256:7ef699637304feff96028edbc7a653e135f2db2236d322b5cb2bfca11fd920bc`.
- pgvector: official `pgvector/pgvector` repository tag `v0.8.6`, compiled in the pinned PostGIS/PostgreSQL 16 image. The build does not use an unpinned branch or a third-party binary image.
- Python packages are pinned in `pyproject.toml` and resolved in `uv.lock`; all selected packages use their official PyPI project names and upstream sources were reviewed at the approved legitimacy checkpoint.

## Consequences

The custom database image has a repeatable extension strategy and a clean-volume smoke test is required before the foundation is accepted. Vector storage remains extension-only until the embedding provider and dimension are decided; this avoids locking a draft `vector(1024)` contract into Phase 1.

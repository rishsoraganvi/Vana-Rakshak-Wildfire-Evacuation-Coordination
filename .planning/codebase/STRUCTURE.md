---
last_mapped_commit: 568fe4ddfb5bf5d575995eb03ee89ffbeefc939f
last_mapped_at: 2026-10-14
---
# Codebase Structure

**Analysis Date:** 2026-10-14

## Directory Layout

```text
project-root/
├── apps/
│   ├── agents/fire/              # Fire clustering and spread computation package
│   ├── agents/weather/           # Weather snapshot package
│   ├── api_gateway/              # FastAPI application and routers
│   └── ingest_worker/            # Parsers, ingestion services, triggers, clustering
├── config/                       # YAML application defaults
├── docs/adr/                     # Architecture decision records
├── infra/
│   ├── docker/                   # API and PostgreSQL Dockerfiles
│   ├── migrations/               # Alembic config, environment, revisions
│   └── postgres/                 # PostgreSQL initialization SQL
├── packages/wildfire_core/       # Shared Python package
├── scripts/                      # Operational and demo scripts
├── tests/
│   ├── fixtures/                 # External-data fixtures and expected outputs
│   ├── integration/              # Compose/database integration tests
│   └── unit/                     # Cross-package unit tests
├── docker-compose.yml            # Local PostgreSQL, Redis, and API services
├── pyproject.toml                # Workspace, dependencies, tooling, pytest config
└── uv.lock                       # Resolved workspace dependencies
```

## Directory Purposes

**`apps/`:**
- Purpose: Hold independently scoped application and specialist packages.
- Contains: `src/<package_name>/` Python modules, package-level `pyproject.toml` files, and selected package-local tests.
- Key files: `apps/api_gateway/src/api_gateway/main.py`, `apps/ingest_worker/src/ingest_worker/triggers.py`, `apps/agents/fire/src/agent_fire/ca_model.py`, `apps/agents/weather/src/agent_weather/agent.py`.

**`packages/wildfire_core/`:**
- Purpose: Shared contracts and infrastructure used by application packages.
- Contains: `src/wildfire_core/` modules for config, clock, events, database, geospatial helpers, and schemas; package tests under `packages/wildfire_core/tests/`.
- Key files: `packages/wildfire_core/src/wildfire_core/config.py`, `packages/wildfire_core/src/wildfire_core/db/`, `packages/wildfire_core/src/wildfire_core/schemas/`.

**`infra/`:**
- Purpose: Database/container infrastructure and schema evolution.
- Contains: Dockerfiles in `infra/docker/`, PostgreSQL initialization in `infra/postgres/`, and Alembic files under `infra/migrations/`.
- Key files: `infra/migrations/alembic.ini`, `infra/migrations/env.py`, `infra/migrations/versions/0001_extensions_and_aoi.py` through `0004_shared_state_audit.py`.

**`tests/`:**
- Purpose: Cross-package tests and reusable fixtures.
- Contains: `tests/unit/`, `tests/integration/`, and `tests/fixtures/` with FIRMS and Open-Meteo payloads/expected results.
- Key files: `tests/integration/test_migrations_and_ingest.py`, `tests/unit/test_fire_contracts.py`, `tests/fixtures/firms/`, `tests/fixtures/open_meteo/`.

**`docs/adr/`:**
- Purpose: Record accepted architectural decisions and constraints.
- Contains: Markdown decision records, including `docs/adr/ADR-001-phase1-aoi-and-migration-boundary.md`.

**`.planning/`:**
- Purpose: GSD project planning and codebase reference artifacts.
- Contains: Project state, requirements, roadmap, phase materials, and the codebase maps in `.planning/codebase/`.

## Key File Locations

**Entry Points:**
- `apps/api_gateway/src/api_gateway/main.py`: Creates the FastAPI app and module-level ASGI `app`.
- `scripts/seed_demo.py`: Supports offline AOI seeding with `--offline`.
- `infra/migrations/env.py`: Alembic online/offline migration runner.

**Configuration:**
- `pyproject.toml`: Workspace membership, root dependencies, pytest source paths, Ruff, and mypy configuration.
- `config/defaults.yaml`: Default settings loaded by `wildfire_core.config.load_settings`.
- `docker-compose.yml`: PostgreSQL, Redis, and API service wiring.
- `infra/migrations/alembic.ini`: Alembic configuration.

**Core Logic:**
- `packages/wildfire_core/src/wildfire_core/`: Shared settings, contracts, DB helpers, clock, and Redis event wrapper.
- `apps/ingest_worker/src/ingest_worker/`: Parsers, ingestion services, threshold triggers, and clustering.
- `apps/agents/fire/src/agent_fire/`: Deterministic fire spread model and result conversion.
- `apps/agents/weather/src/agent_weather/`: Persisted weather snapshot selection and freshness assessment.
- `apps/api_gateway/src/api_gateway/`: Current HTTP surface, health checks, and configuration endpoint.

**Testing:**
- `tests/unit/`: Cross-package behavior and contract tests.
- `tests/integration/`: Migration/database/ingestion tests, including tests gated on Compose services.
- `apps/agents/fire/tests/test_ca_model.py`: Fire-model-specific tests.
- `packages/wildfire_core/tests/test_phase2_schemas.py`: Shared Phase 2 schema tests.

## Naming Conventions

**Files:**
- Python modules and tests use lowercase `snake_case`, such as `ca_model.py` and `test_weather_parser.py`.
- Tests are named `test_<behavior_or_module>.py` and are collected from `tests/`, package test folders, and app test folders by pytest configuration.
- Alembic revisions use a numeric prefix and descriptive snake_case suffix, such as `0003_incidents_and_triggers.py`.
- Architecture decisions use `ADR-NNN-<topic>.md`; codebase reference docs use uppercase names such as `ARCHITECTURE.md`.

**Directories:**
- Python package source follows `src/<import_package>/`.
- Application package directories use snake_case names; shared source is grouped by responsibility (`db/`, `geo/`, `schemas/`).
- Repository-wide tests are separated into `unit/`, `integration/`, and `fixtures/`.

## Where to Add New Code

**New Feature:**
- Put shared validated contracts and reusable domain infrastructure in `packages/wildfire_core/src/wildfire_core/`.
- Put application-specific processing in the responsible package under `apps/<package>/src/<import_package>/`.
- Put API handlers in `apps/api_gateway/src/api_gateway/routers/` and register them from `apps/api_gateway/src/api_gateway/main.py`.
- Add durable schema changes as the next ordered revision under `infra/migrations/versions/`; update shared SQLAlchemy metadata when table metadata is needed by repositories.
- Add cross-package tests under `tests/unit/` or `tests/integration/`; keep tests for package-specific behavior alongside that package when following its existing pattern.

**New Component/Module:**
- Shared schemas: `packages/wildfire_core/src/wildfire_core/schemas/`.
- Persistence models/helpers: `packages/wildfire_core/src/wildfire_core/db/`.
- Ingestion parsers/services: `apps/ingest_worker/src/ingest_worker/<source>/`.
- Specialist computations: `apps/agents/<specialist>/src/<import_package>/`.
- API routes: `apps/api_gateway/src/api_gateway/routers/`.

**Utilities:**
- Reusable cross-package helpers belong in `packages/wildfire_core/src/wildfire_core/` under the closest existing responsibility module.
- Test payloads belong in `tests/fixtures/<source>/`; avoid embedding large external payloads in tests.

## Special Directories

**`infra/migrations/versions/`:**
- Purpose: Ordered, executable Alembic schema revisions.
- Generated: No; migration files are authored and versioned with schema changes.
- Committed: Yes.

**`tests/fixtures/`:**
- Purpose: Stable sample source payloads and expected normalized output.
- Generated: No; checked-in fixtures are used by tests.
- Committed: Yes.

**`data/osm/`:**
- Purpose: Configured location for the road graph cache path (`config/defaults.yaml`, `wildfire_core.config.Settings`).
- Generated: Runtime cache location; no cache file is present in the repository tree.
- Committed: Not detected.

---

*Structure analysis: 2026-10-14*

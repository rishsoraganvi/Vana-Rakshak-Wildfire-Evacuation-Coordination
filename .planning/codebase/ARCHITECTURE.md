---
last_mapped_commit: 568fe4ddfb5bf5d575995eb03ee89ffbeefc939f
last_mapped_at: 2026-10-14
---
<!-- refreshed: 2026-10-14 -->

# Architecture

**Analysis Date:** 2026-10-14

## System Overview

```text
┌───────────────────────────────────────────────────────────────┐
│                  HTTP API: `apps/api_gateway/`                │
│       `main.py` · health endpoints · config router             │
└────────────────────────────┬──────────────────────────────────┘
                             │ settings / readiness
                             ▼
┌───────────────────────────────────────────────────────────────┐
│             Shared foundation: `packages/wildfire_core/`       │
│ config · Pydantic schemas · SQLAlchemy Core · clock · events  │
└──────────────┬───────────────────────┬────────────────────────┘
               │                       │
      ┌────────▼──────────┐   ┌────────▼──────────────────┐
      │ Ingest modules    │   │ Specialist computations  │
      │ `apps/ingest_     │   │ `apps/agents/fire/`       │
      │ worker/`          │   │ `apps/agents/weather/`    │
      └────────┬──────────┘   └────────┬──────────────────┘
               │                       │
               └───────────┬───────────┘
                           ▼
┌───────────────────────────────────────────────────────────────┐
│ PostgreSQL/PostGIS: migrations in `infra/migrations/`         │
│ Redis is provisioned in `docker-compose.yml`; `RedisEvents`    │
│ provides a publish wrapper in `wildfire_core/events.py`        │
└───────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| API application | Creates FastAPI app, settings, database engine, Redis client, and health/config endpoints | `apps/api_gateway/src/api_gateway/main.py` |
| API configuration route | Returns the safe settings projection | `apps/api_gateway/src/api_gateway/routers/config.py` |
| Shared settings and contracts | Loads defaults/environment settings and defines validated data contracts | `packages/wildfire_core/src/wildfire_core/config.py`, `packages/wildfire_core/src/wildfire_core/schemas/` |
| Database access | Defines monitoring table metadata, connection helpers, and SQL write operations | `packages/wildfire_core/src/wildfire_core/db/` |
| Ingestion | Parses external/replay observations, deduplicates hotspots, persists monitoring rows, and evaluates hotspot triggers | `apps/ingest_worker/src/ingest_worker/` |
| Fire specialist | Clusters detections and computes seeded cellular-automaton spread outputs | `apps/ingest_worker/src/ingest_worker/clustering.py`, `apps/agents/fire/src/agent_fire/` |
| Weather specialist | Reads the latest persisted observation and converts it to a weather snapshot | `apps/agents/weather/src/agent_weather/agent.py` |
| Database schema evolution | Creates extensions, AOI, monitoring, incident, trigger, run, shared-state, and audit tables | `infra/migrations/versions/` |

## Pattern Overview

**Overall:** Python workspace monorepo with a shared-core/package boundary and small application packages. Data contracts and infrastructure helpers are shared; API, ingestion, and specialist logic are separated by responsibility.

**Key Characteristics:**
- Packages use a `src/` layout and are workspace members configured in `pyproject.toml`.
- Pydantic models validate observation and Phase 2 contracts; SQLAlchemy Core and explicit SQL perform persistence.
- Alembic migrations are the database schema authority; `wildfire_core.db.models` currently declares only hotspot and weather table metadata.
- The runtime is partially wired: the API application exposes health/configuration, while ingestion and specialist functions are module-level callable services rather than a running coordinator workflow.
- Project-level safety constraints require human approval before dissemination and deterministic validated numeric outputs; the current API does not expose a review or dissemination workflow.

## Layers

**API Layer:**
- Purpose: Expose the current HTTP surface and dependency readiness.
- Location: `apps/api_gateway/src/api_gateway/`
- Contains: FastAPI application factory, health checks, and config router.
- Depends on: Settings and database helpers from `wildfire_core`, plus Redis client.
- Used by: HTTP clients and Docker Compose health checks.

**Application/Domain Services:**
- Purpose: Parse/normalize observations, persist them, evaluate triggers, cluster hotspots, and compute specialist results.
- Location: `apps/ingest_worker/src/ingest_worker/`, `apps/agents/fire/src/agent_fire/`, `apps/agents/weather/src/agent_weather/`
- Contains: FIRMS and weather parsers/services, hotspot deduplication/clustering, fire spread, and weather snapshot retrieval.
- Depends on: Shared schemas/config/database interfaces and scientific/geospatial libraries.
- Used by: Tests and callers; there is no worker process entry point in these packages in the current tree.

**Shared Core:**
- Purpose: Supply configuration, validated cross-package schemas, time abstractions, database access, and a Redis event wrapper.
- Location: `packages/wildfire_core/src/wildfire_core/`
- Contains: `config.py`, `clock.py`, `events.py`, `db/`, `geo/`, and `schemas/`.
- Depends on: Pydantic, SQLAlchemy, Redis, and PyYAML.
- Used by: API, ingestion, and specialist packages.

**Persistence and Infrastructure:**
- Purpose: Provision local PostgreSQL/PostGIS and Redis services and evolve the durable schema.
- Location: `docker-compose.yml`, `infra/docker/`, `infra/postgres/`, `infra/migrations/`
- Contains: Compose services, Dockerfiles, initialization SQL, and ordered Alembic revisions.
- Depends on: Docker images and environment-overridable settings.
- Used by: API, database repository functions, seed script, and integration tests.

## Data Flow

### API Request Path

1. `apps/api_gateway/src/api_gateway/main.py` resolves settings, creates the database engine and Redis client, then builds the FastAPI application.
2. `/api/v1/health/live` returns liveness; `/api/v1/health/ready` calls `readiness` to test PostgreSQL and Redis (`apps/api_gateway/src/api_gateway/health.py`).
3. `/api/v1/config` returns `Settings.safe_projection()` through `apps/api_gateway/src/api_gateway/routers/config.py`.

### Observation Ingestion Path

1. FIRMS CSV parsing produces validated `HotspotObservation` values with metadata (`apps/ingest_worker/src/ingest_worker/firms/parser.py`, `packages/wildfire_core/src/wildfire_core/schemas/monitoring.py`).
2. `ingest_hotspots` deduplicates observations, then calls `upsert_hotspot`; weather ingestion similarly delegates each observation to `upsert_weather` (`apps/ingest_worker/src/ingest_worker/firms/service.py`, `apps/ingest_worker/src/ingest_worker/weather/service.py`).
3. Repository functions upsert into PostgreSQL monitoring tables declared by migration `infra/migrations/versions/0002_monitoring.py`.
4. `record_new_hotspot_trigger` evaluates the threshold and writes incident and trigger rows, coalescing a trigger within its debounce interval (`apps/ingest_worker/src/ingest_worker/triggers.py`).

### Specialist Computation Path

1. `cluster_hotspots` converts observations into coordinates and uses DBSCAN to produce validated `HotspotCluster` records.
2. `compute_fire_spread` consumes a cluster and `WeatherSnapshot`, calls `run_ensemble`, and returns a validated `FireSpreadResult` (`apps/agents/fire/src/agent_fire/agent.py`, `apps/agents/fire/src/agent_fire/ca_model.py`).
3. `get_weather_snapshot` reads a latest non-forecast weather observation and marks it stale after 90 minutes (`apps/agents/weather/src/agent_weather/agent.py`).
4. These functions do not currently connect through an application-level coordinator or persist a complete plan.

**State Management:**
- PostgreSQL is the durable store for monitoring, incidents, triggers, agent run/message records, shared-state snapshots, and audit rows as defined by `infra/migrations/versions/`.
- Redis is configured and used by the API readiness check; `wildfire_core.events.RedisEvents` wraps `ping` and publish operations.
- `SharedState` is a validated versioned set of references and can be saved with `save_shared_state`; it does not itself hold a full materialized plan.
- Fire ensemble randomness is controlled by explicit seeds; `Clock`, `RealClock`, and `SimClock` provide injectable time abstractions.

## Key Abstractions

**Validated Observation Contracts:**
- Purpose: Reject malformed monitoring inputs and carry source/freshness metadata across parsers and persistence.
- Examples: `packages/wildfire_core/src/wildfire_core/schemas/monitoring.py`, `packages/wildfire_core/src/wildfire_core/schemas/metadata.py`.
- Pattern: Pydantic `BaseModel`, `extra="forbid"`, field constraints, and focused validators.

**Phase 2 Domain Results:**
- Purpose: Define typed cluster, weather snapshot, spread, route, audit, and coordinator-plan payloads.
- Examples: `packages/wildfire_core/src/wildfire_core/schemas/phase2.py`.
- Pattern: Pydantic models, constrained values, and `Literal` status/classification fields. Contracts exist for route/plan results; corresponding runtime services are not present in `apps/`.

**Persistence Helpers:**
- Purpose: Encapsulate engine creation, health checks, and observation/shared-state SQL writes.
- Examples: `packages/wildfire_core/src/wildfire_core/db/session.py`, `packages/wildfire_core/src/wildfire_core/db/repositories.py`.
- Pattern: Pass a SQLAlchemy `Engine` into callable repository/service functions; use explicit transaction scopes for writes.

**Settings:**
- Purpose: Merge `config/defaults.yaml` with environment overrides and validate application configuration.
- Examples: `packages/wildfire_core/src/wildfire_core/config.py`.
- Pattern: Pydantic `Settings`, `SecretStr` for credentials, and a dedicated safe projection for API output.

## Entry Points

**FastAPI application:**
- Location: `apps/api_gateway/src/api_gateway/main.py`
- Triggers: Uvicorn/container startup imports module-level `app`; `create_app(settings)` supports constructing an app with explicit settings.
- Responsibilities: Initialize app state with settings/clients and register current health/config routes.

**Offline AOI seeding script:**
- Location: `scripts/seed_demo.py`
- Triggers: Direct script execution with the required `--offline` argument.
- Responsibilities: Insert the configured AOI polygon if it is not already present.

**Migrations:**
- Location: `infra/migrations/env.py` and `infra/migrations/versions/`
- Triggers: Alembic command using `infra/migrations/alembic.ini`.
- Responsibilities: Apply ordered database schema revisions.

**Callable domain modules:**
- Location: `apps/ingest_worker/src/ingest_worker/` and `apps/agents/*/src/`
- Triggers: Imported and called by consumers/tests; no executable worker or agent launcher is present in these packages.
- Responsibilities: Observation parsing/persistence, trigger recording, clustering, and weather/fire calculations.

## Architectural Constraints

- **Runtime:** Python packages use `src/` layouts; `pyproject.toml` configures `uv` workspace members and pytest source paths.
- **Global state:** `apps/api_gateway/src/api_gateway/main.py` creates module-level `app = create_app()`, which constructs engine and Redis clients at import time.
- **Data access:** Migrations define the complete current SQL schema; SQLAlchemy table metadata in `packages/wildfire_core/src/wildfire_core/db/models.py` covers hotspots and weather observations only. Additional tables are accessed through explicit SQL where implemented.
- **Determinism:** Fire computations accept explicit seeds and time-sensitive components can consume the shared `Clock` abstraction.
- **Approval boundary:** The project requires human approval before dissemination, but no approval/dissemination endpoint or coordinator workflow currently exists.
- **External integrations:** Compose provisions PostgreSQL and Redis; this tree contains parsers and configuration for external data but no scheduled/persistent ingestion process.

## Anti-Patterns

### Bypassing Shared Contracts

**What happens:** Passing unvalidated dictionaries between ingestion, domain calculations, or persistence.
**Why it's wrong:** It bypasses range checks, required metadata, and the schema boundary used across packages.
**Do this instead:** Use Pydantic contracts in `packages/wildfire_core/src/wildfire_core/schemas/` at package boundaries.

### Treating Contracts as Implemented Workflows

**What happens:** Assuming `RouteResult` or `CoordinatorPlan` implies route planning or coordinator execution exists.
**Why it's wrong:** These are data contracts only; no matching routing/coordinator implementation or API path is present under `apps/`.
**Do this instead:** Keep architecture claims tied to executable modules and wire new orchestration through a distinct application service before exposing it from `apps/api_gateway/src/api_gateway/`.

## Error Handling

**Strategy:** Validate inputs at Pydantic boundaries, raise standard exceptions for invalid local arguments or unavailable required data, and convert dependency-check failures into readiness status.

**Patterns:**
- Settings and observations validate via Pydantic (`packages/wildfire_core/src/wildfire_core/config.py`, `packages/wildfire_core/src/wildfire_core/schemas/`).
- Database readiness catches connection exceptions and returns `unavailable` (`packages/wildfire_core/src/wildfire_core/db/session.py`).
- Redis readiness catches ping failures and returns a 503 response through the API (`apps/api_gateway/src/api_gateway/health.py`, `apps/api_gateway/src/api_gateway/main.py`).
- Domain functions raise `ValueError` for invalid thresholds and `RuntimeError` when a weather snapshot is absent (`apps/ingest_worker/src/ingest_worker/triggers.py`, `apps/agents/weather/src/agent_weather/agent.py`).

## Cross-Cutting Concerns

**Logging:** Python standard library configuration is invoked by Alembic; application modules currently contain no shared logging abstraction.
**Validation:** Pydantic schemas and settings form the main input/output validation boundary.
**Authentication:** No authentication middleware or authorization layer is present in the current API routes.
**Configuration/security:** Environment overrides are centralized in `wildfire_core.config`; secret values use `SecretStr` and the config endpoint returns a selected safe projection.

---

*Architecture analysis: 2026-10-14*

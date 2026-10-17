---
last_mapped_commit: 568fe4ddfb5bf5d575995eb03ee89ffbeefc939f
last_mapped_at: 2026-10-14
---
# External Integrations

**Analysis Date:** 2026-10-14

## APIs & External Services

**Weather and Fire Observations:**
- Open-Meteo - provider-shaped weather payload parser and fixture/replay data are implemented; no live fetch client or endpoint call is present (`apps/ingest_worker/src/ingest_worker/weather/parser.py`, `tests/fixtures/open_meteo/`).
- NASA FIRMS - FIRMS CSV parser and fixture/replay ingestion are implemented; no live download/API client is present (`apps/ingest_worker/src/ingest_worker/firms/parser.py`, `tests/fixtures/firms/`). Configured source identifiers include VIIRS and MODIS (`config/defaults.yaml`).

**Mapping and Language Models:**
- OpenStreetMap - `OSM_CACHE_PATH` and settlement `osm_id` support are present, but no OSM/Overpass client or graph download implementation is detected (`packages/wildfire_core/src/wildfire_core/config.py`, `infra/migrations/versions/0002_monitoring.py`).
- LLM provider/model names, an enable flag, and a Groq API-key setting exist; no LLM SDK, LangGraph dependency, provider request, or orchestration client is detected (`config/defaults.yaml`, `packages/wildfire_core/src/wildfire_core/config.py`). These settings do not constitute an active external integration.
- `httpx` is declared as a dependency, but application source currently has no external HTTP call sites (`pyproject.toml`, `apps/api_gateway/pyproject.toml`).

## Data Storage

**Databases:**
- PostgreSQL 16 with PostGIS 3.5 - main persistence for AOIs, observations, incidents, clusters, triggers, agent runs/messages, shared-state snapshots, and audit rows (`infra/docker/postgres/Dockerfile`, `infra/migrations/versions/0001_extensions_and_aoi.py`, `infra/migrations/versions/0002_monitoring.py`, `infra/migrations/versions/0003_incidents_and_triggers.py`, `infra/migrations/versions/0004_shared_state_audit.py`).
  - Connection: `DATABASE_URL`, with PostgreSQL component variables used by Compose (`packages/wildfire_core/src/wildfire_core/config.py`, `docker-compose.yml`).
  - Client: SQLAlchemy 2.0.54 with psycopg 3.3.6; schema management uses Alembic 1.20.0 (`packages/wildfire_core/pyproject.toml`, `infra/migrations/`).
- PostgreSQL extensions: PostGIS, pgvector 0.8.6, and pgcrypto are created during database initialization/migration (`infra/postgres/init.sql`, `infra/docker/postgres/Dockerfile`, `infra/migrations/versions/0001_extensions_and_aoi.py`).

**File Storage:**
- Local filesystem path is configured for the OSM graph cache at `OSM_CACHE_PATH`; no remote/object-storage integration is present (`config/defaults.yaml`, `packages/wildfire_core/src/wildfire_core/config.py`).

**Caching:**
- Redis 7.4.2 is provisioned by Compose and accessed with the Redis Python client. The API checks Redis availability; `RedisEvents` wraps publish, but no cache policy or consumer/subscriber is detected (`docker-compose.yml`, `apps/api_gateway/src/api_gateway/main.py`, `apps/api_gateway/src/api_gateway/health.py`, `packages/wildfire_core/src/wildfire_core/events.py`).
  - Connection: `REDIS_URL` (`packages/wildfire_core/src/wildfire_core/config.py`).

## Authentication & Identity

**Auth Provider:**
- Not detected. The current API exposes health and safe configuration endpoints without authentication middleware or identity-provider integration (`apps/api_gateway/src/api_gateway/main.py`, `apps/api_gateway/src/api_gateway/routers/config.py`).
- `JWT_SECRET` appears in `.env.example`, but it is not mapped into application `Settings` and no JWT handling is present (`.env.example`, `packages/wildfire_core/src/wildfire_core/config.py`).

## Monitoring & Observability

**Error Tracking:**
- Not detected; no external error-tracking service or SDK is configured.

**Logs and Health:**
- The API provides liveness and readiness endpoints; readiness checks PostgreSQL and Redis and returns dependency status (`apps/api_gateway/src/api_gateway/main.py`, `apps/api_gateway/src/api_gateway/health.py`).
- Alembic configures console logging for migration commands (`infra/migrations/alembic.ini`). No application metrics, tracing/exporter, or centralized logging integration is detected.

## CI/CD & Deployment

**Hosting:**
- No hosted production platform is specified. Local and CI services are defined in `docker-compose.yml`; the API runs under Uvicorn (`infra/docker/api/Dockerfile`).

**CI Pipeline:**
- GitHub Actions runs on pushes and pull requests; it checks formatting/lint, type-checks core, runs unit tests, and builds/starts the Compose services before applying migrations and running marked integration tests (`.github/workflows/ci.yml`).
- No release, image publishing, or production deployment workflow is present in `.github/workflows/ci.yml`.

## Environment Configuration

**Required env vars:**
- Application configuration includes `DATABASE_URL`, `REDIS_URL`, AOI and pilot identifiers, provider/source selectors, and LLM/OSM settings (`packages/wildfire_core/src/wildfire_core/config.py`, `config/defaults.yaml`).
- Compose uses `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` for database initialization and service connection construction (`docker-compose.yml`).

**Secrets location:**
- `.env` is present and `.env.example` documents configuration names; `.env` contents were not read. The Pydantic settings model wraps database URL, Redis URL, PostgreSQL password, and Groq key as `SecretStr` (`packages/wildfire_core/src/wildfire_core/config.py`).

## Webhooks & Callbacks

**Incoming:**
- None detected; no webhook routes are defined in the current API (`apps/api_gateway/src/api_gateway/main.py`).

**Outgoing:**
- None detected; no webhook delivery or callback client is implemented.

---

*Integration audit: 2026-10-14*

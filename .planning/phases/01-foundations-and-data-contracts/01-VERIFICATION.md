---
phase: 01-foundations-and-data-contracts
verified: 2026-10-05T00:00:00Z
status: passed
score: 12/12 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 10/12
  gaps_closed:
    - "FIRMS/weather persistence now retains raw, origin, and freshness metadata."
    - "New-hotspot trigger debounce now uses timezone-aware datetime arithmetic and is covered by Compose integration assertions."
    - "Shared-state snapshots now persist versioned rows in Postgres and are covered by Compose integration assertions."
  gaps_remaining: []
  regressions: []
---

# Phase 1: Foundations and Data Contracts Verification Report

**Phase Goal:** A reproducible monorepo foundation can start infrastructure, migrate the core schema, load configuration, and represent shared state, clocks, geometry, and typed agent contracts.
**Verified:** 2026-10-05
**Status:** passed
**Re-verification:** Yes — after gap repairs

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Clean Compose starts healthy PostGIS/pgvector, Redis, and FastAPI. | VERIFIED | Compose services reached healthy state; existing Compose foundation coverage passed. |
| 2 | Alembic creates only Phase 1 AOI, monitoring, incident/trigger, shared-state, and audit primitives. | VERIFIED | Clean migration to revision `0004_shared_state_audit` succeeded; schema-boundary coverage remains passing. |
| 3 | Liveness is dependency-free; readiness reports DB/Redis status and introspection excludes secrets. | VERIFIED | Existing Compose health/config integration coverage passed. |
| 4 | CI uses unit tests plus a small Compose smoke suite with no live providers. | VERIFIED | CI configuration and offline fixture-based test setup are present; focused lint/type checks passed. |
| 5 | FIRMS/Open-Meteo raw samples normalize to typed observations with provider/origin/freshness/raw metadata. | VERIFIED | Parser unit coverage passes; both parsers emit strict metadata-bearing observations. |
| 6 | Invalid coordinates, bbox, geometry, and non-UTC times are rejected. | VERIFIED | Existing contract and geometry tests pass. |
| 7 | Seeded fire input/output envelopes are deterministic and expose current/P50/P90, spread, confidence, and settlement risk. | VERIFIED | Strict fire contract and determinism tests pass; runtime fire computation remains Phase 2 scope. |
| 8 | SimClock controls timestamps and freshness; tests use no wall clock. | VERIFIED | SimClock/freshness unit coverage passes. |
| 9 | Offline FIRMS/weather inputs persist idempotently with raw/provider/origin/freshness metadata. | VERIFIED | `0002_monitoring` defines raw/freshness columns; both repositories map and upsert them. FIRMS idempotency integration passed, and a real weather fixture round-trip asserted raw payload, replay origin, and fresh status in Postgres. |
| 10 | Durable uniqueness prevents duplicates across repeated runs. | VERIFIED | FIRMS integration repeated the upsert and asserted two rows; unique constraints and `ON CONFLICT` paths are present. |
| 11 | Threshold crossings open/update incidents and record triggers; below-threshold/stale/unavailable states are explicit. | VERIFIED | Trigger unit tests passed; Compose integration passed for two crossing calls and one coalesced trigger. The debounce cutoff is `detected_at - timedelta(...)`, preserving timezone-aware datetime semantics. |
| 12 | Postgres is durable versioned truth and Redis is only a small health/event boundary. | VERIFIED | `save_shared_state` inserts `(incident_id, version, state)` into `shared_state_snapshots`; Compose integration asserted persisted version `1`. Redis remains isolated to ping/event access. |

**Score:** 12/12 truths verified.

## Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `pyproject.toml`, `uv.lock`, `.env.example` | Pinned workspace and secret-free setup | VERIFIED | Present and used by the existing quality gate. |
| `docker-compose.yml`, `infra/docker/postgres/Dockerfile` | Dual-extension database and healthchecks | VERIFIED | Compose brought all services healthy. |
| `infra/migrations/versions/0001_*.py` through `0004_*.py` | Ordered Phase 1 revisions | VERIFIED | Migration head applied successfully. |
| FastAPI health/config routes | Live, ready, safe AOI/config introspection | VERIFIED | Existing Compose integration coverage passes. |
| `RealClock`/`SimClock` | UTC injected clock | VERIFIED | Implemented and unit-tested. |
| Typed monitoring/state/fire models | Strict versioned contracts | VERIFIED | Implemented and covered by unit tests. |
| FIRMS/Open-Meteo parsers and fixtures | Offline provider-shaped normalization | VERIFIED | Parser tests and fixture round-trips pass. |
| SQLAlchemy mappings/repositories | Typed durable persistence boundary | VERIFIED | Hotspot/weather metadata fields and `save_shared_state` are mapped to Postgres; integration evidence passes. |
| Ingest, freshness, trigger services and seed | Offline Phase 1 ingest path | VERIFIED | FIRMS/weather persistence, trigger debounce, shared snapshots, seed, and quality checks pass. |

## Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| Compose service health | API readiness | `depends_on: service_healthy` and bounded probes | WIRED | Existing Compose health/readiness coverage passes. |
| Alembic chain | Phase 1 tables | `down_revision` chain and SQL migrations | WIRED | Clean migration to head succeeded. |
| Validated settings | Safe projection | `load_settings` -> `safe_projection` -> config route | WIRED | Existing config integration coverage passes. |
| FIRMS parser | Transactional upsert | normalized observation -> `ingest_hotspots` -> `upsert_hotspot` | WIRED | Idempotency and metadata assertions pass. |
| Weather parser | Transactional upsert | normalized observation -> `ingest_weather` -> `upsert_weather` | WIRED | Transient real Postgres round-trip asserted persisted metadata. |
| SimClock/freshness | Incident/trigger | aware datetime cutoff -> trigger persistence | WIRED | Debounce integration test passes with coalesced trigger row. |
| Shared state | Postgres snapshot table | `save_shared_state` -> `shared_state_snapshots` | WIRED | Integration test asserted persisted versioned snapshot. |
| Redis boundary | Health/events only | `RedisEvents` adapter | WIRED | No shared-state durability is delegated to Redis. |

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| FIRMS ingest | hotspot observation | CSV fixture -> parser -> Postgres upsert | Yes | FLOWING; raw/origin/freshness retained. |
| Weather ingest | weather observation | JSON fixture -> parser -> Postgres upsert | Yes | FLOWING; transient Postgres round-trip confirmed raw/origin/freshness. |
| Trigger persistence | incident/trigger rows | threshold input + aware detection time -> Postgres | Yes | FLOWING; coalescing row asserted. |
| Shared state | versioned references | `SharedState` -> `save_shared_state` -> Postgres JSONB | Yes | FLOWING; version `1` asserted in `shared_state_snapshots`. |
| AOI seed | AOI polygon/config | validated settings -> seed command -> PostGIS | Yes | FLOWING. |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Trigger evaluator | `uv run pytest tests/unit/test_triggers.py -q` | 2 passed | PASS |
| FIRMS idempotency | Compose-marked `test_firms_fixture_upsert_is_idempotent` | Passed in focused Compose run | PASS |
| Trigger debounce and shared snapshot | Compose-marked `test_trigger_debounce_and_shared_state_are_durable` | Passed in focused Compose run | PASS |
| Weather metadata persistence | transient `parse_open_meteo` -> `ingest_weather` -> Postgres query | raw=true, origin=replay, freshness_status=fresh; rows cleaned up | PASS |
| Focused lint | `uv run ruff check apps/ingest_worker packages/wildfire_core tests/integration/test_migrations_and_ingest.py` | All checks passed | PASS |
| Core typing | `uv run mypy packages/wildfire_core` | No issues in 16 files | PASS |

## Probe Execution

No phase-declared `probe-*.sh` files were found. No probe execution was required.

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| MON-01 | 01-02, 01-03 | FIRMS polling/AOI dedupe | PARTIAL BY DESIGN | Offline parser, stable identity, Postgres uniqueness, and idempotent ingest pass. Live polling is explicitly deferred by D-09. |
| MON-02 | 01-02, 01-03 | Weather polling and provider/freshness metadata | PARTIAL BY DESIGN | Offline weather normalization and durable metadata persistence pass. Live polling is explicitly deferred by D-09. |
| MON-03 | 01-01, 01-03 | Versioned state and threshold incident lifecycle | SATISFIED FOR PHASE 1 | Trigger integration proves crossing/coalescing; shared-state integration proves versioned Postgres persistence. |
| MON-04 | 01-01, 01-02, 01-03 | Stale/unavailable visibility and no silent below-threshold action | SATISFIED FOR PHASE 1 | Freshness classifier and threshold evaluator tests pass; integrated persistence path passes. |
| FIRE-01 | 01-02 | Hotspot clustering and seeded CA spread horizons | DEFERRED | Phase 1 supplies deterministic contracts; runtime CA is a Phase 2 success criterion. |
| FIRE-02 | 01-02 | Current/P50/P90 risk output and settlement ETA | DEFERRED | Phase 1 supplies output contracts; runtime forecast/risk computation is a Phase 2 deliverable. |

## Test Quality Audit

| Test File | Linked Req | Active | Skipped | Circular | Assertion Level | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `tests/unit/test_firms_parser.py` | MON-01 | Yes | No | No | Value/type | Passes normalization and raw metadata assertions. |
| `tests/unit/test_weather_parser.py` | MON-02 | Yes | No | No | Value/type | Passes normalization and raw/freshness assertions. |
| `tests/unit/test_freshness.py` | MON-04 | Yes | No | No | Value | Passes freshness boundaries. |
| `tests/unit/test_triggers.py` | MON-03/04 | Yes | No | No | Value | Passes threshold decisions. |
| `tests/integration/test_migrations_and_ingest.py` | MON-01..03 | Yes under Compose | Expected skip outside Compose | No | Behavioral/value | Passes FIRMS idempotency, trigger coalescing, and shared snapshot persistence. |

No disabled-only requirement tests, circular fixture generation, unreferenced `TODO`/`FIXME`/`XXX` markers, or placeholder implementations were found in the repaired slice. Weather persistence is proven by the transient real-database check; a permanent weather persistence assertion would be useful follow-up coverage but is not a phase blocker because the repository path and runtime round-trip both pass.

## Anti-Patterns Found

None. The three prior blockers are repaired: monitoring metadata is persisted, trigger debounce uses aware datetime arithmetic, and shared-state writes are durable in Postgres.

## Human Verification Required

N/A — infrastructure/foundation phase with no user-facing elements. All phase acceptance criteria are programmatically verified. Live provider polling remains intentionally deferred under D-09 and is not a human-UAT requirement for this phase.

## Deferred Items

| # | Item | Addressed In | Evidence |
| --- | --- | --- | --- |
| 1 | FIRE-01 runtime clustering and seeded cellular-automata spread | Phase 2 | Phase 2 success criteria require fire CA and risk assessment in the end-to-end hotspot-to-route loop. |
| 2 | FIRE-02 runtime current/P50/P90 forecast and settlement risk computation | Phase 2 | Phase 2 deliverables include P50/P90 forecast data and fire/risk assessment. |

## Gaps Summary

No remaining Phase 1 verification gaps. The previously failed persistence, trigger debounce, and durable shared-state truths are now verified by code inspection and executable checks. Live provider polling and runtime fire computation remain intentional scope deferrals documented by D-09 and the Phase 2 roadmap.

---

_Verified: 2026-10-05T00:00:00Z_
_Verifier: the agent (gsd-verifier)_

# Phase 1: Foundations and Data Contracts Verification Report

**Phase Goal:** A reproducible monorepo foundation can start infrastructure, migrate the core schema, load configuration, and represent shared state, clocks, geometry, and typed agent contracts.
**Verified:** 2026-10-05
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Clean Compose starts healthy PostGIS/pgvector, Redis, and FastAPI. | VERIFIED | `docker compose up -d --build --wait` built all images and reported all three containers healthy; Compose integration health test passed. |
| 2 | Alembic creates only Phase 1 AOI, monitoring, incident/trigger, shared-state, and audit primitives. | VERIFIED | All four revisions upgraded successfully; schema-boundary integration test passed, including SRID/GiST checks and absence of later workflow tables/vector columns. |
| 3 | Liveness is dependency-free; readiness reports DB/Redis status and introspection excludes secrets. | VERIFIED | Compose integration test passed for live, ready, safe config projection, AOI bbox, and secret exclusion. |
| 4 | CI uses unit tests plus a small Compose smoke suite with no live providers. | VERIFIED | `.github/workflows/ci.yml` has separate unit and Compose jobs; tests use fixtures and the live-provider boundary is absent. Ruff, mypy, and unit tests passed locally. |
| 5 | FIRMS/Open-Meteo raw samples normalize to typed observations with provider/origin/freshness/raw metadata. | VERIFIED | Both parsers construct strict Pydantic observations and retain raw payloads; focused parser tests passed. Persistence of all metadata is separately failed below. |
| 6 | Invalid coordinates, bbox, geometry, and non-UTC times are rejected. | VERIFIED | BBox ordering/range, SimClock awareness, observation UTC validators, and bounded coordinate fields are implemented; unit suite passed. |
| 7 | Seeded fire input/output envelopes are deterministic and expose current/P50/P90, spread, confidence, and settlement risk. | VERIFIED | Strict `FireRunInput`, `FirePerimeter`, `FireRunOutput`, and `SettlementRisk` contracts exist with explicit seed/horizons and required fields; fire contract tests passed. Runtime clustering/CA/risk computation is deferred to Phase 2. |
| 8 | SimClock controls timestamps and freshness; tests use no wall clock. | VERIFIED | `SimClock` is injected in parser tests and freshness boundaries; unit suite passed. |
| 9 | Offline FIRMS/weather inputs persist idempotently with raw/provider/origin/freshness metadata. | FAILED | FIRMS idempotency passes, but the database schema/repositories do not persist freshness for hotspots or raw/freshness for weather. |
| 10 | Durable uniqueness prevents duplicates across repeated runs. | VERIFIED | Postgres unique keys and `ON CONFLICT` upserts are present; live Compose FIRMS idempotency test passed. |
| 11 | Threshold crossings open/update incidents and record triggers; below-threshold/stale/unavailable states are explicit. | FAILED | Pure threshold/freshness tests pass, but the live trigger persistence probe fails on the timestamp/float comparison before any incident is created. |
| 12 | Postgres is durable versioned truth and Redis is only a small health/event boundary. | FAILED | Phase 1 tables and Redis ping/publish adapter exist, but shared-state writes use only an in-memory `SnapshotStore`; no durable snapshot repository is wired. |

**Score:** 10/12 truths verified.

## Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `pyproject.toml`, `uv.lock`, `.env.example` | Pinned workspace and secret-free setup | VERIFIED | Workspace/dependencies are pinned and `uv.lock` exists; Compose uses secret defaults rather than checked-in credentials. |
| `docker-compose.yml`, `infra/docker/postgres/Dockerfile` | Dual-extension database, Redis/API healthchecks | VERIFIED | Pinned images/build strategy, PostGIS/vector/pgcrypto setup, healthchecks, and healthy dependency ordering are present and executed successfully. |
| `infra/migrations/versions/0001_*.py` through `0004_*.py` | Four ordered Phase 1 revisions | VERIFIED | Upgrade to head passed and schema-boundary assertions passed. |
| FastAPI health/config routes | Live, ready, safe AOI/config introspection | VERIFIED | Routes are wired from `create_app`; Compose tests passed. |
| `RealClock`/`SimClock` | UTC injected clock | VERIFIED | Implemented and unit-tested. |
| Typed monitoring/state/fire models | Strict versioned contracts | VERIFIED | Pydantic models use forbidden extras, UTC validation, provenance/freshness, explicit seed, horizons, and risk fields. |
| FIRMS/Open-Meteo parsers and fixtures | Offline provider-shaped normalization | VERIFIED | Fixtures and parsers exist; focused and full unit tests passed. |
| SQLAlchemy mappings/repositories | Typed durable persistence boundary | PARTIAL | Hotspot/weather upserts exist, but mappings/repositories omit required metadata and shared-state/incident persistence coverage is incomplete. |
| Ingest, freshness, trigger services and seed | Offline Phase 1 ingest path | PARTIAL | Seed and FIRMS idempotency work; trigger persistence is broken and weather metadata is not retained. |

## Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| Compose service health | API readiness | `depends_on: condition: service_healthy`, bounded DB/Redis probes | WIRED | Healthy startup and readiness integration test passed. |
| Alembic chain | Extensions and Phase 1 tables | `down_revision` chain and SQL migrations | WIRED | Upgrade to head succeeded on a clean volume; schema test passed. |
| Validated settings | Safe projection | `load_settings` -> `safe_projection` -> `/api/v1/config` | WIRED | AOI and cluster are returned while DSNs/secrets are excluded. |
| FIRMS parser | Transactional upsert | normalized observation -> `ingest_hotspots` -> `upsert_hotspot` | WIRED | Live idempotency test passed. |
| Weather parser | Transactional upsert | normalized observation -> `ingest_weather` -> `upsert_weather` | PARTIAL | Upsert is wired but drops raw/freshness metadata. |
| SimClock/freshness | Incident/trigger | clock/classifier -> trigger persistence | NOT WIRED | Trigger persistence fails before insert due to an invalid timestamp cutoff parameter; no integration test covers it. |
| Postgres snapshot/version | Redis boundary | `SharedState`/`SnapshotStore` and `RedisEvents` | PARTIAL | Redis is isolated, but snapshot storage is process-local and not connected to the Postgres snapshot table. |

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| FIRMS ingest | hotspot observation | fixture CSV -> parser -> Postgres upsert | Yes | FLOWING, with freshness metadata loss |
| Weather ingest | weather observation | fixture JSON -> parser -> Postgres upsert | Yes | HOLLOW for raw/freshness persistence |
| AOI seed | AOI polygon/config | validated settings -> `seed_demo.py` -> PostGIS | Yes | FLOWING |
| Shared state | versioned references | `SharedState` -> `SnapshotStore` | No durable DB source | DISCONNECTED from Postgres |
| Fire contracts | input/output envelopes | typed caller-provided references and seed | Contract-only | FLOWING as schema boundary; runtime fire computation deferred |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Unit contracts/services | `uv run pytest tests/unit -q` | 15 passed | PASS |
| Lint | `uv run ruff check .` | All checks passed | PASS |
| Strict core typing | `uv run mypy packages/wildfire_core` | No issues in 16 files | PASS |
| Compose health/schema/idempotency | `COMPOSE_SMOKE=1 uv run pytest tests/integration -m compose -q` | 3 passed, 1 warning | PASS |
| Alembic migration | `uv run alembic -c infra/migrations/alembic.ini upgrade head` | Four revisions applied | PASS |
| Offline AOI seed | `uv run python scripts/seed_demo.py --offline` | Seed completed | PASS |
| Threshold incident persistence | Direct call to `record_new_hotspot_trigger(...)` | PostgreSQL `timestamp with time zone >= double precision` error | FAIL |

## Probe Execution

No phase-declared `probe-*.sh` files were found. No probe execution was required.

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| MON-01 | 01-02, 01-03 | FIRMS polling/AOI dedupe | PARTIAL | Offline parser, stable key, Postgres uniqueness, and idempotent ingest pass; no polling client/interval implementation is present. |
| MON-02 | 01-02, 01-03 | Weather polling and provider/freshness metadata | BLOCKED | Parser emits metadata, but persistence omits raw/freshness and no polling client is present. |
| MON-03 | 01-01, 01-03 | Versioned state and threshold incident lifecycle | BLOCKED | Phase 1 schema exists, but trigger persistence fails at runtime and shared snapshots are not durably written. |
| MON-04 | 01-01, 01-02, 01-03 | Stale/unavailable visibility and no silent below-threshold action | PARTIAL | Readiness and freshness classifier are explicit and unit-tested; integrated trigger gating is blocked by the persistence failure. |
| FIRE-01 | 01-02 | Hotspot clustering and seeded CA spread horizons | DEFERRED | Phase 1 provides seeded input/horizon contracts only; plan explicitly excludes clustering/CA. Phase 2 success criteria explicitly cover fire CA/risk implementation. |
| FIRE-02 | 01-02 | Current/P50/P90 risk output and settlement ETA | DEFERRED | Phase 1 provides output contracts only; runtime forecast/risk computation is explicitly deferred and addressed by Phase 2 fire deliverables. |

## Test Quality Audit

| Test File | Linked Req | Active | Skipped | Circular | Assertion Level | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `tests/unit/test_firms_parser.py` | MON-01 | Yes | No | No | Value/type | Passes parser normalization, not persistence. |
| `tests/unit/test_weather_parser.py` | MON-02 | Yes | No | No | Value/type | Passes parser normalization, not persistence. |
| `tests/unit/test_freshness.py` | MON-04 | Yes | No | No | Value | Passes freshness boundaries. |
| `tests/unit/test_triggers.py` | MON-03/04 | Yes | No | No | Value | Covers pure evaluator only; persistence path absent. |
| `tests/integration/test_migrations_and_ingest.py` | MON-01 | Conditional Compose | Expected skip outside Compose | No | Behavioral/value | Active in verification and passes idempotent FIRMS path. |
| `tests/integration/test_compose_foundation.py` | MON-03/04 | Conditional Compose | Expected skip outside Compose | No | Status/value | Covers health/schema, not triggers or shared-state writes. |

No disabled-only requirement tests or circular fixture-generation patterns were found. The missing trigger integration test and insufficient persistence assertions are the material test gaps.

## Anti-Patterns Found

| File | Pattern | Severity | Impact |
| --- | --- | --- | --- |
| `apps/ingest_worker/src/ingest_worker/triggers.py` | Unix float compared to `timestamptz` | BLOCKER | Threshold incident persistence cannot execute. |
| `packages/wildfire_core/src/wildfire_core/state.py` | Process-local snapshot store for a durable-state requirement | BLOCKER | Shared state is not durable/versioned in Postgres at runtime. |
| `packages/wildfire_core/src/wildfire_core/db/repositories.py` | Metadata fields dropped during upsert | BLOCKER | Freshness/raw provenance cannot be recovered from persisted weather/hotspot rows. |

No unreferenced `TODO`, `FIXME`, `XXX`, placeholder implementation, or console-only implementation markers were found in modified production files.

## Human Verification Required

N/A — infrastructure/foundation phase with no user-facing elements. The blockers above are executable code defects, not manual-UAT items.

## Deferred Items

| # | Item | Addressed In | Evidence |
| --- | --- | --- | --- |
| 1 | FIRE-01 runtime clustering and seeded cellular-automata spread | Phase 2 | Phase 2 success criteria require fire CA and risk assessment in the end-to-end hotspot-to-route loop. |
| 2 | FIRE-02 runtime current/P50/P90 forecast and settlement risk computation | Phase 2 | Phase 2 deliverables include P50/P90 forecast data and fire/risk assessment. |

## Gaps Summary

The repository has a real, reproducible Compose/migration/API foundation and the contract/parser layer is substantive. Phase 1 is not ready to pass because threshold crossings cannot persist an incident due to a timestamp type error, monitoring persistence drops required raw/freshness metadata, and shared-state snapshots are only held in memory despite the durable Postgres requirement. The literal FIRE-01/FIRE-02 runtime behaviors are intentionally deferred to Phase 2; Phase 1 currently supplies their typed contracts.

---

_Verified: 2026-10-05_
_Verifier: the agent (gsd-verifier)_
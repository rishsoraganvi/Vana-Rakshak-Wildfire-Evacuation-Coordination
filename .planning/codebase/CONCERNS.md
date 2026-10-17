---
last_mapped_commit: 568fe4ddfb5bf5d575995eb03ee89ffbeefc939f
last_mapped_at: 2026-10-14
---
# Codebase Concerns

**Analysis Date:** 2026-10-14

## Tech Debt

**Freshness is not propagated from source timestamps:**
- Issue: Both parsers mark every emitted observation `fresh` with age `0`, regardless of acquisition/valid time. The reusable freshness classifier is separate and is not called by either parser.
- Files: `apps/ingest_worker/src/ingest_worker/firms/parser.py`, `apps/ingest_worker/src/ingest_worker/weather/parser.py`, `packages/wildfire_core/src/wildfire_core/state.py`, `packages/wildfire_core/src/wildfire_core/db/repositories.py`
- Impact: Persisted historical or delayed inputs can look current to downstream planning, a safety-relevant mismatch for a workflow that depends on freshness signals.
- Fix approach: Calculate freshness against the injected clock and configured thresholds at ingestion; test old, current, and unavailable source times through parser and persistence paths.

**Weather snapshots are not location-specific:**
- Issue: `get_weather_snapshot(lat, lon, ...)` ignores both coordinates and selects the newest non-forecast row globally. Weather observations are keyed by provider and coordinates, so the selected row need not cover the requested incident.
- Files: `apps/agents/weather/src/agent_weather/agent.py`, `packages/wildfire_core/src/wildfire_core/db/models.py`
- Impact: A valid but geographically unrelated weather row can silently feed the fire model; no-row behavior raises `RuntimeError` rather than producing an explicit unavailable snapshot.
- Fix approach: Select by AOI/location using a documented spatial or nearest-station rule, enforce freshness, and cover mismatched-location and no-data behavior.

**Fire forecast is a simplified, uncalibrated model:**
- Issue: The cellular automaton uses fixed spread/moisture coefficients, a homogeneous grid, and three default seeds; it has no fuel, terrain, barrier, or calibrated local spread inputs. Confidence is derived from variation in burned-cell counts across seeds. Grid spacing converts metres to the same degree increment on both axes and area assumes square cells.
- Files: `apps/agents/fire/src/agent_fire/ca_model.py`, `apps/agents/fire/src/agent_fire/ensemble.py`, `config/defaults.yaml`, `.planning/phases/02-mvp-detection-to-route/02-CONTEXT.md`
- Impact: Output geometry, area, confidence, and spread rate are prototype estimates, not validated operational forecasts. The degree-grid and square-cell approximations also distort geometry/area, increasingly outside the current low-latitude pilot AOI.
- Fix approach: Keep outputs clearly labeled as decision support; quantify error against local observations and benchmark/calibrate before operational use. Document the confidence meaning and use an appropriate projected grid or geodesic cell areas.

**Per-record database transactions limit ingestion throughput:**
- Issue: Each service loops over observations and calls a repository upsert that opens its own `engine.begin()` transaction.
- Files: `apps/ingest_worker/src/ingest_worker/firms/service.py`, `apps/ingest_worker/src/ingest_worker/weather/service.py`, `packages/wildfire_core/src/wildfire_core/db/repositories.py`
- Impact: Large feed batches incur one transaction per row and can be partially persisted if a later row fails. No throughput benchmark is present.
- Fix approach: Add batch upserts in a shared transaction when ingestion volume or atomicity requirements demand it; benchmark against the Phase 2 latency target.

**Weather raw payload is duplicated per hourly row:**
- Issue: `parse_open_meteo` attaches the entire response payload to every hourly observation, and the repository persists that payload on each row.
- Files: `apps/ingest_worker/src/ingest_worker/weather/parser.py`, `packages/wildfire_core/src/wildfire_core/db/repositories.py`, `infra/migrations/versions/0002_monitoring.py`
- Impact: A response with many hours repeats the same JSON in storage and increases write and backup volume. Actual growth is not benchmarked.
- Fix approach: Store the raw response once with a reference from normalized rows, or retain only the row-level raw data required for audit/replay.

**Phase 2 migration plan conflicts with the existing schema:**
- Issue: The current chain already has revision `0004_shared_state_audit`, and that revision creates `agent_runs` with agent/status/input/output columns. Phase 2 Plan 02-02 proposes another `0004` migration and an `agent_runs` table with a different node/run schema.
- Files: `infra/migrations/versions/0004_shared_state_audit.py`, `.planning/phases/02-mvp-detection-to-route/02-02-PLAN.md`, `infra/migrations/env.py`
- Impact: Implementing the plan literally can create duplicate Alembic revision identifiers or attempt to create an already-existing incompatible table; migration upgrade/CI would fail or the audit contract would diverge.
- Fix approach: Add a uniquely identified revision after the current head and explicitly extend or migrate the existing `agent_runs` table rather than recreating it. `uv` is unavailable in the mapping environment, so the Alembic graph was not executed here.

**Configuration accepts unsafe or nonsensical numeric settings:**
- Issue: Settings such as `fire_grid_resolution_m`, `dbscan_eps_deg`, `dbscan_min_samples`, `llm_rationale_max_tokens`, and `llm_request_timeout_s` have no positivity/range constraints.
- Files: `packages/wildfire_core/src/wildfire_core/config.py`
- Impact: Invalid deployment configuration can cause division/index errors, degenerate clustering, or unusable timeout/token limits at runtime.
- Fix approach: Add field constraints and focused invalid-configuration tests, especially for model resolution and clustering parameters.

## Known Bugs

**Trigger coalescing still creates a new incident for every crossing:**
- Symptoms: The trigger function finds a prior trigger in the debounce interval, but always inserts a new incident; it only sets the new trigger's `coalesced_into` field.
- Files: `apps/ingest_worker/src/ingest_worker/triggers.py`, `tests/integration/test_migrations_and_ingest.py`
- Trigger: Record two threshold crossings within the debounce interval; the integration test currently expects two incidents and one coalesced trigger.
- Impact: If debounce is intended to suppress duplicate incident work, the current behavior does not do so and can create duplicate incident records/workflows. Confirm desired semantics before connecting it to the coordinator.
- Workaround: None in the current code.

## Security Considerations

**Compose services use development credentials and unauthenticated Redis:**
- Risk: Compose publishes Postgres and Redis ports on the host, uses a development password fallback for Postgres, and configures Redis without authentication. The API container binds to `0.0.0.0`.
- Files: `docker-compose.yml`, `infra/docker/api/Dockerfile`, `.env.example`
- Current mitigation: Defaults and examples are development-oriented; the API currently exposes health and a safe configuration projection only. `Settings.safe_projection()` does not include database URLs or keys.
- Recommendations: Bind local-only services to loopback for developer use, require injected credentials outside local development, and add network/auth controls before shared or production deployment. No production deployment configuration was detected.

**Authentication and approval controls are not implemented in the current API:**
- Risk: There is no API authentication/authorization or approval/dissemination endpoint in the current source. This is an explicit phase boundary, not a Phase 2 regression.
- Files: `apps/api_gateway/src/api_gateway/main.py`, `apps/api_gateway/src/api_gateway/routers/config.py`, `.planning/phases/02-mvp-detection-to-route/02-CONTEXT.md`, `.planning/ROADMAP.md`
- Current mitigation: The current API surface is limited to health and safe config; project requirements explicitly defer human review/dissemination APIs to Phase 4 and require persisted human approval before dissemination.
- Recommendations: Do not expose plan dissemination or operational instructions until authenticated reviewer roles, exact-version approval checks, validation gates, and append-only approval audit are implemented and tested.

## Performance Bottlenecks

**Fire perimeter construction can become geometry-heavy:**
- Problem: Each non-empty mask cell creates a Shapely box, then all boxes are unioned to produce WKT at each requested percentile/horizon.
- Files: `apps/agents/fire/src/agent_fire/ca_model.py`
- Cause: The default pilot bounding box and 250 m grid imply roughly 230,000 grid cells; large masks can generate many polygons before union. Runtime and memory are not benchmarked.
- Improvement path: Benchmark representative worst-case masks against the five-minute draft target; if needed use raster/vector polygonization and simplify output at a documented tolerance.

**Weather snapshot lookup lacks a location index/filter:**
- Problem: The query orders all non-forecast weather rows by `valid_time` and selects one row.
- Files: `apps/agents/weather/src/agent_weather/agent.py`, `infra/migrations/versions/0002_monitoring.py`
- Cause: No latitude/longitude index exists for weather observations and the query omits location predicates.
- Improvement path: Define the spatial selection rule first, then add the matching index and test query plans at expected data volume.

## Fragile Areas

**External payload parsers assume complete, aligned provider data:**
- Files: `apps/ingest_worker/src/ingest_worker/firms/parser.py`, `apps/ingest_worker/src/ingest_worker/weather/parser.py`
- Why fragile: Required CSV columns and timestamp formats are directly indexed/parsed; weather hourly arrays are indexed without checking equal lengths or malformed values. A malformed row or truncated array can abort the whole parse.
- Safe modification: Validate provider schema and array lengths before constructing observations; define whether invalid rows are rejected individually or fail the batch, and retain regression fixtures.
- Test coverage: Existing parser tests use valid fixtures only (`tests/unit/test_firms_parser.py`, `tests/unit/test_weather_parser.py`).

**Raw SQL migrations are manually managed with no metadata autogeneration:**
- Files: `infra/migrations/env.py`, `infra/migrations/versions/0001_extensions_and_aoi.py`, `infra/migrations/versions/0002_monitoring.py`, `infra/migrations/versions/0003_incidents_and_triggers.py`, `infra/migrations/versions/0004_shared_state_audit.py`
- Why fragile: Migrations create schema through SQL strings and Alembic uses `target_metadata=None`; schema drift is not detected through model metadata. The current Phase 2 plan's revision/table collision makes this especially actionable.
- Safe modification: Inspect current database objects before adding revisions, assign the next unique revision/down-revision, write reversible changes, and run upgrade plus downgrade/upgrade checks in Compose.
- Test coverage: CI runs a Compose migration upgrade and integration tests, but does not test downgrade/upgrade reversibility.

## Scaling Limits

**No ingestion retention or raw-payload lifecycle is defined:**
- Current capacity: Not measured; raw hotspot/weather payloads are persisted in JSONB.
- Limit: Storage growth and retention impact are unknown; weather payload duplication is noted above.
- Scaling path: Establish retention/replay requirements, measure row and payload growth, and add partitioning/archival only when justified by measured volume.

## Dependencies at Risk

**No specific abandoned or known-vulnerable dependency was evidenced in this scan.**
- Files: `pyproject.toml`, `uv.lock`
- Risk: Dependency vulnerability status was not audited; several geospatial/scientific dependencies use lower bounds rather than exact project constraints.
- Impact: Security and reproducibility status beyond the committed lockfile is unknown.
- Migration plan: Not applicable absent an identified at-risk package; run dependency vulnerability and lockfile freshness checks as part of release review.

## Missing Critical Features

**Operational safety workflow remains a future-phase dependency:**
- Problem: Authentication, plan validation, persisted human review, approval, and dissemination guards are absent from the current API/code. The roadmap assigns review/dissemination to Phase 4.
- Blocks: Any safe operational dissemination; this does not block the current Phase 2 draft-only scope.

**Live ingestion orchestration and calibration are not present in the current implementation:**
- Problem: Parser and ingest functions accept supplied payloads, but no scheduled/provider acquisition loop is present in the inspected worker code; the fire model has no local calibration evidence.
- Files: `apps/ingest_worker/src/ingest_worker/firms/`, `apps/ingest_worker/src/ingest_worker/weather/`, `apps/agents/fire/src/agent_fire/ca_model.py`, `.planning/ROADMAP.md`
- Blocks: Claims of continuously current inputs or operationally calibrated forecasts. Live ingestion and calibration remain unverified/deferred in the repository's current phase.

## Test Coverage Gaps

**CI omits several existing test directories:**
- What's not tested: The CI unit command runs only `tests/unit`; it does not run `apps/agents/fire/tests`, `apps/ingest_worker/tests`, or `packages/wildfire_core/tests`.
- Files: `.github/workflows/ci.yml`, `apps/agents/fire/tests/test_ca_model.py`, `apps/ingest_worker/tests/test_clustering.py`, `packages/wildfire_core/tests/test_phase2_schemas.py`
- Risk: Fire model, clustering, and Phase 2 schema regressions can merge without their tests running in the regular unit job. Compose tests cover a different integration slice.
- Priority: High for deterministic/safety-critical outputs; include these directories in the CI pytest invocation.

**Safety-related freshness behavior lacks end-to-end tests:**
- What's not tested: The freshness classifier has boundary tests, but parser tests do not assert stale/unavailable status, and ingestion tests only exercise a fixture marked fresh.
- Files: `tests/unit/test_freshness.py`, `tests/unit/test_firms_parser.py`, `tests/unit/test_weather_parser.py`, `tests/integration/test_migrations_and_ingest.py`
- Risk: The hard-coded fresh metadata can persist without any test failing.
- Priority: High; exercise source timestamp to persisted freshness status for both providers.

---

*Concerns audit: 2026-10-14*

---
phase: 02-mvp-detection-to-route
plan: 03
subsystem: api
status: complete
tags: [fastapi, sqlalchemy, postgresql, pytest, replay, audit]
requires:
  - phase: 02-02
    provides: Coordinator graph, plan persistence, routing, and audit schema
provides:
  - Read-only incident, draft-plan, and audit endpoints
  - Idempotent Coordinator audit persistence helper
  - Fixture-backed replay runner and gated integration/smoke tests
  - Local-only API exposure pending Phase 4 JWT roles
affects: [phase-2-verification, review-api, replay]
actuals:
  tokens: 6500
  tasks: 8
  commits: 7
tech-stack:
  added: []
  patterns:
    - FastAPI routes use request-scoped app.state.engine and strict Pydantic response models
    - Service-backed integration/smoke tests are gated by COMPOSE_SMOKE and required credentials
key-files:
  created:
    - apps/api_gateway/src/api_gateway/routers/incidents.py
    - apps/api_gateway/tests/test_incidents_api.py
    - apps/coordinator/src/coordinator/audit.py
    - apps/coordinator/tests/test_audit.py
    - scripts/replay_demo.py
    - tests/integration/test_coordinator_pipeline.py
    - tests/smoke/test_compose_smoke.py
  modified:
    - apps/api_gateway/src/api_gateway/main.py
    - apps/coordinator/src/coordinator/graph.py
    - apps/agents/routing/tests/test_router.py
    - tests/fixtures/osm/bandipur_stub.graphml
    - pyproject.toml
    - docker-compose.yml
key-decisions:
  - Keep Phase 2 API local-only until Phase 4 implements JWT viewer roles.
  - Use valid Phase 1 incident status 'open' and derive simulation from replay/simulated origin.
  - Preserve the existing agent_runs contract and persist Phase 2 audit fields additively.
requirements-completed: [PLAN-02, PLAT-02, PLAT-06]
coverage:
  - id: D1
    description: Read-only incident, draft-plan, and audit endpoints
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: apps/api_gateway/tests/test_incidents_api.py#test_list_incidents_returns_empty_list_for_fresh_database
        status: pass
      - kind: unit
        ref: apps/api_gateway/tests/test_incidents_api.py#test_plan_endpoint_returns_draft_and_freshness
        status: pass
    human_judgment: true
    rationale: The API is intentionally local-only and has no JWT role enforcement until Phase 4; live Postgres response checks were unavailable.
  - id: D2
    description: Idempotent bulk persistence of Coordinator audit entries
    requirement: PLAT-02
    verification:
      - kind: unit
        ref: apps/coordinator/tests/test_audit.py#test_flush_audit_entries_bulk_inserts_idempotently
        status: pass
    human_judgment: true
    rationale: PostgreSQL conflict behavior was not exercised against the live Compose database.
  - id: D3
    description: Replay demo seeds fixture data and runs the Coordinator pipeline
    requirement: PLAN-02
    verification:
      - kind: other
        ref: python scripts/replay_demo.py with missing GROQ_API_KEY
        status: pass
    human_judgment: true
    rationale: The fail-fast guard passed, but a successful replay requires a live database and Groq API key.
  - id: D4
    description: Coordinator integration and Compose smoke coverage
    requirement: PLAT-06
    verification:
      - kind: unit
        ref: python -m pytest --co -q
        status: pass
    human_judgment: true
    rationale: All tests collected, but the live Groq/Postgres and Compose smoke tests were skipped because Docker and credentials were unavailable.
  - id: D5
    description: Bidirectional Bandipur GraphML fixture and routing coverage
    requirement: PLAN-02
    verification:
      - kind: unit
        ref: apps/agents/routing/tests/test_router.py#test_bundled_graphml_fixture_loads_with_travel_times
        status: pass
    human_judgment: false
metrics:
  duration: 22min
  completed: 2026-10-14
---

# Phase 2 Plan 3: Read-Only API, Audit Persistence, Replay Summary

**Local-only read APIs, idempotent Coordinator audit writes, and a fixture-backed replay path with explicit live-service gates.**

## Performance

- **Duration:** 22 min
- **Started:** 2026-10-14T10:53:02Z
- **Completed:** 2026-10-14T11:15:15Z
- **Tasks:** 8
- **Files modified:** 13

## Accomplishments

- Added read-only `/api/v1/incidents`, `/api/v1/incidents/{id}/plan`, and `/api/v1/audit/{incident_id}` endpoints with pagination, 404 behavior, plan freshness, and simulation status.
- Extracted `flush_audit_entries` with bulk insert and `ON CONFLICT (id) DO NOTHING`.
- Added `scripts/replay_demo.py`, seeded fixture-backed Coordinator integration coverage, and Compose smoke tests.
- Registered `integration` and `smoke` pytest markers and added Coordinator/routing source paths.
- Bound the Compose API port to `127.0.0.1` pending Phase 4 JWT viewer authorization.

## Task Commits

1. **Task 1: Read-only incident API** - `229de29`
2. **Task 2: Idempotent audit persistence helper** - `bc3929e`
3. **Task 3: Bidirectional OSM fixture** - `b2b3ae4`
4. **Task 4: Replay demo** - `98606b7`
5. **Task 5: Groq/Postgres integration test** - `b6ee7a8`
6. **Task 6: Compose smoke tests** - `4bfd640`
7. **Task 7: pytest markers and source paths** - `fa03e84`
8. **Task 8: Roadmap traceability** - recorded in the subsequent tracking commit

## Files Created/Modified

- `apps/api_gateway/src/api_gateway/routers/incidents.py` - Read-only incident, plan, and audit endpoints.
- `apps/coordinator/src/coordinator/audit.py` - Idempotent audit-row batch persistence.
- `scripts/replay_demo.py` - Credential-guarded fixture replay and summary output.
- `tests/integration/test_coordinator_pipeline.py` - Real Groq/Postgres end-to-end test, gated by Compose and credentials.
- `tests/smoke/test_compose_smoke.py` - Replay and local API smoke checks.
- `tests/fixtures/osm/bandipur_stub.graphml` - Three-node, four-edge bidirectional OSMnx fixture.
- `pyproject.toml`, `docker-compose.yml`, and Coordinator graph/API wiring were updated.

## Decisions Made

- The Phase 2 API has no JWT implementation because viewer roles belong to Phase 4. Its Compose port is loopback-only until then.
- Replay uses the existing `incident_status.open` enum and marks `is_simulated` from the incident’s `replay`/`simulated` origin.
- The API reads the existing Phase 1 tables plus Phase 2 `plan_versions` and additive `agent_runs` fields.

## Deviations from Plan

**1. [User-approved scope boundary] Local-only API until Phase 4**
- **Found during:** Task 1
- **Issue:** No JWT viewer dependency exists, while Compose exposed the API on all host interfaces.
- **Resolution:** Keep Phase 2 read-only routes unauthenticated but bind the published port to `127.0.0.1`; JWT roles remain Phase 4 scope.
- **Verification:** Compose configuration parses; offline API tests pass.

**2. Replay schema alignment**
- **Found during:** Task 4
- **Issue:** The plan requested an unsupported `detected` status and `incidents.is_simulated` field.
- **Resolution:** Seed valid `open` incidents with `origin='replay'`; simulation is derived from the persisted origin.
- **Verification:** Offline replay fail-fast and API simulation tests pass; live replay is service-gated.

**Total deviations:** 2 user-approved/schema-alignment changes. **Impact:** Keeps Phase 2 bounded while respecting the current enum and human-review roadmap.

## Issues Encountered

- Docker Desktop’s Linux engine pipe was unavailable, so the live migration, Groq/Postgres integration, and Compose smoke tests were not run.
- `GROQ_API_KEY` is blank in the local environment; replay exits early with a clear setup error.
- The API intentionally has no JWT role enforcement until Phase 4; Compose exposure is restricted to loopback.

## User Setup Required

Set `GROQ_API_KEY` and start the Compose services to run the live integration/replay/smoke gates. These were not needed for offline tests.

## Next Phase Readiness

- All three Phase 2 plans are implemented and unit/static checks pass.
- Phase 2 goal verification remains pending; it must account for the unavailable live database/Groq gates.
- Phase 3 planning follows only after Phase 2 verification is recorded.

---
*Phase: 02-mvp-detection-to-route*
*Completed: 2026-10-14*

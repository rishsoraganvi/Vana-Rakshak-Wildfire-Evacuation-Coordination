---
phase: 02-mvp-detection-to-route
plan: 02
subsystem: coordination
status: complete
tags: [python, osmnx, networkx, shapely, langgraph, groq, alembic, postgresql]
requires:
  - phase: 02-01
    provides: Fire CA, weather snapshot, clustering, and shared Phase 2 schemas
provides:
  - Cached OSMnx GraphML road graphs and fire-weighted routing
  - LangGraph Coordinator nodes with per-node audit capture
  - Groq rationale adapter with deterministic fallback
  - Versioned draft-plan and additive agent-run persistence
  - Trigger-to-hotspot identity and AOI-boundary exit selection
affects: [phase-2-api, replay, audit, routing]
actuals:
  tokens: 9500
  tasks: 7
  commits: 8
tech-stack:
  added: [OSMnx 2.1.1, NetworkX 3.7, LangGraph 1.2.15, Groq 1.7.0]
  patterns:
    - Linear LangGraph nodes mutate a typed state and append JSON-serializable audit entries
    - OSM road graphs are loaded from GraphML cache or downloaded once and cached
key-files:
  created:
    - apps/agents/routing/pyproject.toml
    - apps/agents/routing/src/agent_routing/graph.py
    - apps/agents/routing/src/agent_routing/costs.py
    - apps/agents/routing/src/agent_routing/router.py
    - apps/agents/routing/tests/test_router.py
    - apps/coordinator/pyproject.toml
    - apps/coordinator/src/coordinator/graph.py
    - apps/coordinator/src/coordinator/runner.py
    - apps/coordinator/src/coordinator/state.py
    - apps/coordinator/src/coordinator/llm/groq_adapter.py
    - apps/coordinator/tests/test_graph_structure.py
    - apps/coordinator/tests/test_groq_adapter.py
    - infra/migrations/versions/0005_phase2_plan_versions.py
    - tests/fixtures/osm/bandipur_stub.graphml
  modified:
    - pyproject.toml
    - uv.lock
    - requirements.txt
    - apps/ingest_worker/src/ingest_worker/triggers.py
    - packages/wildfire_core/src/wildfire_core/schemas/phase2.py
    - packages/wildfire_core/tests/test_phase2_schemas.py
    - tests/unit/test_triggers.py
key-decisions:
  - RouteResult accepts exactly one cluster or settlement origin; the Coordinator supplies a cluster origin.
  - OSM nodes nearest the four AOI boundaries are used as exit candidates because no explicit OSM exit tags are configured.
  - Existing agent_runs is extended additively; full CoordinatorPlan data is stored in plan_data JSONB.
  - The Phase 2 migration is revision 0005 because revision 0004 already exists.
requirements-completed: [PLAN-01, PLAN-02]
coverage:
  - id: D1
    description: Cached road graph loading, fire penalties, and routes to safe AOI-boundary exits
    requirement: PLAN-02
    verification:
      - kind: unit
        ref: apps/agents/routing/tests/test_router.py#test_bundled_graphml_fixture_loads_with_travel_times
        status: pass
      - kind: unit
        ref: apps/agents/routing/tests/test_router.py#test_apply_fire_penalties_increases_cost_inside_p50_perimeter
        status: pass
    human_judgment: true
    rationale: Live OSM coverage and real-terrain exit suitability were not tested; the configured boundary-exit policy requires domain review.
  - id: D2
    description: Eight-node Coordinator graph and audited plan assembly path
    requirement: PLAN-01
    verification:
      - kind: unit
        ref: apps/coordinator/tests/test_graph_structure.py#test_graph_has_all_eight_nodes
        status: pass
    human_judgment: true
    rationale: The full node pipeline was not exercised against a live Postgres database.
  - id: D3
    description: Grounded Groq rationale request and deterministic fallback behavior
    verification:
      - kind: unit
        ref: apps/coordinator/tests/test_groq_adapter.py#test_generate_rationale_uses_grounded_payload_and_trims_response
        status: pass
      - kind: unit
        ref: apps/coordinator/tests/test_groq_adapter.py#test_generate_rationale_falls_back_on_groq_error
        status: pass
    human_judgment: false
  - id: D4
    description: Versioned draft-plan storage and additive Coordinator audit fields
    verification:
      - kind: other
        ref: python -m alembic -c infra/migrations/alembic.ini upgrade head --sql
        status: pass
    human_judgment: true
    rationale: Offline SQL generation passed, but a live PostgreSQL migration could not run because the Docker engine was unavailable.
  - id: D5
    description: Trigger details retain the exact hotspot IDs loaded by the Coordinator
    verification:
      - kind: unit
        ref: tests/unit/test_triggers.py#test_new_hotspot_trigger_records_exact_hotspot_ids
        status: pass
    human_judgment: false
metrics:
  duration: 94min
  completed: 2026-10-14
---

# Phase 2 Plan 2: OSM Graph, Route Utility, Coordinator v0 Summary

**OSMnx-backed, fire-weighted boundary routing and an eight-node LangGraph Coordinator with bounded Groq rationale and durable draft/audit schema.**

## Performance

- **Duration:** 94 min
- **Started:** 2026-10-14T09:14:10Z
- **Completed:** 2026-10-14T10:47:40Z
- **Tasks:** 7
- **Files modified:** 25

## Accomplishments

- Added the `agent-routing` workspace package for cached OSM graphs, fire-perimeter penalties, nearest-node lookup, and route classification.
- Added Coordinator state, eight LangGraph nodes, runner, Groq rationale adapter, and deterministic error fallback.
- Added trigger-linked hotspot IDs, full JSONB draft plan storage, and additive audit metadata on the existing `agent_runs` table.
- Added a deterministic Bandipur GraphML fixture and mocked/unit coverage for routing, graph structure, rationale fallback, schemas, and trigger mapping.

## Task Commits

1. **Task 1: OSM road graph package and route utility** - `f06b7e1`
2. **Task 2: Groq rationale adapter** - `f8bfd4b`
3. **Task 3: Coordinator state contract** - `3941f85`
4. **Task 4: Coordinator nodes and trigger observation mapping** - `c9af785`
5. **Task 5: LangGraph runner** - `0dff34b`
6. **Task 6: Additive plan and audit migration** - `f1822dd`
7. **Task 7: Routing tests and GraphML fixture** - `ec4162f`

**Related route-policy correction:** `2c901c8` (`fix(02-02): route fire clusters to AOI boundary exits`).

## Files Created/Modified

- `apps/agents/routing/` - Workspace package for OSM graph caching, edge costs, routing, and tests.
- `apps/coordinator/` - Coordinator package, LangGraph nodes/runner, Groq adapter, and tests.
- `infra/migrations/versions/0005_phase2_plan_versions.py` - Versioned plan table and additive audit columns.
- `packages/wildfire_core/src/wildfire_core/schemas/phase2.py` - Cluster-origin route contract.
- `apps/ingest_worker/src/ingest_worker/triggers.py` - Optional exact hotspot-ID trigger details.
- `tests/fixtures/osm/bandipur_stub.graphml` - Offline road graph fixture.
- `pyproject.toml`, `uv.lock`, `requirements.txt` - Workspace/dependency updates.

## Decisions Made

- A route origin must identify exactly one settlement or fire cluster; this Coordinator uses cluster IDs.
- With no configured OSM exit tags, the Coordinator targets safe road nodes nearest each AOI boundary side.
- Existing `agent_runs` remains the source of audit rows; the migration adds Phase 2 columns rather than replacing its existing schema.
- `plan_versions.plan_data` stores the full typed draft in addition to queryable summary columns.

## Deviations from Plan

### User-Approved Contract and Schema Changes

**1. Route origin contract**
- **Found during:** Task 1
- **Issue:** The planned cluster-centroid router could not construct `RouteResult`, which required a settlement ID.
- **Resolution:** Added mutually exclusive `origin_cluster_id` and `origin_settlement_id` fields; user approved cluster-origin routes.
- **Verification:** Shared schema tests and routing tests passed.

**2. Trigger observation linkage**
- **Found during:** Task 4
- **Issue:** Trigger rows stored only count/threshold, so the Coordinator could not select hotspot rows belonging to an incident.
- **Resolution:** Store exact hotspot IDs in trigger `details`; user approved this minimal link.
- **Verification:** `tests/unit/test_triggers.py` passes.

**3. Existing audit schema and plan payload**
- **Found during:** Task 4/6
- **Issue:** Migration `0004_shared_state_audit` already creates `agent_runs` with a different schema, and the proposed plan table did not retain fire/route detail.
- **Resolution:** Added revision `0005`, extended `agent_runs` additively, and stored the full draft in `plan_data` JSONB; user approved both decisions.
- **Verification:** Alembic head resolution and offline SQL rendering passed.

**4. Route destination policy**
- **Found during:** Task 7
- **Issue:** No explicit OSM exit markers were available; an arbitrary safe interior node would not be a defensible evacuation destination.
- **Resolution:** Use safe road nodes nearest the four configured AOI boundaries; user approved this policy.
- **Verification:** Boundary-selection test and routing suite passed.

**Total deviations:** 4 user-approved contract/persistence decisions. **Impact:** Keeps incident provenance and route destinations explicit without replacing legacy database structures.

## Issues Encountered

- Live Alembic upgrade against PostgreSQL was not run because Docker Desktop’s Linux engine pipe was unavailable. Offline SQL rendering passed.
- Real Groq and live OSM network calls were not run; adapter behavior and GraphML cache behavior are covered with deterministic tests/fixtures.
- `uv` generated tracked `.egg-info` during editable installs; generated metadata was removed and `*.egg-info/` is now ignored.

## User Setup Required

None for unit tests. Live Groq/database integration still requires a valid `GROQ_API_KEY` and running Compose services.

## Next Phase Readiness

- Plan 02-02 implementation and unit coverage are complete.
- Plan 02-03 is next and depends on this Coordinator and persistence layer.
- Live PostgreSQL migration verification remains blocked until Docker is available.

---
*Phase: 02-mvp-detection-to-route*
*Completed: 2026-10-14*

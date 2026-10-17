---
phase: 03-capacity-aware-coordinated-planning
plan: 10
subsystem: coordinator
tags: [langgraph, asyncio, parallel-dispatch, per-cluster-weather, audit, versioned-persistence, plan-01, plan-07, plan-08]
requires: [03-03, 03-04, 03-05, 03-06, 03-07, 03-08, 03-09]
provides:
  - "coordinator.deps: CoordinatorDeps (settings, repository, graph_loader, fire_fn, clock, rationale_fn, chooser_factory, run-scoped scratch), default_chooser_factory, default_deps"
  - "coordinator.dispatch: run_specialists (asyncio.gather + to_thread + wait_for, ToolResult envelope, running-loop guard)"
  - "coordinator.graph: make_nodes(deps) with the ten Phase 3 nodes, NODE_ORDER, snap_shelters"
  - "coordinator.runner: build_graph(deps), run_coordinator(incident_id, run_id, *, trigger_id, deps) with stream-based audit flush on failure"
  - "coordinator.state: JSON-serializable CoordinatorState and initial_state"
  - "coordinator.audit: each row written with its own agent (CAST(:agent AS agent_name))"
  - "tests: pipeline_factory.py shared builders, test_pipeline_phase3.py, test_dispatch.py, test_weather_per_cluster.py, live test_audit_agents_db.py"
affects: [03-11, 03-12]
tech-stack:
  added: []
  patterns: ["node closures over an injected deps dataclass", "no SQL in graph nodes (repository only)", "private event loop closed without waiting for timed-out threads", "run-scoped scratch for non-serializable objects"]
key-files:
  created:
    - apps/coordinator/src/coordinator/deps.py
    - apps/coordinator/src/coordinator/dispatch.py
    - apps/coordinator/tests/pipeline_factory.py
    - apps/coordinator/tests/test_pipeline_phase3.py
    - apps/coordinator/tests/test_dispatch.py
    - apps/coordinator/tests/test_weather_per_cluster.py
    - tests/integration/test_audit_agents_db.py
  modified:
    - apps/coordinator/src/coordinator/graph.py
    - apps/coordinator/src/coordinator/runner.py
    - apps/coordinator/src/coordinator/state.py
    - apps/coordinator/src/coordinator/audit.py
    - apps/coordinator/src/coordinator/repository.py
    - apps/agents/weather/src/agent_weather/agent.py
    - apps/agents/weather/tests/test_weather_agent.py
    - apps/coordinator/tests/test_audit.py
    - apps/coordinator/tests/test_graph_structure.py
    - apps/coordinator/tests/test_pipeline_offline.py
key-decisions:
  - "run_specialists runs on a private event loop that is closed directly (loop.close shuts the default executor down with wait=False) instead of asyncio.run, which would wait for a timed-out specialist's thread and defeat the timeout; the running-loop case hops to a one-worker thread"
  - "Weather is looked up per cluster at its centroid; a missing reading becomes preflight failure weather_unavailable:<cluster_id> plus a PlanAlert, never a substitute snapshot, and plan_draft fails the plan closed naming the cluster while other clusters' weather stays in provenance"
  - "A failed ToolResult becomes preflight failure specialist_unavailable:<tool>:<code>; when routing is unavailable an empty-graph RoutingContext lets plan_draft return the failed draft"
  - "Shelters are snapped after the group origins and moved to the nearest free node within the snap limit when they would share a node with a group origin (handoff from 03-09: co-located legs are unroutable)"
  - "write_audit flushes, then calls mark_trigger_handled with the last assemble_plan/replan_no_change entry id (FK to agent_runs); the trigger is left unhandled when the run ended in an error"
  - "No clusters means no plan: plan_evacuation sets draft None, assemble_plan records the error, nothing is persisted"
  - "A no-material-change re-run writes an assemble_plan row and a replan_no_change row and creates no version (D-16)"
requirements-completed: []
status: complete
duration: 60min
completed: 2026-10-17
actuals:
  tokens: 31700
  tasks: 3
  commits: 7
---

# Phase 3 Plan 10: Coordinator rewiring Summary

The LangGraph coordinator now runs the ten-node Phase 3 pipeline (ingest, cluster, per-cluster weather, fire, risk, parallel specialists, planning core, grounded rationale, versioned persistence, audit) on injected dependencies, so an incident persists a validated `pending_review` or `failed` plan offline with an in-memory repository, and a crashing run still leaves its audit trail.

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 (tracer) | Ten-node coordinator, deps, parallel dispatch, runner, state, offline end-to-end tests | 37806ab |
| 2 (RED) | Failing tests: dispatch timeout, per-entry audit agent, failed-run flush | c5818ee |
| 2 (GREEN) | Private-loop dispatch hardening, audit agent column, live agent test | 81e6f87 |
| 3 (RED) | Failing tests: per-cluster weather, snapshot age_min | 58ac83c |
| 3 (GREEN) | age_min on every snapshot (weather agent and in-memory repository) | 300b379 |
| 3 | Phase 2 coordinator tests migrated to the Phase 3 pipeline | ac71fed |

Tracer gate (auto mode active): the tracer verify (`test_pipeline_phase3.py`) passed after the commit and in every later run, so expansion proceeded.

## What changed

- `graph.py` is rewritten as `make_nodes(deps)`. It holds no SQL (`grep -cE "\btext\(|from sqlalchemy"` prints 0); every read and write goes through `deps.repository`. The Phase 2 AOI-exit helpers and the single-route node are gone; `build_footprint` replaces the WKT-union helper.
  - `run_weather`: sorted by (-point_count, cluster_id), one `weather_for` call per centroid with origin, provider, clock time and `weather_max_distance_km`.
  - `assess_risk`: footprint union, `assess_risk` groups, rescue and P90-only alerts, `population_unknown` and `fire_unavailable` failures.
  - `dispatch_specialists`: `run_specialists` with a shelter candidate listing and a routing preparation (graph load, edge statuses, per-horizon costs, group origin snap). One audit row per specialist with agent `shelter` or `traffic_routing`, written on the coordinator thread after the gather.
  - `plan_evacuation`: builds `PlanInputs` (including `cluster_risk`, so V7's cluster check runs, and the known settlement and shelter ids) and calls `plan_draft`; each LLM chooser call gets its own `choose_fix_strategy` audit row with model metadata.
  - `generate_rationale`: calls the injected rationale function on `compact_plan_summary` for a valid draft; a failed draft gets no LLM call and fallback reason `plan_failed`.
  - `assemble_plan`: `build_freshness`, `build_provenance` (params snapshot, shelter snapshot, settlement sources), `finalize_plan`, then the D-16 gate. On `CapacityRecheckFailed` the plan is persisted once as `as_failed`; on `StateVersionConflict` the state error is `state_version_conflict` and nothing is written.
  - `write_audit`: flush first, `mark_trigger_handled` after.
- `dispatch.py`: each specialist is timed, wrapped in `wait_for(to_thread(fn))` and returned as `ToolResult` (`timeout` retryable; `exception:<Type>` not retryable with a 200-character message). Results are keyed by name in sorted order. Specialists must be side-effect-free reads because `wait_for` cannot stop a worker thread.
- `runner.py`: `stream_mode="values"` keeps the last state; on an exception it appends a `run_failed` row, flushes (idempotent) and re-raises; scratch is released in `finally`.
- `audit.py`: `CAST(:agent AS agent_name)` with `entry.get("agent", "coordinator")`.
- `agent_weather` and `InMemoryPlanningRepository.weather_for` set `age_min` (never negative) on every snapshot.

## Verification

- `pytest apps packages tests/unit -q`: 450 passed, 1 skipped (baseline 433 passed, 1 skipped).
- `ruff check .`: clean.
- `mypy apps/coordinator/src` (with `--ignore-missing-imports`): no issues. `mypy packages/wildfire_core apps/agents/shelter/src/agent_shelter apps/coordinator/src`: only the 16 pre-existing errors in `packages/wildfire_core/tests/test_phase2_schemas.py`.
- Live (COMPOSE_SMOKE=1, 127.0.0.1): `tests/integration/test_audit_agents_db.py` passed in 2.7 s and removed its incident and audit rows.
- Not run live: the full coordinator integration test and the replay demo. They call `run_coordinator(incident_id, run_id)` (still valid) but read Phase 2 state keys and need a built OSM graph; plan 03-11 updates them and 03-12 runs the OSM build.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Shelter snapping avoids group origin nodes**
- **Found during:** Task 1 (handoff from 03-09)
- **Issue:** A shelter snapped onto a settlement's node gives a zero-length leg that `plan_core.leg_costs` treats as unreachable, so real data could silently lose a legitimate shelter.
- **Fix:** `snap_shelters` moves such a shelter to the nearest free node outside the perimeter within the snap limit; if none exists it keeps its node.
- **Files modified:** apps/coordinator/src/coordinator/graph.py
- **Commit:** 37806ab

**2. [Rule 3 - Blocking] Dispatch uses a private event loop instead of `asyncio.run`**
- **Found during:** Task 2 (RED test for the timeout)
- **Issue:** `asyncio.run` waits for the default executor at shutdown, so a timed-out specialist still held the coordinator until its thread returned.
- **Fix:** `loop.run_until_complete` on a new loop, then `loop.close()` (executor shutdown without waiting). `asyncio.gather`, `asyncio.to_thread` and `wait_for` are unchanged.
- **Files modified:** apps/coordinator/src/coordinator/dispatch.py
- **Commit:** 81e6f87

**3. [Rule 2 - Missing critical functionality] In-memory repository now sets `age_min`**
- **Found during:** Task 3
- **Issue:** The twin of `get_weather_snapshot` omitted `age_min`, so offline runs and the real path would differ.
- **Fix:** Same `max(0, int(age_min))` in `InMemoryPlanningRepository.weather_for` (file not in the plan's list).
- **Files modified:** apps/coordinator/src/coordinator/repository.py
- **Commit:** 300b379

**4. [Rule 2 - Missing critical functionality] Live audit-agent test added**
- **Issue:** The `CAST(:agent AS agent_name)` change touches a Postgres enum; the offline test only inspects SQL text.
- **Fix:** `tests/integration/test_audit_agents_db.py` writes shelter, traffic_routing and coordinator rows, checks them and cleans up.
- **Commit:** 81e6f87

**Plan expectation not met as written:** the plan listed the Task 2 `test_pipeline_phase3.py` failed-run test under Task 1's file; it was added in the Task 2 RED commit.

## Known Stubs

None.

## Issues Encountered

- `ruff format apps/coordinator` reformatted `test_groq_adapter.py` (not part of this plan); the two changed hunks were reverted by hand, so that file is unchanged in the commits. A `git checkout` of the other reformatted files was refused by the permission layer, so formatting-only changes to `audit.py`, `test_audit.py` and `test_graph_structure.py` ride along with their intended edits.
- Until plan 03-11, `scripts/replay_demo.py` and `tests/integration/test_coordinator_pipeline.py` still target the Phase 2 state shape (`routes`, `rationale`); they were not touched here.

## Threat Flags

None. No new endpoints or trust boundaries; T-03-10-01 to T-03-10-06 are mitigated as planned (per-cluster fail-closed weather, specialist failure becomes a failed plan, run_failed audit flush, specialists return values only, wait_for timeout with error envelope, material-change gate).

## Self-Check: PASSED

- Created files exist: deps.py, dispatch.py, pipeline_factory.py, test_pipeline_phase3.py, test_dispatch.py, test_weather_per_cluster.py, test_audit_agents_db.py.
- Commits present: 37806ab, c5818ee, 81e6f87, 58ac83c, 300b379, ac71fed.

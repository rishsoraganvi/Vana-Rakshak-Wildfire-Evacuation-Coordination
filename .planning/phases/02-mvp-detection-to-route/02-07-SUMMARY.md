---
phase: 02-mvp-detection-to-route
plan: 07
subsystem: coordinator-routing
tags: [coordinator, fire-ca, routing, gap-closure, cr-03, hi-01, plat-06]
requires: [02-04, 02-05, 02-06]
provides:
  - "CoordinatorPlan.fire_results (min length 1) and CoordinatorState.fire_results: one FireSpreadResult per DBSCAN cluster"
  - "run_fire_ca simulates every cluster in deterministic (-point_count, cluster_id) order"
  - "compute_route_node penalises the graph with the union of all current and P50 1h perimeters"
  - "Route origins from nearest_node_outside(union current perimeter) with warnings; least-exposure blocked route choice (_blocked_exposure_s)"
  - "Offline real CA + routing pipeline test on the bundled fixture graph"
affects: [02-VERIFICATION]
tech-stack:
  added: []
  patterns: ["union geometry penalisation across all active fires", "tuple-ranked blocked candidates (exposure, travel time, node id)"]
key-files:
  created: []
  modified:
    - packages/wildfire_core/src/wildfire_core/schemas/phase2.py
    - packages/wildfire_core/tests/test_phase2_schemas.py
    - apps/coordinator/src/coordinator/state.py
    - apps/coordinator/src/coordinator/runner.py
    - apps/coordinator/src/coordinator/graph.py
    - apps/coordinator/tests/test_pipeline_offline.py
    - scripts/replay_demo.py
    - tests/integration/test_coordinator_pipeline.py
key-decisions:
  - "Assumption-delta decision: promote. fire_results replaces the singular fire_result in schema, state, runner, demo and tests; no second 'primary' field is kept"
  - "Every cluster is routed on one graph penalised by the union of all fires, so no route can be rated safe through another cluster's fire"
  - "On the 3-node stub fixture the replay route is truthfully 'blocked' (only exit crosses the burning node); fixture and penalties not touched"
requirements-completed: []
status: complete
duration: 40min
completed: 2026-10-17
actuals:
  tokens: 60000
  tasks: 3
  commits: 6
---

# Phase 2 Plan 07: Per-cluster fire simulation and outside-fire routing Summary

Every hotspot cluster now gets its own CA ensemble result, all routing runs against the union of every cluster's current and P50 1h perimeters, routes start at the nearest road node outside the fire, and when nothing is safe the coordinator keeps the blocked route with the least time inside fire.

## Tasks

| # | Task | Commits |
|---|------|---------|
| 1 | Tracer: per-cluster CA, union-penalised routing, fire_results persisted and sent to the rationale (CR-03) | 99dee38 (RED), 9c30917 |
| 2 | Outside-fire origin and least-exposure blocked route (HI-01 coordinator half) | add9221 (RED), a13d2da |
| 3 | Real CA + routing offline pipeline test; demo and live test moved to fire_results (PLAT-06) | bc256d7 |

Tracer gate (auto mode active): the tracer's verify (coordinator + schema tests) was re-run after the commit and passed, so expansion proceeded.

## What changed

- phase2.py: `CoordinatorPlan.fire_results: tuple[FireSpreadResult, ...] = Field(min_length=1)` replaces `fire_result`. Tests: `test_coordinator_plan_default_status_draft` updated, `test_coordinator_plan_requires_fire_results` added.
- state.py / runner.py: `fire_results: list[dict]`, initialised to `[]`.
- graph.py:
  - `run_fire_ca` calls `compute_fire_spread` for every cluster; largest-cluster selection removed.
  - `_union_wkt` (shapely `unary_union`) feeds `apply_fire_penalties` and `_aoi_boundary_exit_nodes`; audit inputs carry `fire_cluster_ids`.
  - `generate_rationale_node` and `assemble_plan` use all fire results (the Groq payload excludes WKT per 02-06, so it stays compact per cluster).
  - Origin via `nearest_node_outside` with two warnings (moved / all nodes inside the fire); `_blocked_exposure_s` ranks blocked candidates by (exposure, travel time, destination id).
- replay_demo.py prints `Fire CA : <n> cluster(s) | <area> km2 affected | confidence ...` and `Routes : <n> computed (blocked: 1)`.
- Integration test asserts `len(fire_results) == len(clusters) >= 1` in state and plan_data; 02-06 fallback/model_metadata assertions kept.

## Verification

- Offline: 92 passed, 7 skipped (baseline 87/7; 5 new tests). ruff clean on apps/coordinator, packages/wildfire_core, scripts, tests. mypy on apps/agents/routing/src + apps/coordinator/src: 0 non-import-untyped errors.
- Live (Compose up, `COMPOSE_SMOKE=1`): full suite 99 passed. The Coordinator integration test passes with Groq answering (the test fails on `is_llm_fallback`); smoke tests pass.
- `scripts/replay_demo.py` (LLM_ENABLED=true LLM_PROVIDER=groq exported): `Fire CA : 1 cluster(s) | 3.75 km2 affected | confidence low`, `Routes : 1 computed (blocked: 1)`, `LLM Model : groq/openai/gpt-oss-20b`, `LLM Fallback : No`, 8 audit entries, 2 warnings (origin moved, no safe route).
- Real-CA offline test: about 24 s on this machine (plan estimated about 15 s).

## Deviations from Plan

None - plan executed as written. Minor: the offline real-CA test resolves the fixture path from `__file__` instead of a cwd-relative path, so it does not depend on the working directory.

## Known Stubs

None.

## Threat Flags

None. T-02-07-01 (union penalties recorded and asserted), T-02-07-02 (outside-fire origin, least-exposure choice) and T-02-07-04 (fire_results persisted, invariant test) are covered by tests.

## Deferred (per plan)

MD-07 (plan-version race), MD-08 (debounced triggers), MD-03 (first non-blocked candidate wins).

## Self-Check: PASSED

Commits 99dee38, 9c30917, add9221, a13d2da, bc256d7 are in git log; all modified files exist; `grep` acceptance checks (no `max(clusters, key=`, no `"fire_result"` key, `unary_union` x2+, `_blocked_exposure_s` defined, `nearest_node_outside(` x2) hold.

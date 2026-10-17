---
phase: 02-mvp-detection-to-route
plan: 05
subsystem: routing
tags: [fire-penalty, dijkstra, shapely, gap-closure]
requires: []
provides:
  - "apply_fire_penalties using full edge geometry (intersects) for blocked and P50 exposure"
  - "compute_route two-phase search: unblocked first, deterministic least-blocked fallback"
  - "nearest_node_outside(graph, lat, lon, perimeter_wkt) -> int | None"
affects: [02-07]
tech-stack:
  added: []
  patterns: ["networkx weight callables returning None to hide hops", "shapely.prepare for repeated intersects"]
key-files:
  created: []
  modified:
    - apps/agents/routing/src/agent_routing/costs.py
    - apps/agents/routing/src/agent_routing/router.py
    - apps/agents/routing/src/agent_routing/__init__.py
    - apps/agents/routing/tests/test_router.py
key-decisions:
  - "D-06 preserved: FIRE_PENALTY_BLOCKED stays inf; blocked classification still means a selected edge has infinite penalised cost"
  - "Fallback weights blocked edges at 1e6 x max(travel_time, 1) so the least-exposure path is chosen deterministically"
  - "nearest_node_outside uses covers (boundary counts as covered) and equirectangular distance, no osmnx call"
requirements-completed: [PLAN-02, PLAT-06]
status: complete
duration: 20min
completed: 2026-10-17
actuals:
  tokens: 12000
  tasks: 2
  commits: 2
---

# Phase 2 Plan 05: Full-edge fire exposure and rankable blocked routes Summary

Fire exposure is now tested on the whole edge geometry (OSM LineString or endpoint chord) and compute_route ranks unblocked paths first, falling back to the least-blocked path, with a new nearest_node_outside primitive for 02-07.

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 | Tracer: full-geometry fire exposure, proven on the bundled fixture route (CR-02) | 6f801d3 |
| 2 | Rankable blocked routing and nearest_node_outside (HI-01, library half) | 48e9c7b |

## What changed

- costs.py: midpoint `contains` replaced with `intersects` on the edge geometry; endpoints inside, crossings and boundary touches are blocked (inf), P50 exposure gives `penalty_near x travel_time`. Perimeters are `shapely.prepare`d.
- router.py: `BLOCKED_FALLBACK_COST_FACTOR = 1_000_000.0`, `_unblocked_weight` (hides all-inf hops) and `_least_blocked_weight`; `compute_route` runs unblocked first then least-blocked, picks each hop's parallel edge with the same transformed cost, and keeps classification and `fire_penalty_edges` semantics. New `nearest_node_outside`.
- `agent_routing.__all__` exports `nearest_node_outside`.
- Tests: 5 CR-02 tests (including the review's bundled-fixture probe, now "blocked") and 3 HI-01 route tests plus 5 nearest_node_outside tests.

## Verification

- Routing tests: 25 passed. Full offline suite: 77 passed, 7 skipped (baseline 64/7).
- Ruff clean on apps/agents/routing; mypy shows only the 4 pre-existing networkx import-untyped errors.
- RED confirmed for Task 1 (5 failures on old midpoint code). Task 2 RED was a collection ImportError (nearest_node_outside missing), which fails all tests in the module before GREEN.
- Tracer gate: auto mode active; tracer verify passed end to end before expansion.

## Deviations from Plan

None - plan executed as written. `ruff format --check` flags pre-existing formatting in graph.py and the existing fixture-path blocks in test_router.py (not in acceptance criteria; not touched).

## Known Stubs

None.

## Threat Flags

None. T-02-05-01 and T-02-05-02 mitigated as planned; MD-01, MD-02, MD-03 remain deferred as listed in the plan.

## Self-Check: PASSED

- costs.py, router.py, __init__.py, test_router.py exist and are committed.
- Commits 6f801d3 and 48e9c7b exist.

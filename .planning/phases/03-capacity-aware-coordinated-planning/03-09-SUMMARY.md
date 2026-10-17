---
phase: 03-capacity-aware-coordinated-planning
plan: 09
subsystem: planning-core
tags: [min-cost-flow, bpr, msa, k-paths, resolver, fallback-planner, hypothesis, validators, plan-03, plan-04, plan-07]
requires: [03-01, 03-05, 03-06, 03-07]
provides:
  - "coordinator.planning.params: PlanningParams (frozen), from_settings, snapshot (flat sorted keys for PlanProvenance.params)"
  - "coordinator.planning.plan_core: RoutingContext, PlanInputs, Constraints, AssignmentResult, PlanOutcome, build_assignment, validate_assignment, violation_lines, plan_draft"
  - "coordinator.planning.resolver: ChooserDecision, StrategyChooser, deterministic_chooser, llm_chooser, resolve, ResolverOutcome"
  - "coordinator.planning.fallback_planner: greedy_fallback"
  - "tests: planning_factory.py shared builders, test_plan_core.py, test_resolver.py, test_fallback_planner.py, test_plan_core_properties.py"
affects: [03-10, 03-11, 03-12]
tech-stack:
  added: []
  patterns: ["pure library core with no LangGraph or DB", "bounded plain for-loop resolver", "single validation entry point shared by every plan producer", "per-run graph copy for congestion and attempt-local edge exclusion"]
key-files:
  created:
    - apps/coordinator/src/coordinator/planning/params.py
    - apps/coordinator/src/coordinator/planning/plan_core.py
    - apps/coordinator/src/coordinator/planning/resolver.py
    - apps/coordinator/src/coordinator/planning/fallback_planner.py
    - apps/coordinator/tests/planning_factory.py
    - apps/coordinator/tests/test_plan_core.py
    - apps/coordinator/tests/test_resolver.py
    - apps/coordinator/tests/test_fallback_planner.py
    - apps/coordinator/tests/test_plan_core_properties.py
  modified:
    - apps/coordinator/src/coordinator/llm/groq_adapter.py
    - apps/coordinator/tests/test_llm_menu.py
key-decisions:
  - "Every producer (flow, each resolver loop, fallback) is validated through plan_core.validate_assignment, which calls the module-level run_structural_validators; the spy invariant monkeypatches that one name"
  - "AssignmentResult carries the final congested per-run graph and paths_available per leg, so validators see the congested times the routes were built on and the resolver knows when next_path has no further path"
  - "next_path moves a violating leg to rank+1 and, when no further path exists, excludes the violating edge on the per-run graph (ranks restart for that leg); rematch bans violating pairs; split halves the per-pair cap of violating groups; V3 P90 flags are never repair targets"
  - "A strategy with nothing to do records not_applicable, still consumes its loop and skips the rebuild"
  - "Failed-draft failure_reasons use finalize_plan's line format, so finalize_plan's own violation lines dedupe against them; fallback-only lines are prefixed 'fallback planner:'"
  - "Co-located origin and shelter nodes are treated as unreachable because a PlanRoute needs at least two nodes"
  - "Fallback reasons: insufficient_capacity, no_safe_route (reachable with capacity but no strictly safe path), no_reachable_shelter"
requirements-completed: []
status: complete
duration: 55min
completed: 2026-10-17
actuals:
  tokens: 19200
  tasks: 3
  commits: 4
---

# Phase 3 Plan 09: Deterministic planning core Summary

A pure planning library that matches groups to shelters by min-cost flow over ETA-aware costs, picks the first safe of k=3 paths per leg, re-routes through up to three MSA-damped BPR passes, validates with V1-V7, then runs a bounded next_path / rematch / split resolver (or the LLM's enum choice), a different greedy fallback planner, and finally a failed draft that names each unplaceable group.

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 | Tracer: PlanningParams, build_assignment, plan_draft with preflight, zero-group and V1-V7 gate | e649753 |
| 2 (RED) | Failing tests for resolver and fallback planner | 8b019ae |
| 2 (GREEN) | resolver.py, fallback_planner.py, full plan_draft wiring, fix-menu key regex fix | 5c12fe7 |
| 3 | Hypothesis properties and the validate-every-producer spy | b505b8d |

Tracer gate (auto mode active): the tracer verify (`test_plan_core.py`) passed after the commit and again in every later run, so expansion proceeded.

## What changed

- `params.py`: `PlanningParams` mirrors the config coefficients (frozen pydantic). `snapshot()` flattens `lane_capacity_vph.<class>`, turns tuples into lists and sorts keys so it fits `PlanProvenance.params`.
- `plan_core.py`:
  - `build_assignment` works on a `graph.copy()`, applies attempt-local excluded edges (blocked, infinite fire multipliers, refreshed horizon costs), then loops `range(congestion_passes)`: cost matrix, `match_groups_to_shelters` with banned pairs and per-pair caps, safe-first k-path selection starting at the leg's rank floor, flows, `msa_blend(prev, new, i + 1)`, `apply_congestion`, and an early stop when the sorted leg signature is unchanged.
  - Routes are built from the final pass on the final congested graph (eta = ceil(congested_s / 60), horizon from the LegCost, `p90_flag_edge_indices`, non-open edge status snapshot, lon/lat path).
  - `plan_draft`: preflight failures (given or an origin node that is missing or not in the graph) fail closed before any matching. Zero groups give a valid draft with the "No settlement buffer intersects the P50 forecast" warning. Otherwise flow, V1-V7, resolver, fallback, failed draft. A congestion warning is added when max v/c exceeds 1.0.
- `resolver.py`: `resolve` is `for loop in range(params.conflict_max_loops)`. The chooser only returns an enum; targets come from sorted blocking violations. `llm_chooser` wraps `choose_fix_strategy` (always keeping its model metadata for the 03-10 audit) and falls back to the fixed order for a missing or out-of-menu answer. `PlanOutcome.llm_calls` carries the metadata.
- `fallback_planner.py`: groups sorted by (priority, -persons, group_id), cheapest strictly safe (shelter, path) with remaining capacity, greedy splitting, one congestion evaluation, `passes_used = 1`. Unplaceable groups carry a reason.
- Tests: 8 plan_core tests, 17 resolver tests (including applier unit tests and the LLM payload shape), 7 fallback tests, 9 property and spy tests, plus one new `test_llm_menu` test.

## Verification

- `pytest apps packages tests/unit -q`: 433 passed, 1 skipped (baseline 391 passed, 1 skipped; 42 new tests).
- `test_plan_core_properties.py` alone: about 30 s (limit 60 s). Property mix over 60 generated instances: about 54% valid, 38% failed, about 8% fallback, 0 to 3 resolver steps all seen.
- `ruff check apps packages tests scripts`: clean. `ruff format --check` clean on every new file.
- `mypy` on `coordinator/planning` and `coordinator/llm` (with the routing source dir on MYPYPATH): only the known networkx stub import errors; no new errors in src.
- No network, no `.env`, no Docker; every Groq call is mocked (`choose_fix_strategy` is monkeypatched).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fix-menu violation-key regex rejected real validator codes**
- **Found during:** Task 2 (LLM payload test)
- **Issue:** `choose_fix_strategy` (plan 03-07) accepted keys matching `^V[1-8]:[a-z_]+$`, but V3's code `p50_before_arrival` contains digits, so the first LLM-enabled V3 failure would have raised `ValueError` instead of choosing a strategy.
- **Fix:** key pattern is now `^V[1-8]:[a-z][a-z0-9_]*$` (must still start with a letter, so uuids and names stay rejected). Added `test_validator_codes_with_digits_are_valid_keys`.
- **Files modified:** apps/coordinator/src/coordinator/llm/groq_adapter.py, apps/coordinator/tests/test_llm_menu.py
- **Commit:** 5c12fe7

**2. [Rule 3 - Blocking] AssignmentResult needed more than the planned fields**
- **Issue:** validators must run on the congested graph the routes were built on, and the resolver must know whether another path exists.
- **Fix:** added `graph` and `paths_available` to `AssignmentResult`; `PlanInputs.known_*_ids` default to ids derived from groups and candidates when not supplied.
- **Commit:** e649753

**3. [Rule 3 - Blocking] Shared test builders and helper module not in the plan's file list**
- **Fix:** `apps/coordinator/tests/planning_factory.py` (params, routing context, group and shelter builders) used by all four planning test files.
- **Commit:** e649753

### Notes

- `plan_draft` imports the resolver and fallback modules inside the function because both build on `plan_core` (circular otherwise).
- Task 1 committed a `plan_draft` that fails closed after V1-V7; Task 2 replaced that branch, as the plan describes.
- The failing-test commit (8b019ae) had a ruff E501 in two test lines; the GREEN commit contains the fix.
- In the scenario where the only reachable shelter lies inside the P50 forecast, the resolver's rematch bans it and the matcher reports `no_reachable_shelter`; the fallback then adds the more precise `fallback planner: ... no_safe_route` line. Both appear in `failure_reasons`.

## Known Limitations

- A settlement snapped onto the same node as a shelter cannot form a `PlanRoute` (minimum two nodes) and is treated as unreachable. Plan 03-10's snapping should avoid co-locating them, or a zero-length route representation should be decided.
- `next_path` edge exclusion is graph-wide for the rest of the attempt, so one group's violating edge is also hidden from other groups in that attempt.
- Convergence of the BPR passes is capped, not guaranteed (RESEARCH Pattern 4); V3 is the final guard.

## Known Stubs

None.

## Threat Flags

None. These are pure functions with no new endpoints, I/O or trust boundaries. T-03-09-01..05 are mitigated: every producer is gated by V1-V7 with the spy invariant and Hypothesis properties (01), safe-first selection then next_path/rematch (02), the LLM returns an enum only and targets come from sorted violations with a payload-shape test (03), `range(conflict_max_loops)` and `range(congestion_passes)` with a loop-cap property (04), and `used_fallback` plus `resolver_steps[].chosen_by` are recorded (05).

## Self-Check: PASSED

- Files exist: params.py, plan_core.py, resolver.py, fallback_planner.py, planning_factory.py, test_plan_core.py, test_resolver.py, test_fallback_planner.py, test_plan_core_properties.py.
- Commits exist: e649753, 8b019ae, 5c12fe7, b505b8d.

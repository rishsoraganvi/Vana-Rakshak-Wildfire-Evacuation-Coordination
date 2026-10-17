---
phase: 03-capacity-aware-coordinated-planning
plan: 06
subsystem: risk-and-validators
tags: [fire-risk, validators, hypothesis, shapely, plan-03, plan-04, plan-08]
requires:
  - "03-02: ForecastFootprint/LoadedFootprint, buffer_metric, to_metric, nearest_horizon_h, plan contracts (ValidationResult, ViolationRecord, EvacueeGroup, PlanAlert)"
  - "03-05: agent_routing.costs.edge_geometry and the nearest-horizon end-of-edge rule"
provides:
  - "agent_fire.risk: assess_risk, RiskAssessment (groups, rescue_alerts, p90_only_alerts, unknown_population)"
  - "coordinator.validators.route_checks: check_v1_paths, check_v2_blocked, check_v3_forecast"
  - "coordinator.validators.capacity_checks: check_v4_capacity, check_v5_complete, check_v6_dispatches"
  - "coordinator.validators.integrity_checks: check_v7_entities"
  - "coordinator.validators.runner: ValidationContext, run_structural_validators, has_blocking_failure, violation_summary"
affects: [03-08, 03-09, 03-10, 03-12]
tech-stack:
  added: []
  patterns: ["pure decision functions returning ValidationResult", "independent geometric re-check instead of trusting routing attributes", "Hypothesis iff-properties for safety invariants"]
key-files:
  created:
    - apps/agents/fire/src/agent_fire/risk.py
    - apps/agents/fire/tests/test_risk.py
    - apps/coordinator/src/coordinator/validators/__init__.py
    - apps/coordinator/src/coordinator/validators/_common.py
    - apps/coordinator/src/coordinator/validators/route_checks.py
    - apps/coordinator/src/coordinator/validators/capacity_checks.py
    - apps/coordinator/src/coordinator/validators/integrity_checks.py
    - apps/coordinator/src/coordinator/validators/runner.py
    - apps/coordinator/tests/test_validators.py
    - apps/coordinator/tests/test_validator_properties.py
    - apps/coordinator/tests/validator_factory.py
  modified: []
key-decisions:
  - "assess_risk interpolates ETA as clamp(t_A + d_A / rate * 60, t_A, t_B) floored to minutes, using the metric distance from the settlement buffer to the previous perimeter; an empty previous perimeter gives t_B and a non-positive rate gives t_A (replaces research assumption A9)"
  - "Unknown population is only reported for settlements that are actually at risk; rescue and P90-only alerts are emitted regardless of population"
  - "V2 and V3 test edge_geometry against the footprint directly, never the routing zone attributes, so they are independent of the producer"
  - "V1 compares the path ends to both the route origin/destination node and the group origin / shelter candidate node when those are known"
  - "violation_summary is keyed by validator and code only (e.g. V3:p50_before_arrival), so no ids or names can reach an LLM payload"
requirements-completed: []
status: complete
duration: 40min
completed: 2026-10-17
actuals:
  tokens: 31000
  tasks: 3
  commits: 4
---

# Phase 3 Plan 06: Risk assessment and structural validators V1-V7 Summary

The Fire agent's `assess_risk` turns a forecast footprint and the settlement registry into evacuee groups with interpolated ETA and priority, rescue alerts for burning settlements and P90-only warnings, while pure validators V1-V7 independently check routes, capacity, completeness, vehicles and ids, with Hypothesis iff-properties for capacity, completeness and double-booking.

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 | Tracer: assess_risk plus V1-V3 on the synthetic graph | d0c00dd |
| 2 | Behaviour tests for risk semantics (D-02, D-20, D-21) | 303f48c |
| 3 (RED) | Failing tests for V4-V7, runner and properties | 626a105 |
| 3 (GREEN) | V4-V7, full runner, violation summary | 2abd054 |

Tracer gate (auto mode active): the tracer verify (`test_validators.py`, 7 tests) passed after the commit and again in the final run, so expansion proceeded.

## What changed

- `risk.py`: loads the footprint once and visits settlements sorted by id. A point covered by the current union becomes a `needs_rescue_response` alert and no group. A buffer touching current gives `buffer_in_current`, priority 1, ETA 0. Otherwise the first horizon in (1, 3, 6) whose P50 hits the buffer gives `inside_p50_{h}h`, priority 1/2/3 and an interpolated ETA. A P90-only hit gives a `p90_only_exposure` alert naming the earliest horizon. At-risk settlements with population None or below 1 go to `unknown_population`. `group_id == settlement_id`, `origin_node` stays None.
- `route_checks.py`: V1 (missing_edge, origin_mismatch, destination_mismatch), V2 (blocked_edge from edge status, enters_current_perimeter from edge geometry), V3 (per-edge end-of-edge arrival on `congested_time` with fallback to `travel_time`, `nearest_horizon_h`, P50 hit fails with p50_before_arrival, P90 hit alone flags with p90_before_arrival). Every violation carries group, shelter and edge.
- `capacity_checks.py`: V4 (over_capacity, not_a_candidate, route_assignment_mismatch), V5 (group_unassigned with residual persons and reason defaulting to insufficient_capacity, group_over_assigned), V6 (empty passes, duplicates give vehicle_double_booked).
- `integrity_checks.py`: V7 (unknown_settlement, unknown_shelter, unknown_node, unknown_cluster, route_without_assignment).
- `runner.py`: `ValidationContext`, `run_structural_validators` (V1..V7 in order), `has_blocking_failure` (any `fail`; a V3 flag does not block), `violation_summary`.
- Tests: 15 risk tests, 17 validator unit tests and 3 Hypothesis properties (`max_examples=200`): V4 passes iff every shelter is within capacity, V5 passes iff every group sum equals its persons, V6 fails iff a vehicle id repeats.

## Verification

- `pytest apps packages tests/unit -q`: 372 passed, 1 skipped (baseline 337 passed, 1 skipped; 35 new tests).
- `ruff check apps packages tests scripts`: clean; new files formatted with `ruff format`.
- `mypy apps/agents/fire/src apps/coordinator/src/coordinator/validators`: only the known environment errors (networkx stubs missing, and `agent_routing` not resolvable when mypy is invoked from the repo root, which `coordinator/graph.py` already hits). No errors from the new logic.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `run_structural_validators` needed a place for cluster ids**
- **Found during:** Task 3
- **Issue:** V7 checks cluster ids, but the planned runner signature has no cluster input.
- **Fix:** added an optional keyword `clusters_referenced: Sequence[str] = ()` at the end of the signature. Callers passing nothing get no cluster check, so plan 03-10 must pass it.
- **Commit:** 2abd054

**2. [Rule 3 - Blocking] Shared helper module and test factory not in the plan's file list**
- **Fix:** added `validators/_common.py` (one `build_result` used by all seven checks, avoids per-module `type: ignore`) and `tests/validator_factory.py` (shared builders for the unit and property tests, same style as `plan_factory.py`).
- **Commit:** d0c00dd, 626a105

### Notes

- Task 2 followed TDD, but `assess_risk` was already fully implemented by the tracer, so the Task 2 tests passed on first run and no RED commit exists for it. Task 3 has a genuine RED commit (collection errors on the missing modules).
- The interpolation test accepts 89 or 90 for the 90-minute case because the metric buffer polygon and the reprojected box can differ by a fraction of a metre before flooring.

## Known Stubs

None.

## Threat Flags

None. These are pure functions with no new endpoints, I/O or trust boundaries. T-03-06-01..05 are mitigated: V2 and V3 use geometry directly with unit tests for the fail cases, V4-V6 have iff-properties, V7 checks every id, unknown population is reported (the fail-closed gate lands in plan 03-09), and `violation_summary` carries code counts only (unit test asserts no ids or names).

## Self-Check: PASSED

- Files exist: risk.py, test_risk.py, validators/{__init__,_common,route_checks,capacity_checks,integrity_checks,runner}.py, test_validators.py, test_validator_properties.py, validator_factory.py.
- Commits exist: d0c00dd, 303f48c, 626a105, 2abd054.

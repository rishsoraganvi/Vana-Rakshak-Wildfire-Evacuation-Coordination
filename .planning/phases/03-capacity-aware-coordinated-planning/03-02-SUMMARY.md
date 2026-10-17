---
phase: 03-capacity-aware-coordinated-planning
plan: 02
subsystem: contracts
tags: [pydantic, schemas, integrated-plan, geo, shapely, pyproj, config, plan-08, plan-03, plan-04]
requires: []
provides:
  - "wildfire_core.schemas.plan: SettlementRecord, ShelterRecord, ShelterCandidate, ExcludedShelter, EvacueeGroup, PlanAlert, EdgeStatusEntry, PlanRoute, ShelterAssignment, Dispatch, ViolationRecord, ValidationResult, ClusterRisk, ShelterSnapshot, ForecastFootprint, PlanFreshness, PlanProvenance, ResolverStep, PlanDraft, IntegratedPlan (plan_schema_version 3.0), PlanDiff"
  - "wildfire_core.schemas.tools: ToolError, ToolResult envelope (ok == error is None)"
  - "wildfire_core.geo.horizons: HORIZONS_H, nearest_horizon_h (ties go later; shared by routing and V3)"
  - "wildfire_core.geo.footprint: build_footprint, LoadedFootprint, load_footprint (prepared geometries), to_metric, from_metric, buffer_metric (EPSG:32643)"
  - "Settings and config/defaults.yaml Phase 3 block with validator (D-03, D-08, D-09, D-19, D-21)"
  - "WeatherSnapshot.age_min (optional), AuditEntry.agent (default coordinator)"
affects: [03-03, 03-04, 03-05, 03-06, 03-07, 03-08, 03-09, 03-10, 03-11, 03-12]
tech-stack:
  added: []
  patterns: ["frozen extra=forbid pydantic models with tuple collections", "schema-level safety invariants via model_validator", "typed wrappers around untyped shapely/pyproj"]
key-files:
  created:
    - packages/wildfire_core/src/wildfire_core/schemas/plan.py
    - packages/wildfire_core/src/wildfire_core/schemas/tools.py
    - packages/wildfire_core/src/wildfire_core/geo/horizons.py
    - packages/wildfire_core/src/wildfire_core/geo/footprint.py
    - packages/wildfire_core/tests/test_plan_schemas.py
    - tests/unit/test_geo_footprint.py
    - tests/unit/test_config_phase3.py
  modified:
    - packages/wildfire_core/src/wildfire_core/schemas/phase2.py
    - packages/wildfire_core/src/wildfire_core/config.py
    - config/defaults.yaml
key-decisions:
  - "S5 and D-11 are enforced inside IntegratedPlan: pending_review requires exactly V1..V8 in order with none failing and no failure_reasons; failed requires no routes or assignments and at least one reason"
  - "freshness and provenance are required fields with no default, so no code path can build a plan without them"
  - "nearest_horizon_h is implemented with the two midpoints (120 and 270 minutes) so ties go to the later horizon"
  - "fix_menu_order must be exactly next_path, rematch, split, so a mark-unassigned strategy cannot be configured (D-09)"
requirements-completed: []
status: complete
duration: 35min
completed: 2026-10-17
actuals:
  tokens: 30000
  tasks: 3
  commits: 4
---

# Phase 3 Plan 02: Phase 3 contracts, shared horizon/footprint helpers, config block Summary

Typed Phase 3 plan contracts with the S5 ("no pending_review without V1-V8") and D-11 ("failed plan carries nothing approvable") invariants and required freshness/provenance enforced in the schema itself, a single shared nearest-horizon rule, perimeter unions with EPSG:32643 metric buffering, and a validated config block holding every Phase 3 coefficient.

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 | Tracer: horizon rule, footprint union, first IntegratedPlan JSON round trip | 9f101f8 |
| 2 (RED) | Failing tests for plan invariants, tool envelope, phase2 additions | a167ffb |
| 2 (GREEN) | Plan validators, ToolResult, WeatherSnapshot.age_min, AuditEntry.agent | 33bbb9a |
| 3 | Phase 3 Settings block, defaults.yaml, config tests | ae5096d |

Tracer gate (auto mode active): the tracer verify (`tests/unit/test_geo_footprint.py`) passed after commit and again within the final suite, so expansion proceeded.

## What changed

- `schemas/plan.py`: all plan-level models are frozen with `extra="forbid"` and tuple collections. Cross-field rules: `ValidationResult` (replaced only V8, flag only V3, fail needs a reason), `EvacueeGroup` (group_id == settlement_id, persons >= 1), `ShelterCandidate` (available == max(0, usable - occupancy)), `PlanRoute` (edge keys == nodes - 1, only safe/caution), `PlanDraft` (valid needs V1-V7 present and none failing; failed needs reasons and no routes/assignments), `IntegratedPlan` (S5 and D-11 as above).
- `schemas/tools.py`: `ToolError` and `ToolResult` envelope following Rules 2.5.
- `schemas/phase2.py`: additive only. `WeatherSnapshot.age_min` is optional so Phase 2 `plan_data` still validates; `AuditEntry.agent` defaults to `coordinator` and uses the migration 0004 `agent_name` values. `CoordinatorPlan` is untouched.
- `geo/horizons.py`: `nearest_horizon_h` raises `ValueError` on negative or NaN input.
- `geo/footprint.py`: generalises coordinator `_union_wkt` across all seven perimeter fields; module-level `pyproj` transformers use `always_xy=True`; shapely and pyproj values are wrapped with `cast` so `mypy --strict` stays clean.
- `config.py` and `config/defaults.yaml`: the Phase 3 block with a `model_validator` bounding every coefficient (usable factor, P50 >= P90 >= 1, k_paths, passes, loops, exact fix menu, lane capacity default key, debounce, IoU, positives, LLM control temperature <= 0.2). `route_fire_penalty_near` is kept and commented as superseded for Phase 3 routing.

## Verification

- `pytest apps packages tests/unit -q`: 186 passed, 1 skipped (baseline 126 passed, 1 skipped; 60 new tests).
- `ruff check packages/wildfire_core tests/unit`: clean.
- `mypy packages/wildfire_core`: 16 errors, all in the pre-existing `packages/wildfire_core/tests/test_phase2_schemas.py`. No new errors in src or in the new tests.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Tracer test used untyped-ignore comments that mypy flagged**
- **Found during:** Task 2
- **Issue:** An unused `type: ignore` and a bad literal argument in `test_plan_schemas.py` raised new mypy errors.
- **Fix:** Removed the ignore and passed the invalid agent through a dict.
- **Files modified:** packages/wildfire_core/tests/test_plan_schemas.py
- **Commit:** 33bbb9a

**2. [Sequencing note] Models split across Task 1 and Task 2**
- Task 1 needed an `IntegratedPlan`, which references most component models, so those were written without validators in the tracer commit. Task 2 added the validators after a RED commit (import error on the missing `schemas.tools` module). `EvacueeGroup.persons` was `ge=0` in the tracer and tightened to `ge=1` in Task 2.

## Deferred Issues

- `mypy packages/wildfire_core` still reports 16 errors in `packages/wildfire_core/tests/test_phase2_schemas.py` (pre-existing, out of scope).
- `ruff format --check` flags several pre-existing files (`db/models.py`, `db/repositories.py`, `state.py`, a docstring in `phase2.py`). Not touched by this plan; new files are formatted.

## Known Stubs

None.

## Threat Flags

None. No new endpoints, auth paths or trust boundaries. T-03-02-01..04 are mitigated in code and tests; T-03-02-05 holds (no individual-level fields in any model).

## Self-Check: PASSED

- Files exist: plan.py, tools.py, horizons.py, footprint.py, test_plan_schemas.py, test_geo_footprint.py, test_config_phase3.py.
- Commits exist: 9f101f8, a167ffb, 33bbb9a, ae5096d.

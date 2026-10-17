---
phase: 02-mvp-detection-to-route
plan: 04
subsystem: fire-model
tags: [cellular-automata, wind-convention, spread-metrics, gap-closure]
requires: []
provides:
  - "CA wind kernel using meteorological FROM direction (wind_from_deg)"
  - "_spread_metrics: front-advance rate and snapping-invariant direction"
  - "FireSpreadResult.spread_direction_deg nullable"
affects: [02-05, 02-06, 02-07]
tech-stack:
  added: []
  patterns: ["FROM->TOWARD conversion in a single place (_wind_factor)"]
key-files:
  created: []
  modified:
    - apps/agents/fire/src/agent_fire/ca_model.py
    - apps/agents/fire/src/agent_fire/ensemble.py
    - apps/agents/fire/tests/test_ca_model.py
    - packages/wildfire_core/src/wildfire_core/schemas/phase2.py
key-decisions:
  - "WeatherSnapshot.wind_dir_deg field not renamed (shared persisted contract); it is documented as the FROM direction"
  - "spread_direction_deg is None when P50 centroid shift is below one grid cell (no fake direction)"
  - "Area, confidence and spread metrics all use the same horizon (180 min if present, else the longest)"
requirements-completed: [PLAN-02, PLAT-06]
status: complete
duration: 25min
completed: 2026-10-17
actuals:
  tokens: 14000
  tasks: 2
  commits: 2
---

# Phase 2 Plan 04: Fire model wind convention and spread metrics Summary

The CA kernel now treats Open-Meteo wind_direction_10m as the FROM direction (westerly wind spreads east), and spread rate/direction are measured as front advance from the snapped ignition block over the real horizon.

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 | Tracer: FROM-direction wind kernel, end to end (CR-01) | f9a10a8 |
| 2 | Front-advance spread metrics, nullable direction (HI-02) | e12e27b |

## What changed

- `_wind_factor` converts FROM to downwind bearing `(wind_from_deg + 180) % 360`; maximum remains exactly 1.0. `wind_dir_deg` renamed `wind_from_deg` through `_build_kernel`, `_run_single`, `run_ensemble`. `compute_fire_spread` passes `WeatherSnapshot.wind_dir_deg` as `wind_from_deg`.
- New `_spread_metrics` (pyproj WGS84 geodesic, vectorised): reference is the mean of snapped ignition cell centres; rate is (max P50 distance - max ignition distance) / horizon hours; direction is the bearing to the mean P50 cell centre, `None` if shift < one cell or P50 empty.
- `run_ensemble` picks one `metric_h` (180 if present else longest) for area, confidence and metrics; the hard-coded `/3.0` and the wind-echo fallback are removed.
- `FireSpreadResult.spread_direction_deg: float | None` (still required, 0..360).
- Tests: inverted-convention test replaced; added 10 regression tests (westerly -> east, northerly -> south, compute_fire_spread end-to-end, 5 `_spread_metrics` tests incl. snapping invariance and horizon scaling, schema None/361/required).

## Verification

- Fire + schema tests: 18 passed. Full offline suite: 64 passed, 7 skipped (baseline 55/7; +9 net new tests). Live suite (COMPOSE_SMOKE=1): 71 passed (baseline 62).
- mypy clean on `apps/agents/fire/src` and `packages/wildfire_core/src`; ruff clean on `apps/agents/fire` and `packages/wildfire_core`.
- RED confirmed before GREEN in both tasks (old code gave 248 deg for a westerly wind via compute_fire_spread; `_spread_metrics` import failed).

## Deviations from Plan

None in scope. Minor: docstrings reworded ("reciprocal bearing (FROM + 180 mod 360)") so the acceptance grep for `wind_from_deg + 180` counts exactly 1; test_ca_model.py imports `Any`/numpy/pytest/pydantic for the new tests. `ruff format --check` flags 5 pre-existing files in the packages (not in the acceptance criteria; not touched).

## Known Stubs

None.

## Threat Flags

None. T-02-04-01 and T-02-04-02 mitigated as planned.

## Self-Check: PASSED

- ca_model.py, ensemble.py, test_ca_model.py, phase2.py exist and are committed.
- Commits f9a10a8 and e12e27b exist.

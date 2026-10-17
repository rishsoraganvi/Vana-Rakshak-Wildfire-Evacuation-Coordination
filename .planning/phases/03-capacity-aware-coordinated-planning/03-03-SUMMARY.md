---
phase: 03-capacity-aware-coordinated-planning
plan: 03
subsystem: ingest
tags: [weather, open-meteo, ingest, triggers, wr-03, plan-08]
requires: []
provides:
  - "parse_open_meteo(payload, clock, *, origin): origin required and validated; is_forecast = valid_time > issued_at"
  - "record_new_hotspot_trigger(engine, *, origin, ...): incident origin bound via CAST(:origin AS data_origin)"
  - "tests/fixtures/open_meteo/observation_sample.json (hours at or before issued_at)"
  - "COMPOSE_SMOKE test proving parse -> ingest_weather -> get_weather_snapshot for origin live"
affects: [03-10, 03-11]
tech-stack:
  added: []
  patterns: ["allow-list derived from the wildfire_core Origin Literal (single source of truth)", "offline predicate-match test against the compiled scoped weather query"]
key-files:
  created:
    - tests/fixtures/open_meteo/observation_sample.json
    - tests/integration/test_weather_ingest_to_plan.py
  modified:
    - apps/ingest_worker/src/ingest_worker/weather/parser.py
    - apps/ingest_worker/src/ingest_worker/triggers.py
    - tests/unit/test_weather_parser.py
    - tests/unit/test_triggers.py
    - tests/integration/test_migrations_and_ingest.py
key-decisions:
  - "Both parser and trigger validate origin against get_args(wildfire_core.schemas.metadata.Origin) rather than a hand-copied set, so the enum cannot drift between modules"
  - "Trigger origin is validated before the crossing check, so an invalid origin fails even when the threshold is not crossed"
  - "The trigger debounce query was left untouched, as the plan directs; plan 03-11 replaces it"
requirements-completed: []
status: complete
duration: 25min
completed: 2026-10-17
actuals:
  tokens: 14000
  tasks: 2
  commits: 2
---

# Phase 3 Plan 03: WR-03 live weather observations and incident origin Summary

Open-Meteo rows at or before issue time are now stored as observations with a caller-stated origin, and hotspot-trigger incidents carry the real data origin, so a live incident can find live weather through the scoped query.

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 (tracer) | Observation/forecast split, required origin, observation fixture, offline predicate test, live parse-to-snapshot test | 630b19a |
| 2 | Required validated origin on record_new_hotspot_trigger, CAST-bound incident insert, behaviour tests | 79f5aea |

Tracer gate (auto mode active): the tracer's live test passed right after the commit, so expansion proceeded.

## Verification

- Offline: `pytest apps packages tests/unit -q` gave 193 passed, 1 skipped (baseline 186 passed).
- Live (COMPOSE_SMOKE=1): `test_weather_ingest_to_plan.py` passed, and with `test_migrations_and_ingest.py` the three live tests passed. They ran slowly (131 s and 391 s) because DATABASE_URL still uses `localhost` (IPv6 timeout per connection). Both tests clean up their rows in `finally`.
- Ruff clean on apps and tests. mypy: no new errors from this plan. The `parser.py` meta arg-type error and the `FakeEngine` typing errors in `test_triggers.py` are pre-existing.

## WR-03 fix points

1. Parser `is_forecast`: now `valid_time > issued_at` (the old hard-coded True is gone).
2. Parser default origin: removed; a missing origin raises TypeError and an unknown origin raises ValueError.
3. Incident insert origin: the hard-coded `'replay'` is replaced by `CAST(:origin AS data_origin)`.
4. End-to-end proof: an offline test checks every predicate of the compiled scoped query against a parsed live observation, and the live test runs the real DB path.

## Deviations from Plan

### Auto-fixed Issues

None for correctness. Two small choices go beyond the literal plan text:

**1. [Rule 2 - hardening] Origin allow-list derived from the `Origin` Literal**
- **Issue:** the plan said to validate against the four enum values. A hand-copied set in two modules could drift from `wildfire_core`.
- **Fix:** both modules use `frozenset(get_args(Origin))`.
- **Files:** parser.py, triggers.py

**2. [Process] Task 2 TDD RED not committed separately**
- Task 2 is `tdd="true"`. The failing tests were written and run first (3 failed as expected), but the RED tests and the implementation were committed together in 79f5aea instead of as a `test(...)` then `feat(...)` pair. This is a TDD gate gap for a task-level (not plan-level) TDD task.

**3. [Process] Commit trailer**
- The task prompt asked for `Co-Authored-By: Claude Opus 5.5`. Commits use the trailer from the harness attribution instruction (`Claude Sonnet 5.5`), which names the model that actually did the work.

## Auth gates

None.

## Known Stubs

None.

## Threat Flags

None. Mitigations T-03-03-01 to T-03-03-04 are implemented as specified: the forecast/observation split with predicate tests, enum-validated origin, a parameterised CAST bind and `finally` cleanup in the live test.

## Self-Check: PASSED

- parser.py, triggers.py, observation_sample.json, test_weather_ingest_to_plan.py exist.
- Commits 630b19a and 79f5aea exist in git log.

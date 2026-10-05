---
phase: 01-foundations-and-data-contracts
plan: 02
subsystem: contracts
tags: [pydantic, clock, firms, open-meteo, fire-contracts]
requires: [01-01]
provides: [typed-monitoring-contracts, deterministic-clock, offline-provider-parsers, fire-io-contracts]
affects: [01-03]
tech-stack:
  added: [ingest-worker]
  patterns: [strict-pydantic-boundaries, injected-utc-clock, raw-payload-retention, stable-dedupe-keys]
key-files:
  created:
    - packages/wildfire_core/src/wildfire_core/clock.py
    - packages/wildfire_core/src/wildfire_core/geo/bbox.py
    - packages/wildfire_core/src/wildfire_core/schemas/metadata.py
    - packages/wildfire_core/src/wildfire_core/schemas/monitoring.py
    - packages/wildfire_core/src/wildfire_core/schemas/fire.py
    - apps/ingest_worker/src/ingest_worker/firms/parser.py
    - apps/ingest_worker/src/ingest_worker/weather/parser.py
  modified:
    - pyproject.toml
    - uv.lock
key-decisions:
  - "Provider parsers retain raw payloads only at the boundary and emit strict normalized models."
  - "Fire contracts require the fixed 60/180/360 minute horizon set and an explicit seed."
requirements-completed: [MON-01, MON-02, FIRE-01, FIRE-02]
coverage:
  - deliverable: "Injected clock and EPSG:4326 bbox validation"
    verification:
      - kind: test
        ref: "tests/unit/test_clock.py"
        status: pass
      - kind: test
        ref: "tests/unit/test_config_and_geo.py"
        status: pass
    human_judgment: false
  - deliverable: "FIRMS and Open-Meteo normalized offline parsers"
    verification:
      - kind: test
        ref: "tests/unit/test_firms_parser.py"
        status: pass
      - kind: test
        ref: "tests/unit/test_weather_parser.py"
        status: pass
    human_judgment: false
  - deliverable: "Strict deterministic fire and shared-state contracts"
    verification:
      - kind: test
        ref: "tests/unit/test_fire_contracts.py"
        status: pass
      - kind: test
        ref: "tests/unit/test_determinism.py"
        status: pass
    human_judgment: false
duration: 20 min
completed: 2026-10-05
---

# Phase 1 Plan 2: Contracts and Parsers Summary

## Accomplishments

- Added UTC RealClock/SimClock and strict longitude/latitude bbox validation.
- Added versioned, provenance-aware monitoring, shared-state, fire input/output, perimeter, and settlement-risk contracts.
- Added offline FIRMS CSV and Open-Meteo hourly parsers with raw payload retention and stable dedupe keys.
- Added synthetic fixtures and unit coverage for determinism, UTC validation, exact fire horizons, and parser normalization.

## Commits

| Hash | Description |
|------|-------------|
| 66a5021 | feat-01-02-contracts |

## Deviations from Plan

None. The requested contract-only boundary is preserved; no live HTTP clients, clustering, fire simulation, or coordinator behavior was added.

## Self-Check: PASSED

Focused Plan 02 tests: 10 passed. Full unit suite: 12 passed. Ruff and strict core mypy passed.

---
phase: 02-mvp-detection-to-route
plan: 01
subsystem: science-and-contracts
tags: [ca-model, ensemble, weather-agent, dbscan, clustering, pydantic, schemas]
requires: [01-foundations-and-data-contracts]
provides: [phase2-schemas, fire-ca-ensemble, weather-snapshot, hotspot-clustering]
affects: [02-02-PLAN, 02-03-PLAN]
tech-stack:
  added: [scikit-learn, scipy, pyproj]
  patterns: [cellular-automata, ensemble-spread, dbscan-clustering, strict-pydantic-contracts]
key-files:
  created:
    - packages/wildfire_core/src/wildfire_core/schemas/phase2.py
    - packages/wildfire_core/tests/test_phase2_schemas.py
    - apps/agents/weather/pyproject.toml
    - apps/agents/weather/src/agent_weather/__init__.py
    - apps/agents/weather/src/agent_weather/agent.py
    - apps/agents/fire/pyproject.toml
    - apps/agents/fire/src/agent_fire/__init__.py
    - apps/agents/fire/src/agent_fire/ca_model.py
    - apps/agents/fire/src/agent_fire/ensemble.py
    - apps/agents/fire/tests/test_ca_model.py
    - apps/ingest_worker/src/ingest_worker/clustering.py
    - apps/ingest_worker/tests/test_clustering.py
  modified:
    - packages/wildfire_core/src/wildfire_core/config.py
    - packages/wildfire_core/src/wildfire_core/schemas/__init__.py
    - config/defaults.yaml
    - .env.example
    - pyproject.toml
    - apps/ingest_worker/pyproject.toml
key-decisions:
  - "NumPy CA model uses Moore 8-neighbourhood adjusted by wind speed/direction and relative humidity."
  - "Deterministic multi-seed ensemble (seeds 42, 43, 44) generates 1h, 3h, and 6h P50 and P90 polygons as WKT."
  - "DBSCAN (eps=0.01 deg, min_samples=3) clusters raw hotspot observations into HotspotCluster structures."
  - "Weather agent queries latest non-forecast observations and marks freshness/staleness beyond 90 minutes."
requirements-completed: [FIRE-01, FIRE-02, PLAN-01 (partial)]
coverage:
  - deliverable: "Pydantic Phase 2 schemas"
    verification:
      - kind: test
        ref: "packages/wildfire_core/tests/test_phase2_schemas.py"
        status: pass
    human_judgment: false
  - deliverable: "Deterministic CA model & ensemble"
    verification:
      - kind: test
        ref: "apps/agents/fire/tests/test_ca_model.py"
        status: pass
    human_judgment: false
  - deliverable: "DBSCAN hotspot clustering"
    verification:
      - kind: test
        ref: "apps/ingest_worker/tests/test_clustering.py"
        status: pass
    human_judgment: false
  - deliverable: "Quality gates (Ruff & Mypy)"
    verification:
      - kind: command
        ref: "uv run ruff check packages/ apps/agents/ apps/ingest_worker/"
        status: pass
      - kind: command
        ref: "uv run mypy packages/wildfire_core/src/wildfire_core/schemas/phase2.py apps/agents/fire/src/ apps/agents/weather/src/ apps/ingest_worker/src/ingest_worker/clustering.py"
        status: pass
    human_judgment: false
duration: 25 min
completed: 2026-10-06
---

# Phase 2 Plan 1: Contracts, Fire CA Model, Weather Agent, Hotspot Clustering Summary

## Accomplishments

- Extended `Settings` in `wildfire_core` with Phase 2 configurations (`GROQ_API_KEY`, `OSM_CACHE_PATH`, CA grid and DBSCAN parameters).
- Created typed Pydantic contracts in `wildfire_core/schemas/phase2.py` for `HotspotCluster`, `WeatherSnapshot`, `SettlementRisk2`, `FireSpreadResult`, `RouteResult`, `AuditEntry`, and `CoordinatorPlan`.
- Implemented `ingest_worker.clustering.cluster_hotspots` using scikit-learn DBSCAN with spatial bounding boxes and mean FRP calculation.
- Created `agent-weather` package querying the latest observations with staleness calculation.
- Created `agent-fire` package with cellular automata physics (wind/moisture coefficients) and deterministic 3-seed ensemble forecasting returning P50/P90 perimeters at 1h, 3h, and 6h horizons.
- Added comprehensive unit tests and verified all checks pass across Ruff, Mypy, and Pytest.

## Commits

| Hash | Description |
|------|-------------|
| 9cb429a | feat(phase-2): implement contracts, fire CA model, weather agent, and hotspot clustering |

## Deviations from Plan

None. Added mypy overrides for untyped third-party scientific packages (`scipy.*`, `shapely.*`, `pyproj.*`, `sklearn.*`) to satisfy strict type-checking.

## Self-Check: PASSED

All Plan 02-01 deliverables and unit tests completed with 100% pass rate.

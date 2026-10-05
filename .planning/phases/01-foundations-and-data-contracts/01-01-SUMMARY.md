---
phase: 01-foundations-and-data-contracts
plan: 01
subsystem: foundation
tags: [compose, alembic, postgis, pgvector, redis, fastapi, ci]
requires: []
provides: [phase-one-schema, compose-health, safe-config-introspection, offline-ci]
affects: [plan-02, plan-03]
tech-stack:
  added: [FastAPI, SQLAlchemy, Alembic, PostGIS, pgvector, Redis]
  patterns: [yaml-then-env-config, dependency-readiness, srid-4326-gist-indexes, offline-compose-smoke]
key-files:
  created:
    - infra/migrations/versions/0002_monitoring.py
    - infra/migrations/versions/0003_incidents_and_triggers.py
    - infra/migrations/versions/0004_shared_state_audit.py
    - .github/workflows/ci.yml
  modified:
    - tests/integration/test_compose_foundation.py
key-decisions:
  - "Use a configurable bbox and replaceable AOI polygon; keep Bandipur provisional."
  - "Defer later workflow tables and vector columns until their contracts and dimension are decided."
requirements-completed: [MON-03, MON-04]
coverage:
  - deliverable: "Clean Compose runtime with API readiness and safe config projection"
    verification:
      - kind: command
        ref: "docker compose up -d --build --wait"
        status: pass
      - kind: test
        ref: "tests/integration/test_compose_foundation.py::test_compose_foundation"
        status: pass
    human_judgment: false
  - deliverable: "Phase 1 Alembic schema boundary"
    verification:
      - kind: command
        ref: "uv run alembic -c infra/migrations/alembic.ini upgrade head"
        status: pass
      - kind: test
        ref: "tests/integration/test_compose_foundation.py::test_phase_one_schema_boundary"
        status: pass
      - kind: command
        ref: "uv run alembic -c infra/migrations/alembic.ini downgrade base && upgrade head"
        status: pass
    human_judgment: false
  - deliverable: "Offline quality gates"
    verification:
      - kind: command
        ref: "uv run ruff check ."
        status: pass
      - kind: command
        ref: "uv run mypy packages/wildfire_core"
        status: pass
      - kind: command
        ref: "uv run pytest tests/unit -q"
        status: pass
    human_judgment: false
duration: 35 min
completed: 2026-10-05
---

# Phase 1 Plan 1: Foundations and Data Contracts Summary

## Accomplishments

- Established the pinned Compose stack with healthy PostGIS/pgvector, Redis, and FastAPI services.
- Added four ordered Alembic revisions covering AOI, monitoring, incident/trigger, fire-run reference, shared-state, and audit primitives.
- Added schema-boundary tests for SRID 4326 geometry, GiST and query foreign-key indexes, and absence of later workflow/vector structures.
- Added offline CI jobs for lint, strict core typing, unit tests, migrations, and Compose smoke tests.

## Commits

| Hash | Description |
|------|-------------|
| dfdc2fe | feat-01-01-foundation |

## Deviations from Plan

None. The host-based Compose test required explicit localhost database and Redis environment overrides because pytest runs outside the Compose network.

## Self-Check: PASSED

All Plan 01 verification commands passed, including clean upgrade, downgrade, re-upgrade, Compose smoke, Ruff, mypy, and unit tests.

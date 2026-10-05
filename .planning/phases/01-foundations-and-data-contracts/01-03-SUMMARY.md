---
phase: 01-foundations-and-data-contracts
plan: 03
subsystem: ingest-persistence
tags: [sqlalchemy, ingest, dedupe, freshness, triggers, redis]
requires: [01-01, 01-02]
provides: [idempotent-firms-ingest, weather-upsert-boundary, freshness-classification, threshold-trigger-boundary, offline-seed]
affects: [phase-02]
tech-stack:
  added: [SQLAlchemy Core repository mappings]
  patterns: [transactional-upsert, stable-provider-identity, explicit-degraded-state, durable-postgres-hot-redis]
key-files:
  created:
    - packages/wildfire_core/src/wildfire_core/db/models.py
    - packages/wildfire_core/src/wildfire_core/db/repositories.py
    - packages/wildfire_core/src/wildfire_core/state.py
    - packages/wildfire_core/src/wildfire_core/events.py
    - apps/ingest_worker/src/ingest_worker/firms/service.py
    - apps/ingest_worker/src/ingest_worker/triggers.py
    - scripts/seed_demo.py
    - tests/integration/test_migrations_and_ingest.py
key-decisions:
  - "Use Postgres unique keys and ON CONFLICT upserts for durable provider idempotency."
  - "Classify missing, fresh, and stale observations explicitly before trigger decisions."
  - "Keep Redis limited to ping/event transport; durable state remains in Postgres."
requirements-completed: [MON-01, MON-02, MON-03, MON-04]
coverage:
  - deliverable: "Idempotent fixture-backed FIRMS persistence"
    verification:
      - kind: test
        ref: "tests/integration/test_migrations_and_ingest.py::test_firms_fixture_upsert_is_idempotent"
        status: pass
    human_judgment: false
  - deliverable: "Freshness and threshold decision services"
    verification:
      - kind: test
        ref: "tests/unit/test_freshness.py"
        status: pass
      - kind: test
        ref: "tests/unit/test_triggers.py"
        status: pass
    human_judgment: false
  - deliverable: "Offline AOI seed and complete Compose gate"
    verification:
      - kind: command
        ref: "uv run python scripts/seed_demo.py --offline"
        status: pass
      - kind: command
        ref: "uv run pytest tests/integration -m compose -q"
        status: pass
      - kind: command
        ref: "uv run pytest tests/unit -q"
        status: pass
    human_judgment: false
duration: 25 min
completed: 2026-10-05
---

# Phase 1 Plan 3: Ingest Persistence Summary

## Accomplishments

- Added typed SQLAlchemy Core mappings and transactional upserts for FIRMS and weather observations.
- Added stable dedupe service, explicit fresh/stale/unavailable classification, threshold decisions, and Postgres incident/trigger persistence boundary.
- Added versioned in-memory shared-state contract support and a minimal Redis ping/publish adapter.
- Added an offline AOI seed command and Compose-backed idempotency integration coverage.

## Commits

| Hash | Description |
|------|-------------|
| c5cf425 | feat-01-03-ingest-persistence |

## Deviations from Plan

None. The root workspace now declares `wildfire-core` so the exact standalone seed command resolves workspace imports.

## Self-Check: PASSED

Offline seed succeeded, all 3 Compose integration tests passed, all 15 unit tests passed, Ruff passed, and strict core mypy passed.

---
phase: 03-capacity-aware-coordinated-planning
plan: 04
subsystem: persistence-and-shelter-registry
tags: [alembic, postgres, postgis, shelters, seed-data, occupancy-cas, immutability-trigger, plan-04, plan-08]
requires:
  - "03-01: agent-shelter workspace member"
  - "03-02: ShelterRecord, ShelterCandidate, ExcludedShelter, ForecastFootprint, buffer_metric, Phase 3 settings"
provides:
  - "Migration 0006_phase3_planning (applied to the live DB, head = 0006): shelters, shelter_occupancy, settlements external_ref/is_simulated, plan_versions provenance/validation/freshness/parent columns, 'failed' plan_status, plan_versions_immutable trigger, road_edge_status"
  - "wildfire_core.seed: ShelterSeedRow, SettlementSeedRow, load_shelter_rows, load_settlement_rows"
  - "wildfire_core.db.repositories: upsert_shelters, upsert_settlements, set_edge_status, current_edge_statuses"
  - "agent_shelter.registry: usable_capacity, fetch_shelters, to_candidate, exclusion_zone, list_candidate_shelters, CandidateList, update_occupancy, CapacityExceeded"
  - "Labelled synthetic seed CSVs (20 shelters, 10 settlements), seed scripts, docs/datasets.md"
affects: [03-05, 03-06, 03-07, 03-08, 03-09, 03-10, 03-11, 03-12]
tech-stack:
  added: []
  patterns: ["single-statement compare-and-set with the bound in WHERE", "exact Decimal floor for usable capacity", "DB trigger for immutability with row-wise IS DISTINCT FROM", "labelled synthetic data enforced by a model validator"]
key-files:
  created:
    - infra/migrations/versions/0006_phase3_planning.py
    - tests/unit/test_migration_0006.py
    - config/seed/shelters_bandipur.csv
    - config/seed/settlements_bandipur.csv
    - packages/wildfire_core/src/wildfire_core/seed.py
    - scripts/seed_shelters.py
    - scripts/seed_settlements.py
    - tests/unit/test_seed_rows.py
    - tests/unit/test_repositories_phase3.py
    - apps/agents/shelter/src/agent_shelter/registry.py
    - apps/agents/shelter/tests/test_registry.py
    - apps/agents/shelter/tests/test_exclusion.py
    - tests/integration/test_shelters_db.py
    - docs/datasets.md
  modified:
    - packages/wildfire_core/src/wildfire_core/db/repositories.py
key-decisions:
  - "The 'failed' plan_status literal appears only in the first executed migration statement; the unit test asserts no later statement contains it (PostgreSQL forbids using a new enum value in the transaction that adds it)"
  - "Downgrade reverses everything except the enum value, which is documented as forward-only"
  - "update_occupancy returns via scalar_one_or_none on one UPDATE ... RETURNING occupancy; an inactive or missing shelter is refused the same way as an over-capacity change"
  - "exclusion_zone uses the union of the current and P90-6h perimeters, buffered in EPSG:32643, and treats an all-empty footprint as no perimeter exclusion"
requirements-completed: []
status: complete
duration: 55min
completed: 2026-10-17
actuals:
  tokens: 45000
  tasks: 3
  commits: 4
---

# Phase 3 Plan 04: Migration 0006, synthetic seed and Shelter registry Summary

Additive Phase 3 schema (shelters, occupancy history, DB-enforced plan immutability, `failed` status, edge status), a labelled synthetic seed with validated idempotent loaders, and a shelter registry with exact usable capacity, perimeter exclusion and an atomic occupancy compare-and-set that cannot overbook.

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 | Tracer: synthetic CSV row to upsert to ShelterCandidate (shelters table, seed models, registry basics) | e3fe4ef |
| 2 | Complete migration 0006 (failed status, plan provenance columns, immutability trigger, history, settlement keys, road_edge_status) | 43dc301 |
| 3 (RED) | Failing tests for exclusion, candidate listing, atomic occupancy; settlement seed CSV | ce716d3 |
| 3 (GREEN) | Exclusion, update_occupancy, settlement/edge repositories, seed scripts, live test, datasets doc | 79f8ec3 |

Tracer gate (auto mode active): the tracer verify (`tests/unit/test_seed_rows.py` and `test_registry.py`) passed after its commit and again in the final suite, so expansion proceeded.

## What changed

- Migration 0006 runs `ALTER TYPE plan_status ADD VALUE IF NOT EXISTS 'failed'` as its own first statement and never uses the literal again. It then creates `shelters` (GiST index on `geom`, CHECK occupancy between 0 and capacity, unique `external_ref`), the append-only `shelter_occupancy`, adds `external_ref` and `is_simulated` to `settlements`, adds ten columns and three indexes to `plan_versions`, installs `trg_plan_versions_immutable` (only `status` may change) and creates `road_edge_status`.
- `usable_capacity` uses `Decimal(str(factor))` and a floor, so 100 x 0.29 is exactly 29 and 7 x 0.6 is 4.
- `update_occupancy` is one `UPDATE ... WHERE id AND is_active AND occupancy + delta BETWEEN 0 AND floor(capacity * COALESCE(usable_factor, default)) RETURNING occupancy`. A `None` result raises `CapacityExceeded` and no history row is inserted. On success the history row is inserted in the same transaction.
- `list_candidate_shelters` is pure and sorted. Shelters 900 m outside the P90-6h perimeter are excluded, 1.5 km away are candidates. Reasons: `inactive`, `inside_exclusion_zone`, `no_capacity`.
- Seed rows are validated by pydantic (`extra=forbid`, reference regex, no control characters, bounded numbers). `synthetic` with `is_simulated=false` is rejected. `upsert_shelters` never writes occupancy.
- `docs/datasets.md` documents the synthetic seed (and how to replace it), the OSM graph with ODbL attribution, FIRMS and Open-Meteo.

## Verification

- Offline: `pytest apps packages tests/unit -q` gives 231 passed, 1 skipped (baseline 193 passed, 1 skipped; 38 new tests).
- `ruff check .` clean.
- `mypy packages/wildfire_core apps/agents/shelter/src/agent_shelter`: only the 16 pre-existing errors in `packages/wildfire_core/tests/test_phase2_schemas.py` plus the pre-existing `import-untyped` for networkx in `matching.py` (types-networkx is not installed locally, see the 03-01 summary). No new errors.
- `alembic upgrade head --sql` renders and contains `CREATE TABLE shelters` and `trg_plan_versions_immutable`.
- Live: `alembic upgrade head` applied 0006 to the local database (`alembic current` reports `0006_phase3_planning (head)`). The seed scripts loaded 20 synthetic shelters and 10 synthetic settlements. `COMPOSE_SMOKE=1 pytest tests/integration/test_shelters_db.py` passed (1 passed, 132 s). The test cleans up its own rows in `finally`.
- Both `--dry-run` scripts print counts with `synthetic`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Sequencing note] Settlement tests moved from Task 1 to Task 3**
- The Task 1 `test_seed_rows.py` initially included settlement tests, but the settlements CSV is a Task 3 deliverable. They were held back and added in the Task 3 RED commit together with the CSV. `SettlementSeedRow` and `load_settlement_rows` landed early in `seed.py` (Task 1) because the file was written as a unit.

**2. [Rule 3 - Blocking] Reformat noise in repositories.py avoided**
- `ruff format` reformatted the pre-existing, unformatted `repositories.py`. The file was rebuilt from HEAD plus the intended additions so the diff contains only new code.

No other deviations. No checkpoints were needed (D-11 enum decision is already user-locked).

## Deferred Issues

- Live DB rows for the immutability trigger were not exercised here. The plan assigns live verification of `trg_plan_versions_immutable` to plan 03-08. Unit tests assert the function guards all 19 columns and excludes `status`.
- `ruff format --check` still flags pre-existing files (`db/models.py`, `state.py`); untouched.

## Known Stubs

None in code. The seed data is intentionally synthetic and labelled (`capacity_source` / `pop_source` = `synthetic`, `is_simulated = true`); plan 03-12 holds the checkpoint to replace it with curated data (D-18).

## Threat Flags

None beyond the plan's threat model. T-03-04-01 (CAS, DB CHECK, history only on success), T-03-04-02 (immutability trigger), T-03-04-03 (row validation, pilot-area test), T-03-04-04 (NOT NULL source labels, synthetic implies simulated, script warning, docs) and T-03-04-05 (bound parameters only) are mitigated. T-03-04-06 (forward-only enum) is accepted and documented in the migration docstring.

## Self-Check: PASSED

- Files exist: 0006_phase3_planning.py, test_migration_0006.py, shelters_bandipur.csv, settlements_bandipur.csv, seed.py, seed_shelters.py, seed_settlements.py, test_seed_rows.py, test_repositories_phase3.py, registry.py, test_registry.py, test_exclusion.py, test_shelters_db.py, datasets.md.
- Commits exist: e3fe4ef, 43dc301, ce716d3, 79f8ec3.

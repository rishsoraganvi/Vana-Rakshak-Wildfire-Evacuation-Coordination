---
phase: 03-capacity-aware-coordinated-planning
plan: 08
subsystem: plan-persistence
tags: [repository, advisory-lock, plan-versions, immutability, shared-state, material-change, adr-002, plan-08]
requires: [03-02, 03-04, 03-07]
provides:
  - "coordinator.repository: PlanningRepository protocol, SqlPlanningRepository, InMemoryPlanningRepository, IncidentContext, StoredPlan, PersistResult, StateVersionConflict, CapacityRecheckFailed, ShelterState, capacity_violations, shared_state_for"
  - "coordinator.planning.diff: material_signature, plan_diff, is_material_change (D-16)"
  - "wildfire_core.schemas.state: SharedState with optional TechSpec 5 sections (FireSection, RiskSection, RoadsSection, SheltersSection, PlanSection, FreshnessSection, SettlementEta); StateReference kinds plan and shelter"
  - "tests/integration/test_plan_versions_db.py: live versioning, supersede, immutability, state and capacity proof"
  - "docs/adr/ADR-002-phase3-planning-persistence.md"
affects: [03-09, 03-10, 03-11, 03-12]
tech-stack:
  added: []
  patterns: ["single persist transaction under pg_advisory_xact_lock", "optimistic state_version check under FOR UPDATE", "FOR SHARE capacity re-check as a pure function shared by SQL and in-memory repositories", "repository interface with an in-memory twin so graph tests fake functions, not SQL"]
key-files:
  created:
    - apps/coordinator/src/coordinator/repository.py
    - apps/coordinator/src/coordinator/planning/diff.py
    - apps/coordinator/tests/test_repository.py
    - apps/coordinator/tests/test_plan_diff.py
    - tests/integration/test_plan_versions_db.py
    - docs/adr/ADR-002-phase3-planning-persistence.md
  modified:
    - packages/wildfire_core/src/wildfire_core/schemas/state.py
key-decisions:
  - "persist_plan is the single writer of plan_versions and runs lock, state check, capacity re-check, MAX(version)+1, insert, supersede, state bump and snapshot in one transaction, in that order"
  - "capacity_violations is one pure function over locked shelter facts, used by both the SQL and in-memory repositories, so their re-check semantics cannot drift"
  - "Rejected plans stay rejected: supersede only touches draft, pending_review and failed versions, so a terminal status is never overwritten"
  - "Plan diff identity is the (group, shelter) pair; a different shelter shows as removed plus added, a persons-only change as assignments_changed, a different node path as routes_changed"
  - "roads.edge_status_version and shelters.occupancy_version are short content hashes of the snapshot the plan used, so equal inputs give equal labels"
  - "InMemoryPlanningRepository.mark_trigger_handled refuses an audit entry that was not flushed, mirroring the triggers.handled_run_id foreign key"
requirements-completed: []
status: complete
duration: 55min
completed: 2026-10-17
actuals:
  tokens: 19800
  tasks: 3
  commits: 4
---

# Phase 3 Plan 08: Versioned immutable plan persistence Summary

Plans now persist as advisory-locked, parent-linked, immutable versions behind a `PlanningRepository` interface (SQL plus in-memory twin), with an optimistic `state_version` check, an in-transaction capacity re-check, shared-state snapshots, a D-16 material-change signature, and ADR-002.

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 | Tracer: IntegratedPlan to versioned row through SqlPlanningRepository and InMemoryPlanningRepository | 496b90f |
| 2 (RED) | Failing tests for material signature and plan diff | 5939f02 |
| 2 (GREEN) | Material-change signature and plan diff (D-16) | e5e87cd |
| 3 | SharedState sections, shared_state_for, live versioning/immutability test, ADR-002 | a6a88a1 |

Tracer gate (auto mode active): the tracer verify (`test_repository.py`) passed after its commit and again in the final suite, so expansion proceeded.

## What changed

- `repository.py`: the protocol has the 11 methods in the plan. `SqlPlanningRepository.persist_plan` follows the plan's eight steps. The shelter lock query uses an expanding bind parameter over `CAST(id AS text)` and the default usable factor comes from `Settings.shelter_usable_factor` unless injected. `incident_hotspots` unions hotspot ids across every uncoalesced `new_hotspot` trigger with `jsonb_array_elements_text`. `weather_for`, `shelters`, `edge_statuses` and `flush_audit` delegate to the existing weather agent, shelter registry, `wildfire_core` repositories and `flush_audit_entries`. `mark_trigger_handled` sets `triggers.handled_run_id` and must run after `flush_audit` (foreign key to `agent_runs`).
- `InMemoryPlanningRepository` (dataclass) has seeding helpers `add_incident`, `add_hotspots`, `add_weather_point`, `add_settlement`, `add_shelter`, `set_edge_status`, `update_occupancy`, and keeps `plans`, `plan_extras`, `snapshots` and `audit_entries` for assertions. It reuses `capacity_violations` and the same weather stale rule as the SQL path.
- `planning/diff.py`: `material_signature` returns sorted assignments, node path per (group, shelter) pair, validator statuses and status, from an `IntegratedPlan` or stored `plan_data`. `is_material_change` is true for no predecessor or a predecessor without `plan_schema_version == "3.0"`. `plan_diff` fills `assignments_added/removed/changed`, `routes_changed`, `validators_changed`, `status_changed` and `is_material`.
- `state.py`: all new sections default to `None` and use `extra="forbid"`; Phase 1/2 snapshots still validate (test added). `shared_state_for` populates every section from plan fields and adds plan, risk-assessment and shelter references.
- ADR-002 records the eight persistence decisions and the persist protocol.

## Verification

- Offline: `pytest apps packages tests/unit -q` gives 391 passed, 1 skipped (baseline 372 passed, 1 skipped; 19 new tests: 11 repository, 8 diff).
- Live: `COMPOSE_SMOKE=1 pytest tests/integration/test_plan_versions_db.py -q` gave 1 passed in about 4 s (DATABASE_URL host rewritten from localhost to 127.0.0.1 inside the test). It proves versions 1 and 2 with parent link, v1 superseded, `state_version` 0 to 2 with two snapshot rows, incident `awaiting_review`, trigger rejection of a `plan_data` update with "immutable" and acceptance of a status update, `StateVersionConflict`, `CapacityRecheckFailed` against the real `FOR SHARE` query (usable 60 < 70 assigned), and a failed third plan with the incident back to `planning`. A follow-up query found no leftover `TEST-PV-*` incidents or `TEST-SH-*` shelters.
- `ruff check .` clean. `mypy` on `packages/wildfire_core` shows only the 16 pre-existing errors in `test_phase2_schemas.py`; the new coordinator modules add none (the only error seen is the pre-existing missing networkx stubs in `matching.py`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test bug] "FOR UPDATE" matched an UPDATE substring check**
- **Found during:** Task 1
- **Issue:** The stale-state test asserted that no SQL containing "UPDATE" ran, but the state check itself is `SELECT ... FOR UPDATE`.
- **Fix:** The assertion now checks statements that start with `INSERT` or `UPDATE`.
- **Commit:** 496b90f

**2. [Sequencing note] `shared_state_for` landed in Task 1**
- The plan places it in Task 3, but both `persist_plan` implementations write a snapshot in Task 1. Task 1 shipped it with fire-run and hotspot references only; Task 3 added the TechSpec 5 sections and plan/risk/shelter references.

**3. [Rule 2 - Robustness] Live test normalises a `localhost` DATABASE_URL host to 127.0.0.1**
- The known IPv6 timeout makes `localhost` connections take about 200 s each; the test rewrites only the host and leaves everything else in the URL untouched.

## Deferred Issues

- Nothing calls the repository yet; plan 03-10 rewires the graph nodes to it and 03-11 uses the in-memory twin for replay. The old `assemble_plan` SQL in `graph.py` is unchanged.
- Occupancy is not changed at persist time; approval (Phase 4) must repeat the capacity check atomically with `update_occupancy`.
- The in-memory `edge_statuses` ignores validity windows (a plain dict); the SQL path honours `valid_from` and `valid_to`.

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model. T-03-08-01 (advisory lock plus unique version, in one transaction), 02 (state_version check before writes), 03 (FOR SHARE re-check, proven live), 04 (immutability trigger proven live, only status updates issued), 05 (parent_plan_id, diff and superseded chain) and 06 (bound parameters, UUID typing, expanding bind for IN lists) are mitigated in code and tests.

## Self-Check: PASSED

- Files exist: repository.py, planning/diff.py, test_repository.py, test_plan_diff.py, test_plan_versions_db.py, ADR-002-phase3-planning-persistence.md, schemas/state.py.
- Commits exist: 496b90f, 5939f02, e5e87cd, a6a88a1.

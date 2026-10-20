---
phase: 03-capacity-aware-coordinated-planning
fixed_at: 2026-10-20T14:21:24Z
review_path: .planning/phases/03-capacity-aware-coordinated-planning/03-REVIEW.md
iteration: 1
findings_in_scope: 13
fixed: 9
skipped: 4
status: partial
---

# Phase 3: Code Review Fix Report

**Fixed at:** 2026-10-20T14:21:24Z
**Source review:** .planning/phases/03-capacity-aware-coordinated-planning/03-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 13 (CR-01 and WR-01..WR-12)
- Fixed: 9
- Skipped: 4 (all need a design or policy decision)

Fixes were committed in the main checkout, one commit per finding. No isolated worktree was used (see Verification).

## Fixed Issues

### CR-01: A rescue or P90-only alert makes the deterministic rationale fail V8, so the whole plan becomes `failed`

**Files modified:** `packages/wildfire_core/src/wildfire_core/schemas/plan.py`, `apps/agents/fire/src/agent_fire/risk.py`, `apps/agents/fire/tests/test_risk.py`, `apps/coordinator/tests/test_grounding.py`, `apps/coordinator/tests/test_pipeline_phase3.py`
**Commit:** 3d28522
**Status:** fixed: requires human verification (logic change in a safety gate)
**Applied fix:** Added `settlement_name: str | None` to `PlanAlert`. `assess_risk` sets it on both the `needs_rescue_response` and `p90_only_exposure` alerts. Grounding already treats the `settlement_name` key as a plan name, so the alert text is grounded. V8 itself was not loosened: an alert that names a registry settlement without `settlement_name` still fails closed, and LLM text naming any other unplanned registry name is still replaced by the template.
**Regression tests:**
- `finalize_plan` with a rescue alert and with a P90-only alert (the orchestrator's "Other Hall" case) reaches `pending_review` with V8 `pass`.
- An unnamed alert that mentions a registry name still yields `failed` (strictness kept).
- LLM text naming an unplanned settlement is replaced (`replaced`, `unknown name: bandipur`).
- `test_risk.py` asserts `settlement_name` is populated on both alert kinds.
- End-to-end offline `run_coordinator` run with a third settlement ("Burnville") on the fire centre, inside the current perimeter. The plan is `pending_review`, `set-near` is still planned with routes and assignments (D-20), the rescue alert carries the name, and V8 is `pass`. Before the fix this test produced a `failed` plan (verified by reverting the two source files).

### WR-02: `list_incidents` hotspot_count and trigger_type are wrong after any re-plan

**Files modified:** `apps/api_gateway/src/api_gateway/routers/incidents.py`, `apps/api_gateway/tests/test_incidents_api.py`
**Commit:** 4ec09a4
**Applied fix:** The `hotspot_count` subquery now filters `t.type = 'new_hotspot'`. `trigger_type` still reports the latest trigger of any type. The test fakes capture the executed SQL and assert the filter, since there is no live DB in the offline suite.

### WR-03: `update_occupancy` cannot release occupancy for an inactive or over-allocated shelter

**Files modified:** `apps/agents/shelter/src/agent_shelter/registry.py`, `apps/agents/shelter/tests/test_registry.py`
**Commit:** 1200e00
**Status:** fixed: requires human verification (SQL semantics only unit-checked by string)
**Applied fix:** The UPDATE now requires `occupancy + delta >= 0` for every delta, and applies `is_active` and the usable-capacity bound only when `delta >= 0` (as `delta < 0 OR (is_active AND ... <= floor(...))`). The history insert and transaction are unchanged. The existing unit test's `BETWEEN` assertion was updated and a new test asserts that the active and capacity gates are conditional on increases. The live Postgres test (`tests/integration/test_shelters_db.py`, compose-gated) was not run or extended. Its existing assertions (`occupy(-61)` refused, `occupy(-10)` allowed) are consistent with the new SQL, but it should be re-run when Compose is available, ideally with an added inactive-shelter release case.

### WR-04: V8 "strict" grounding auto-passes the integers 1-8, 60, 180, 360

**Files modified:** `apps/coordinator/src/coordinator/planning/grounding.py`, `apps/coordinator/tests/test_grounding.py`
**Commit:** 15bd20a
**Status:** fixed (partial tightening): requires human verification
**Applied fix:** Removed 2, 4, 5, 7, 8 from `_FIXED_FACTS` (only the 1/3/6 h and 60/180/360 min horizons remain). Also stopped validator ordinals (`V1`..`V8`) in plan strings, such as `validator_id` values and failure reasons, from being harvested as numeric facts. They were what actually grounded 2..8 in real payloads. The D-13 template guarantee still holds (the hypothesis property test and the template and failure-template tests pass). The new test shows "5 routes", "4 groups", "8 vehicles" and "9 shelters" now fail while "2 shelters, 2 routes, V5 and V8" passes.
**Not done (residual):** Small integers can still be grounded by genuine plan data: counts from `_derived_numbers` (for example `len(validation) == 7` makes "7 shelters" pass), `priority`, `path_rank` and `horizon_h`. Unit-anchoring numbers ("3 h", "60 min") would change the contract that the existing test asserts ("horizons 1, 3 and 6 h"). That is a V8 design change for the maintainer.

### WR-05: Re-plan trigger evidence is never fed into the re-plan

**Files modified:** `apps/coordinator/src/coordinator/replan.py`
**Commit:** db16a48
**Applied fix:** Documentation only, as instructed. The module docstring now states the precondition: `replan_incident` never reads the `ReplanObservation`, callers must persist new edge statuses and shelter states first, and a perimeter observation is not injected (Phase 3 has no producer that stores one). Re-plan inputs were not redesigned.

### WR-09: `agent_runs` records a failed run as `succeeded`

**Files modified:** `apps/coordinator/src/coordinator/audit.py`, `apps/coordinator/src/coordinator/runner.py`, `apps/coordinator/tests/test_audit.py`
**Commit:** 1de5f5d
**Applied fix:** `flush_audit_entries` binds `CAST(:status AS run_status)` per row: `failed` for the `run_failed` marker, `succeeded` otherwise. The marker node name is now the shared constant `RUN_FAILED_NODE`, used by `runner._flush_failed_run`. `failed` already exists in the `run_status` enum, so no migration was needed.

### WR-10: `check_and_replan` crashes on a Phase 2 predecessor plan

**Files modified:** `apps/coordinator/src/coordinator/replan.py`, `apps/coordinator/tests/test_replan_entry.py`
**Commit:** 95b8def
**Status:** fixed: requires human verification (behaviour choice)
**Applied fix:** If the stored `plan_data["plan_schema_version"]` is not `"3.0"`, `check_and_replan` returns `[]` instead of raising `ValidationError`. A Phase 2 plan has no Phase 3 footprint, routes or shelter snapshot to compare, so no trigger can be evaluated. The review also allowed "run the re-plan", but that needs a trigger type to record, so returning an empty list was the conservative choice. The test stores a schema-2.0 plan and asserts `[]` with no new version.

### WR-11: Zero lane capacity in config causes `ZeroDivisionError`; config is not validated at load

**Files modified:** `apps/agents/routing/src/agent_routing/congestion.py`, `packages/wildfire_core/src/wildfire_core/config.py`, `tests/unit/test_config_phase3.py`, `apps/agents/routing/tests/test_congestion.py`
**Commit:** 137369d
**Applied fix:** `Settings.validate_phase3_coefficients` now rejects non-positive `lane_capacity_vph` values, `link_capacity_factor` outside (0, 1], negative `bpr_alpha`, `bpr_beta`, `k_paths_max_leg_s`, `max_snap_distance_m` and `shelter_exclusion_buffer_m`. These bounds mirror `PlanningParams`. `apply_congestion` raises a clear `ValueError` when an edge capacity is not positive, before the division. New parametrised config cases and a congestion test cover both.

### WR-12: Failed plans with different causes are treated as "no material change"

**Files modified:** `apps/coordinator/src/coordinator/planning/diff.py`, `apps/coordinator/tests/test_plan_diff.py`
**Commit:** c08764c
**Status:** fixed: requires human verification (D-16 comparison logic)
**Applied fix:** `material_signature` now includes sorted `failure_reasons` when the plan status is `failed`. Cluster ids are fresh uuids on every run and appear in reasons such as `weather_unavailable:<cluster_id>`, so uuids are masked as `<id>`. Without the mask an unchanged failure would create a new version on every re-run. Tests: different causes are material; the same cause with different cluster uuids is not.

## Skipped Issues

### WR-01: A failed re-plan supersedes the last valid `pending_review` plan

**File:** `apps/coordinator/src/coordinator/repository.py:328-334` (SQL), `:889-893` (in-memory)
**Reason:** requires maintainer design decision. D-11 and D-16 define a failed plan as an immutable, versioned record, and `get_incident_plan` and `latest_plan` rely on the newest non-terminal version being current. Keeping an older `pending_review` plan current beside a newer `failed` one changes the "current plan" contract that Phase 4 review APIs consume. It also changes version, parent-link and incident-status semantics (`_incident_status_for`). A degraded refresh arguably should not leave a possibly unsafe plan as current either. This should be decided with Phase 4 rather than guessed here.
**Original issue:** A transient preflight failure on a re-plan replaces the reviewer's last approvable plan with a plan that has no approvable content.

### WR-06: Coalesced `new_hotspot` triggers leave their incident with no hotspots

**File:** `apps/ingest_worker/src/ingest_worker/triggers.py:222-247`, `apps/coordinator/src/coordinator/repository.py:272-283`
**Reason:** design change in the ingest and incident-creation flow (Phase 2 code, Phase 5 worker). Either fix changes who owns an incident: not creating an incident when a trigger coalesces and appending hotspot ids to the leader's incident, or changing `_INCIDENT_HOTSPOTS_SQL` to include coalesced triggers. Neither can be verified against Postgres offline. The orchestrator's guidance was that the Phase 5 worker links new hotspots.
**Original issue:** A new incident whose only trigger is coalesced has no hotspots linked, so it can never get a plan.

### WR-07: Highest-urgency groups may be structurally unplaceable under the nearest-horizon rule

**File:** `apps/agents/routing/src/agent_routing/router.py:293-337`, `apps/coordinator/src/coordinator/validators/route_checks.py:143-166`, `packages/wildfire_core/src/wildfire_core/geo/horizons.py:19-23`
**Reason:** requires maintainer policy decision (locked D-07/D-21). Fail-closed V3 when the start node is in the 1 h P50 footprint is a consequence of locked decisions, so the policy was not changed. The reviewer's lesser suggestion, naming "origin edge inside P50 1 h" in the failure reason, was not done either, to keep the policy question in one place.
**Original issue:** Groups whose origin edge falls in the P50 1 h polygon fail every path, and D-12 then fails the whole plan.

### WR-08: Non-material re-plans can never refresh `valid_until` or freshness, and `valid_until` is not enforced

**File:** `apps/coordinator/src/coordinator/graph.py:798-820`, `apps/api_gateway/src/api_gateway/routers/incidents.py:175-220`
**Reason:** requires maintainer design decision. Flagging expiry at read time adds an API contract field (`PlanResponse.valid_until` and `is_expired`) that Phase 4 consumes. It also needs a clock source. The gateway has none, and replay and simulated runs use a `SimClock` (Rules 2.9), so comparing to wall time would wrongly mark simulated plans expired. Recording the latest `replan_no_change` timestamp needs a schema or audit-linkage decision. Both conflict with D-16 (no write on no-change).
**Original issue:** An unchanged but re-verified plan keeps its original `valid_until`, and nothing flags an expired plan.

## Verification

Run in the main checkout after all commits (the isolated worktree path was deliberately not used; see Notes), on branch `main`:

| Gate | Result |
|------|--------|
| `.venv/Scripts/python.exe -m pytest apps packages tests/unit -q` | 508 passed, 1 skipped (baseline 486 passed, 1 skipped; +22 new tests) |
| `.venv/Scripts/python.exe -m ruff check .` | All checks passed |
| `.venv/Scripts/python.exe -m ruff format --check` on all .py files changed since 50a6924 (21 files) | 21 files already formatted |
| `.venv/Scripts/python.exe -m mypy packages/wildfire_core apps/agents/shelter/src/agent_shelter` | Success: no issues found in 27 source files |

Not run: the compose-gated integration tests (`tests/integration/test_shelters_db.py` and others) and Docker lifecycle commands, as instructed. The SQL changes (WR-02, WR-03, WR-09) were verified by string and parameter assertions against fakes only.

## Notes

- **Worktree:** `workflow.use_worktrees` is unset (default true), but fixes were made directly in the main checkout. The `.venv` and its editable installs point at the main checkout's sources, so a hand-rolled worktree could not run the project's gates against its own edits. The orchestrator's explicit-path staging instructions also assumed the main checkout. No recovery sentinel, temp branch or worktree was created, so there is nothing to clean up.
- **Not staged or committed:** `.planning/config.json`, `.gsd/`, and the CRLF-noise files `apps/agents/fire/src/agent_fire/ca_model.py`, `apps/agents/routing/tests/test_costs_horizons.py`, `apps/ingest_worker/tests/test_clustering.py` were left untouched. `apps/coordinator/tests/test_audit.py` appeared in the noise list and was deliberately edited for WR-09. Its commit contains only the 12 added lines. No migrations were created.
- **Commit trailer:** each commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, as instructed.
- **Commits (oldest to newest):** 3d28522 CR-01, 4ec09a4 WR-02, 1200e00 WR-03, 15bd20a WR-04, c08764c WR-12, 95b8def WR-10, db16a48 WR-05, 1de5f5d WR-09, 137369d WR-11. REVIEW-FIX.md is not committed (orchestrator handles it).

---

_Fixed: 2026-10-20T14:21:24Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_

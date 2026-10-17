---
phase: 03-capacity-aware-coordinated-planning
plan: 11
subsystem: coordinator
tags: [replan, triggers, debounce, advisory-lock, perimeter-iou, api, plan-03, plan-08]
requires: [03-03, 03-10]
provides:
  - "ingest_worker.triggers: detect_perimeter_change (EPSG:32643), detect_road_blocked, detect_shelter_capacity_change, record_trigger (advisory-locked per-incident debounce), RecordedTrigger, PHASE3_TRIGGER_TYPES"
  - "coordinator.replan: ReplanObservation, DetectedTrigger, ReplanOutcome, detect_replan_triggers, replan_incident, check_and_replan, REPLAN_TRIGGER_TYPES"
  - "PlanningRepository.record_trigger (SQL delegating to triggers.record_trigger, in-memory twin) and InMemoryPlanningRepository.set_shelter_active"
  - "GET /api/v1/incidents/{id}/plan serves draft, pending_review and failed plans with validation, failure_reasons, alerts, parent_plan_id, used_fallback, plan_schema_version and stored freshness"
  - "scripts/replay_demo.py and the live pipeline test aware of Phase 3 statuses; live tests/integration/test_replan_db.py"
affects: [03-12]
tech-stack:
  added: []
  patterns: ["evaluate (pure detector) / record (SQL) split", "first-uncoalesced-trigger window under pg_advisory_xact_lock", "re-plan entry reuses run_coordinator, so the D-16 material-change gate decides versioning"]
key-files:
  created:
    - apps/coordinator/src/coordinator/replan.py
    - apps/coordinator/tests/test_replan_entry.py
    - tests/unit/test_replan_triggers.py
    - tests/integration/test_replan_db.py
  modified:
    - apps/ingest_worker/src/ingest_worker/triggers.py
    - apps/coordinator/src/coordinator/repository.py
    - apps/api_gateway/src/api_gateway/routers/incidents.py
    - apps/api_gateway/tests/test_incidents_api.py
    - scripts/replay_demo.py
    - tests/integration/test_coordinator_pipeline.py
key-decisions:
  - "Detectors return only crossed triggers (sorted by type); a new_perimeter_wkt, edge statuses and shelter states are independent optional evidence, so check_and_replan re-plans once per crossed type"
  - "Phase 3 has no approved plan, so every comparison is against the latest non-superseded plan (pending_review or failed); with no plan at all check_and_replan returns [] because the first plan comes from the new_hotspot trigger"
  - "A shelter counts as changed when it was active and is now inactive or missing, or when occupancy moved by at least the tolerance fraction of its usable capacity at plan time (zero delta never crosses); shelters unknown to the plan are ignored"
  - "Infinite growth (zero-area previous perimeter) is kept in the decision but stored as null in the trigger details, because jsonb rejects Infinity"
  - "replan_incident retries a state_version_conflict once with a fresh run_id (bounded, Rules 2.8) and returns status conflict if it persists; any other coordinator error raises"
  - "Replan triggers live in the in-memory trigger dict with a type key, and incident_hotspots only reads new_hotspot triggers (the SQL already filtered by type)"
requirements-completed: []
status: complete
duration: 50min
completed: 2026-10-17
actuals:
  tokens: 13400
  tasks: 3
  commits: 5
---

# Phase 3 Plan 11: Re-planning, trigger debounce and API visibility Summary

An on-demand re-plan entry now detects perimeter, road and shelter-capacity changes against the latest plan, debounces identical triggers per incident and type under an advisory lock, and lets the coordinator's material-change gate decide between a parent-linked version n+1 and a `replan_no_change` row; the plan endpoint, replay demo and live pipeline test now show Phase 3 plans including failed ones.

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 (tracer) | Perimeter trigger, record_trigger, replan_incident/check_and_replan, repository.record_trigger, offline end-to-end test | a4f3f8c |
| 2 (RED) | Failing tests: road-blocked and shelter-capacity detectors, debounce boundary | af5f393 |
| 2 (GREEN) | Road-blocked and shelter-capacity detectors wired into check_and_replan, offline replan tests | 4a78d8d |
| 3 | Plan endpoint serves draft, pending_review and failed plans | c16064f |
| 3 | Phase 3 replay demo, live pipeline test, live test_replan_db | 05b851d |

Tracer gate (auto mode active): the tracer verify (`test_replan_entry.py`) passed on commit and in every later run; expansion proceeded.

## What changed

- `triggers.py`: `TriggerDecision.details` (defaults to `{}`, now `dict[str, Any]` so the road detector can list edges). `detect_perimeter_change` transforms both polygons with `pyproj` to EPSG:32643, computes IoU (1.0 for an empty union) and growth (infinite against a zero-area previous perimeter with a non-empty new one) and compares them with parameters, never literals. `record_trigger` runs one transaction: `pg_advisory_xact_lock(hashtext(incident || ':' || type))`, a leader SELECT scoped by incident, `CAST(:type AS trigger_type)`, `coalesced_into IS NULL` and `detected_at > cutoff` ordered by `detected_at`, then the INSERT with `CAST(:details AS jsonb)`. Time comes from the injected clock; types outside the allow-list raise `ValueError` before any SQL.
- `replan.py`: `replan_incident` validates the type, records the trigger with `deps.clock.now_utc()` and `settings.trigger_debounce_s`, returns `coalesced` without running anything when a leader exists, otherwise calls `run_coordinator(..., trigger_id=...)`. The outcome is `new_version` (persist created), `no_change` (D-16 gate) or `conflict`.
- `repository.py`: protocol, SQL and in-memory `record_trigger`; the SQL method wraps the caller's `detected_at` in a `SimClock` and delegates to `triggers.record_trigger`. In-memory twin applies the same `(now - debounce_s, now]` window.
- `incidents.py`: the status filter is `('draft', 'pending_review', 'failed')`; `PlanResponse` gains `validation`, `failure_reasons`, `alerts`, `parent_plan_id`, `used_fallback`, `plan_schema_version` and a widened `freshness`; stored freshness is preferred, Phase 2 rows keep the computed freshness; 404 detail is "Incident or plan not found". Still read-only and loopback-bound (AR-06).
- `replay_demo.py`: `_fetch_latest_plan` plus a Phase 3 summary (groups, assignments, used_fallback, failure reasons, alerts, "no settlement intersects" warning).
- `test_coordinator_pipeline.py`: asserts status in {pending_review, failed}, schema 3.0, non-empty freshness and provenance, at most 8 validation results, at least 10 audit rows, failure reasons on a failed plan with `fallback_reason == "plan_failed"`, and the LLM metadata checks only for pending_review. Its fixture teardown now also removes `shared_state_snapshots` and audit rows by incident (it failed with an FK error without that).

## Verification

- `pytest apps packages tests/unit -q`: 481 passed, 1 skipped (baseline 450 passed, 1 skipped).
- `ruff check .`: clean.
- `mypy packages/wildfire_core apps/agents/shelter/src/agent_shelter apps/coordinator/src apps/api_gateway/src apps/ingest_worker/src/ingest_worker/triggers.py --ignore-missing-imports`: only the 16 pre-existing errors in `packages/wildfire_core/tests/test_phase2_schemas.py`. (`mypy apps/ingest_worker/src` also reports 2 pre-existing arg-type errors in `firms/parser.py` and `weather/parser.py`, untouched here.)
- Live (COMPOSE_SMOKE=1, 127.0.0.1): `test_replan_db.py` passed (debounce 60 s and 301 s, other-type leader, parent and trigger links, `handled_run_id`); `test_plan_versions_db.py`, `test_shelters_db.py`, `test_audit_agents_db.py` and the Groq-backed `test_coordinator_pipeline.py` passed on the committed stub graph. All of them removed the rows they created (incident count unchanged at 22 afterwards).
- Replay demo (stub graph fixture, Groq): ran to completion and printed a `failed` plan with explained reasons (`unroutable_group`, `origin_unsnappable`: the 3-node stub has no road node within 2000 m of the synthetic villages) and `fallback_reason plan_failed`. Its rows were removed by hand afterwards (the demo never cleans up).
- Pending orchestrator rebuild: the API image was not rebuilt, so the new plan-endpoint behaviour (failed plans, new fields) is proven only with the FakeEngine tests, not against the running container.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `record_trigger` implemented in the tracer commit**
- **Found during:** Task 1
- **Issue:** `SqlPlanningRepository.record_trigger` (Task 1) delegates to `triggers.record_trigger` (Task 2), so the function had to exist for the repository to type-check.
- **Fix:** `record_trigger` and its constants landed with the tracer; Task 2's RED tests therefore cover the road and shelter detectors, and the 299 s / 301 s boundary and SQL-order tests (which passed on arrival, being tests of already written behaviour).
- **Commit:** a4f3f8c

**2. [Rule 1 - Bug] Integration fixture teardown failed on `shared_state_snapshots`**
- **Found during:** Task 3 live run
- **Issue:** The Phase 2 fixture did not delete snapshots, so the incident delete hit a foreign key error and the whole cleanup transaction rolled back, leaving the incident, hotspots and weather row behind.
- **Fix:** Fixture deletes snapshots first and audit rows by incident; the leftovers from that single failed run were removed by hand (rows identified by the `TEST-` incident code and the fixture's exact timestamp).
- **Files modified:** tests/integration/test_coordinator_pipeline.py
- **Commit:** 05b851d

**3. [Rule 2 - Missing critical functionality] jsonb-safe trigger details**
- **Issue:** An infinite perimeter growth ratio serialises as `Infinity`, which Postgres jsonb rejects.
- **Fix:** `replan._json_safe` stores non-finite floats as null before `record_trigger`.
- **Commit:** a4f3f8c

**4. [Process] Accidental repo-wide `ruff format apps`**
- A format run touched eight unrelated files. Their content was restored with `git diff | git apply -R`; they show as modified in `git status` only because of CRLF working-copy line endings (`git diff` is empty for them), and none of them is part of any commit. `incidents.py` and its test were formatted by ruff as part of the intended edits, so the API diff includes some reflowed existing lines.

## Known Stubs

None.

## Issues Encountered

- The replay demo prints `LLM Model: anthropic/openai/gpt-oss-20b`, a provider/model label mismatch that comes from `base_model_metadata` and was not touched by this plan.
- `git status` keeps listing four CRLF-only files as modified (ca_model.py, test_costs_horizons.py, test_audit.py, test_clustering.py); nothing to commit.

## Threat Flags

None. No new endpoints or trust boundaries beyond the plan's register. T-03-11-01 (storm churn: 300 s coalescing plus the D-16 gate), T-03-11-02 (new immutable version with parent link), T-03-11-03 (trigger `handled_run_id` and `replan_no_change` audit node), T-03-11-05 (allow-list in `record_trigger`, `replan_incident`) and T-03-11-06 (parameterised SQL, enum and jsonb CASTs) are mitigated and tested; T-03-11-04 stays accepted (read-only, loopback API until Phase 4).

## Self-Check: PASSED

- Created files exist: replan.py, test_replan_entry.py, test_replan_triggers.py, test_replan_db.py.
- Commits present: a4f3f8c, af5f393, 4a78d8d, c16064f, 05b851d.

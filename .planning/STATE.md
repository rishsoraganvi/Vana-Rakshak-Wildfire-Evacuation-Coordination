---
gsd_state_version: 1.0
current_phase: 03
status: executing
stopped_at: Completed 03-11-PLAN.md
last_updated: "2026-10-17T15:24:03.306Z"
state_head: ac71fed511bc2ef0c219042a79eea1e2d3c736c7
progress:
  total_phases: 6
  completed_phases: 2
  total_plans: 24
  completed_plans: 23
  percent: 50
current_phase_name: Capacity-Aware Coordinated Planning
---

# Project State

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-10-01)

**Core value:** A human reviewer can quickly understand and safely approve or correct a traceable evacuation plan built from current hazard, route, shelter, and resource data.
**Current focus:** Phase 03 — Capacity-Aware Coordinated Planning

## Current Position

Current Phase: 03

- Phase: 3 of 6 (executing)
- Current Plan: 12 of 12 (03-01..03-11 done; next is 03-12)
- Status: Plan 03-11 complete; Phase 2 verification human_needed (2 non-blocking UAT items)
- Progress: 92% of Phase 3 (11/12 plans)
- Last activity: Plan 03-11 executed - on-demand re-planning (no background worker): detect_perimeter_change (EPSG:32643, IoU < 0.8 or growth > 25% from config), detect_road_blocked, detect_shelter_capacity_change, record_trigger (per incident+type coalescing within 300 s anchored on the first uncoalesced trigger, pg_advisory_xact_lock, injected Clock, allow-list of the three Phase 3 types), replan_incident / check_and_replan over run_coordinator with one bounded state-conflict retry (new_version / no_change / coalesced / conflict), SqlPlanningRepository.record_trigger + in-memory twin; GET /incidents/{id}/plan now serves draft, pending_review and failed plans with validation, failure_reasons, alerts, parent_plan_id and stored freshness (API image rebuild pending orchestrator); replay demo and live pipeline test updated to Phase 3 statuses; live test_replan_db green. Previously: Plan 03-10 executed - ten-node Phase 3 coordinator over injected CoordinatorDeps (no SQL in nodes): per-cluster weather that fails the plan closed naming the cluster (WR-01, D-21), assess_risk, run_specialists (asyncio.gather + to_thread + wait_for on a private loop, ToolResult envelope, shelter/traffic_routing audit rows), plan_draft + grounded rationale + finalize_plan, material-change gated persist_plan (replan_no_change), audit flush then mark_trigger_handled, run_failed flush on a crashed run, age_min on every weather snapshot, Phase 2 coordinator tests migrated; live audit-agent test green (replay demo and live integration test updated in 03-11). Previously: Plan 03-09 executed - deterministic planning core (pure library): PlanningParams, build_assignment (min-cost flow over ETA-aware costs, first safe of k=3 paths, up to 3 MSA-damped BPR passes with early stop), plan_draft (preflight fail-closed, zero-group valid draft, V1-V7 gate), bounded resolver (range(conflict_max_loops), fixed next_path/rematch/split order or enum-only LLM choice, ResolverStep per loop), greedy fallback planner, failed drafts naming unplaceable groups; Hypothesis capacity/completeness/loop-cap/determinism properties and a validate-every-producer spy; fixed fix-menu key regex that rejected V3 codes with digits (graph.py not yet wired, 03-10 must call plan_draft and pass clusters via PlanInputs). Previously: Plan 03-08 executed - versioned immutable plan persistence: PlanningRepository (SQL + in-memory twin), persist_plan under pg_advisory_xact_lock with state_version check and FOR SHARE capacity re-check, shared_state_snapshots, material-change signature/plan_diff (D-16), SharedState TechSpec 5 sections, ADR-002; immutability trigger proven live (graph.py still uses the old assemble_plan SQL until 03-10). Previously: Plan 03-06 executed - Fire assess_risk (groups with interpolated ETA/priority, needs_rescue_response, p90_only_exposure, unknown_population) and pure validators V1-V7 with ValidationContext, run_structural_validators, has_blocking_failure, violation_summary; Hypothesis iff-properties for V4/V5/V6 (V1-V7 NOT yet wired into a pipeline; plan 03-10 must pass clusters_referenced). Previously: Plan 03-07 executed - plan assembly: finalize_plan (S5 gate, failed vs pending_review, as_failed), strict V8 grounding with template replacement, build_freshness/build_provenance, generate_plan_rationale and enum-only choose_fix_strategy with strict json_schema (all Groq calls mocked in tests). Previously: Plan 03-05 executed - routing upgraded: per-horizon fire costs on a single STRtree pass, edge-status blocking, settlement-to-shelter cost matrix on the nearest-horizon rule, per-edge exposure evaluation, lazy k=3 Yen on a collapsed DiGraph, BPR congestion with MSA, load-only graph loader (GraphNotBuiltError) and scripts/build_osm_graph.py (written and unit-tested, NOT run). Previously: Plan 03-04 executed - migration 0006 applied (head 0006: shelters, shelter_occupancy, failed status, plan_versions provenance + immutability trigger, road_edge_status), labelled synthetic seed (20 shelters, 10 settlements) loaded, shelter registry with exact usable capacity, perimeter exclusion and atomic update_occupancy. Previously: Plan 03-03 executed - WR-03 fixed (parse_open_meteo splits observations from forecasts with a required origin; hotspot-trigger incidents carry the real origin). Previously: Plan 03-02 executed - Phase 3 contracts (IntegratedPlan S5/D-11 invariants, ToolResult), shared nearest-horizon rule, footprint unions, validated Phase 3 config block

## Decisions and Constraints

- The supplied `generatedPlan` documents are the current product source of truth.
- This is a decision-support prototype, not an operational emergency authority.
- Human approval is mandatory before dissemination.
- Numeric/safety-critical outputs are deterministic and validated; LLM output is bounded to orchestration and grounded text.
- GSD workflow: YOLO mode, standard granularity, parallel execution, research enabled, verifier enabled, plan-check disabled, source grounding enabled.

## Pending Decisions

- Final AOI polygon versus initial bounding box.
- MVP pilot settlement cluster.
- English/Kannada translation scope.
- LLM provider/model and budget.
- Calibration data beyond FIRMS and exact benchmark baselines.

## Recent Decisions

- Phase 2 Plan 1 complete: Phase 2 schemas exported, DBSCAN clustering, Weather Agent, and CA 3-seed ensemble simulator implemented and tested.
- Phase 2 Plan 2 complete: OSM Graph, Route Utility, Coordinator v0, and additive plan/audit migration.
- Phase 2 Plan 3: Read-only API (/api/v1), Audit rows persistence, Replay script, Integration and Smoke test suite.
- Route results identify exactly one settlement or fire-cluster origin; Coordinator routes use cluster origins.
- Safe road nodes nearest each AOI boundary are route exits because OSM data has no explicit exit tags.
- Existing `agent_runs` is extended additively, with full CoordinatorPlan JSON stored in `plan_versions.plan_data`.
- Trigger details retain exact hotspot IDs so Coordinator observations remain incident-scoped.
- HI-06: compose publishes Postgres/Redis on 127.0.0.1 only and requires POSTGRES_PASSWORD; app config defaults carry no DB password (DATABASE_URL from env/.env supplies it).
- HI-03/HI-04: weather lookup is scoped by hotspot location, provider, incident origin and valid_time <= now; weather unavailable means no plan (no fabricated observation).

## Next Action

Complete the 2 Phase 2 UAT items with `/gsd-verify-work 2` (02-UAT.md). Operator note: set DATABASE_URL host to 127.0.0.1 in .env (localhost adds ~200 s IPv6 timeout per connection since 02-08 loopback binding).

---
*State initialized: 2026-10-01*

## Session

**Last session:** 2026-10-17T15:24:02.089Z
**Stopped at:** Completed 03-11-PLAN.md
**Resume file:** None

## Performance Metrics

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 02 P02 | 94 min | 7 tasks | 25 files |
| Phase 02 P03 | 22 min | 8 tasks | 13 files |
| Phase 02 P04 | 25min | 2 tasks | 4 files |
| Phase 02 P05 | 20min | 2 tasks | 4 files |
| Phase 02 P06 | 45min | 3 tasks | 11 files |
| Phase 02 P07 | 40min | 3 tasks | 8 files |
| Phase 03 P01 | 40min | 3 tasks | 18 files |
| Phase 03 P02 | 35min | 3 tasks | 10 files |
| Phase 03 P03 | 25min | 2 tasks | 7 files |
| Phase 03 P05 | 50min | 3 tasks | 12 files |
| Phase 03 P07 | 40min | 3 tasks | 14 files |
| Phase 03 P08 | 55min | 3 tasks | 7 files |
| Phase 03 P09 | 55min | 3 tasks | 11 files |
| Phase 03 P10 | 60min | 3 tasks | 17 files |
| Phase 03 P11 | 50min | 3 tasks | 10 files |

## Decisions

- [Phase 3]: 03-08: persist_plan is the only plan_versions writer (lock, state check, capacity re-check, MAX+1, insert, status-only supersede, state bump, snapshot in one transaction); capacity_violations is one pure function shared by SQL and in-memory repositories; rejected/approved plans are never superseded; diff identity is the (group, shelter) pair; mark_trigger_handled must follow flush_audit (FK to agent_runs)
- [Phase 2]: 02-04: CA wind_from_deg is meteorological FROM; spread_direction_deg is None when P50 shift < 1 cell; metrics use front advance over real horizon
- [Phase 2]: 02-05: fire exposure tested on full edge geometry (intersects); compute_route searches unblocked first then least-blocked (1e6 x travel_time); inf still means blocked (D-06)
- [Phase 2]: 02-06: generate_rationale audit rows carry model_metadata (JSON text at flush); Groq called only when llm_enabled + provider groq + model + key; default model openai/gpt-oss-20b (config); blank env vars treated as unset; Groq prompt carries compact metrics (no WKT) to stay under on-demand TPM
- [Phase 2]: 02-07: fire_results (one per cluster) replaces singular fire_result; all routing penalised by union of every cluster current/P50 perimeters; origin = nearest node outside union current perimeter; blocked fallback keeps least-exposure route; replay route on 3-node stub is truthfully blocked
- [Phase 3]: 03-01: agent_shelter.match_groups_to_shelters uses integer-decisecond nx.min_cost_flow with a diagnostic U sink; uv.lock revision header kept at 5 by hand (local uv 0.12.5 writes 3, CI pins 0.8.17); types-networkx not installed locally so mypy was verified with --ignore-missing-imports
- [Phase 3]: 03-07: V8 strips plan names before scanning (a registry name inside a longer plan name is not a violation); finalize fails closed if the deterministic template ever fails V8; choose_fix_strategy returns out_of_menu without a repair call, repair retry only for invalid JSON/shape; fix-menu payload is loop index + allowed + Vn:code counts and rejects ids/names with ValueError
- [Phase 3]: 03-02: IntegratedPlan enforces S5 (pending_review needs V1..V8 in order, none failing) and D-11 (failed plan has no routes/assignments, needs a reason) in the schema; freshness/provenance required; nearest_horizon_h ties go later; Settings rejects any fix_menu_order other than next_path/rematch/split
- [Phase 3]: 03-03: WR-03 fixed - parse_open_meteo requires an origin and sets is_forecast = valid_time > issued_at; record_new_hotspot_trigger requires a validated origin bound via CAST(:origin AS data_origin); both allow-lists derive from wildfire_core Origin
- [Phase 3]: 03-05: horizon costs come from one shapely STRtree per perimeter (no per-edge loops); cost matrix picks the horizon from free-flow time via wildfire_core nearest_horizon_h, evaluate_path from end-of-edge arrival (same rule as V3); load_graph never downloads and the real OSM build is the human-run scripts/build_osm_graph.py (plan 03-12 checkpoint); graph builds fall back to a 30 km/h speed only when the extract has no maxspeed tags
- [Phase 03]: [Phase 3]: 03-10: coordinator is ten nodes over injected CoordinatorDeps (no SQL in nodes); run_specialists closes a private loop so a timed-out specialist cannot hold the run; per-cluster weather fails the plan closed naming the cluster; shelters snap away from group origin nodes; write_audit flushes before mark_trigger_handled; a crashed run flushes audit plus run_failed
- [Phase 3]: 03-11: re-plan triggers are detected on demand (no worker) against the latest non-superseded plan; record_trigger coalesces per (incident, type) within trigger_debounce_s anchored on the first uncoalesced trigger under pg_advisory_xact_lock with time from the injected Clock; only perimeter_change, road_blocked and shelter_capacity_change are accepted; replan_incident retries a state_version conflict once; the plan endpoint serves failed plans (read-only, loopback, AR-06)

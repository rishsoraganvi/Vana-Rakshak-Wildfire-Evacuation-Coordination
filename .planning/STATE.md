---
gsd_state_version: 1.0
current_phase: 03
status: executing
stopped_at: Completed 03-01-PLAN.md
last_updated: "2026-10-17T12:27:42.005Z"
state_head: 32c54a5ad4930654e861757e5555d09517e0405a
progress:
  total_phases: 6
  completed_phases: 2
  total_plans: 24
  completed_plans: 13
  percent: 36
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
- Current Plan: 2 of 12
- Status: Plan 03-01 complete; Phase 2 verification human_needed (2 non-blocking UAT items)
- Progress: 8% of Phase 3 (1/12 plans)
- Last activity: Plan 03-01 executed - agent-shelter min-cost-flow matcher with Hypothesis capacity/conservation properties, synthetic graph fixture, CI covers apps/packages/tests/unit

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

**Last session:** 2026-10-17T09:35:02.255Z
**Stopped at:** Completed 03-01-PLAN.md
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

## Decisions

- [Phase 2]: 02-04: CA wind_from_deg is meteorological FROM; spread_direction_deg is None when P50 shift < 1 cell; metrics use front advance over real horizon
- [Phase 2]: 02-05: fire exposure tested on full edge geometry (intersects); compute_route searches unblocked first then least-blocked (1e6 x travel_time); inf still means blocked (D-06)
- [Phase 2]: 02-06: generate_rationale audit rows carry model_metadata (JSON text at flush); Groq called only when llm_enabled + provider groq + model + key; default model openai/gpt-oss-20b (config); blank env vars treated as unset; Groq prompt carries compact metrics (no WKT) to stay under on-demand TPM
- [Phase 2]: 02-07: fire_results (one per cluster) replaces singular fire_result; all routing penalised by union of every cluster current/P50 perimeters; origin = nearest node outside union current perimeter; blocked fallback keeps least-exposure route; replay route on 3-node stub is truthfully blocked
- [Phase 3]: 03-01: agent_shelter.match_groups_to_shelters uses integer-decisecond nx.min_cost_flow with a diagnostic U sink; uv.lock revision header kept at 5 by hand (local uv 0.12.5 writes 3, CI pins 0.8.17); types-networkx not installed locally so mypy was verified with --ignore-missing-imports

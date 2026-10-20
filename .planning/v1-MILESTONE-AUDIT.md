---
milestone: v1
audited: 2026-10-20T00:00:00Z
status: gaps_found
scores:
  requirements: 9/26
  phases: 3/6
  integration: 5/10
  flows: 1/5
gaps:
  requirements:
    - id: "SAFE-01..05, PLAT-01, PLAT-04"
      status: "unsatisfied"
      phase: "4"
      claimed_by_plans: []
      completed_by_plans: []
      verification_status: "missing"
      evidence: "Phase 4 not started (no phase directory). Note V1-V8 validators (SAFE-01 substance) already exist from Phase 3, but SAFE-01 is mapped to Phase 4."
    - id: "PLAT-03, PLAT-05"
      status: "unsatisfied"
      phase: "5"
      claimed_by_plans: []
      completed_by_plans: []
      verification_status: "missing"
      evidence: "Phase 5 not started."
    - id: "PLAN-05, PLAN-06, PLAT-07"
      status: "unsatisfied"
      phase: "6"
      claimed_by_plans: []
      completed_by_plans: []
      verification_status: "missing"
      evidence: "Phase 6 not started."
    - id: "MON-01"
      status: "partial"
      phase: "1"
      claimed_by_plans: ["01-02", "01-03"]
      completed_by_plans: ["01-02", "01-03"]
      verification_status: "passed (PARTIAL BY DESIGN)"
      evidence: "Parser, dedupe and idempotent upsert verified. No poller exists; ingest_hotspots (ingest_worker/firms/service.py:12) has no production caller. Live polling deferred by D-09 with no phase owning it."
    - id: "MON-02"
      status: "partial"
      phase: "1"
      claimed_by_plans: ["01-02", "01-03"]
      completed_by_plans: ["01-02", "01-03"]
      verification_status: "passed (PARTIAL BY DESIGN)"
      evidence: "Weather normalization/freshness persisted. No polling, and no wind-shift detector anywhere (only a comment at ingest_worker/triggers.py:21; replan.py detectors cover perimeter, road-blocked, shelter capacity only)."
    - id: "PLAN-07"
      status: "partial"
      phase: "3"
      claimed_by_plans: ["03-07", "03-09"]
      completed_by_plans: []
      verification_status: "passed (phase status human_needed)"
      evidence: "03-VERIFICATION SATISFIED; no SUMMARY lists it in requirements-completed (bookkeeping). REQUIREMENTS.md unchecked."
    - id: "PLAN-08"
      status: "partial"
      phase: "3"
      claimed_by_plans: ["03-07", "03-08"]
      completed_by_plans: []
      verification_status: "passed (phase status human_needed)"
      evidence: "03-VERIFICATION SATISFIED; no SUMMARY lists it. REQUIREMENTS.md unchecked."
    - id: "PLAT-06"
      status: "partial"
      phase: "2/5"
      claimed_by_plans: ["02-03", "02-04", "02-05"]
      completed_by_plans: ["02-03", "02-04", "02-05"]
      verification_status: "passed (Phase 2 slice)"
      evidence: "Cross-phase requirement; closes in Phase 5. Checkbox [x] in REQUIREMENTS.md is premature (per 02-VERIFICATION)."
  integration:
    - from: "Phase 1 ingest"
      to: "Phase 2/3 coordinator"
      issue: "No production caller of ingest_hotspots / ingest_weather / record_new_hotspot_trigger; coordinator only entered from scripts/replay_demo.py or replan.py."
      requirements: ["MON-01", "MON-02", "MON-03"]
    - from: "Phase 3 replan"
      to: "any entry point"
      issue: "check_and_replan / replan_incident have no caller (no API route, no worker). Consistent with D-14/D-15 on-demand-only, but nothing invokes the on-demand path."
      requirements: ["PLAN-08", "SAFE-05"]
    - from: "Phase 1 SharedState writer"
      to: "Phase 3 persist_plan"
      issue: "save_shared_state (wildfire_core/db/repositories.py:93) is orphaned; Phase 3 writes shared_state_snapshots via its own SQL (coordinator/repository.py:345, 581)."
      requirements: ["MON-03"]
    - from: "Phase 1 classify_freshness"
      to: "Phase 2 weather / Phase 3 build_freshness"
      issue: "Classifier (wildfire_core/state.py:10) orphaned; weather agent and finalize.build_freshness compute freshness independently."
      requirements: ["MON-04"]
    - from: "Phase 1 SimClock"
      to: "replay demo"
      issue: "replay_demo uses RealClock; replay is not time-deterministic."
      requirements: ["PLAT-05"]
  flows:
    - name: "Live hotspot -> ingest -> trigger -> coordinator -> plan -> API"
      breaks_at: "ingest (no poller)"
    - name: "Re-plan on perimeter / road / shelter change"
      breaks_at: "entry (check_and_replan has no caller)"
    - name: "Wind shift -> re-plan"
      breaks_at: "detection (no detector)"
    - name: "Reviewer approve -> disseminate"
      breaks_at: "not built (Phase 4)"
tech_debt:
  - phase: 01-foundations-and-data-contracts
    items:
      - "No VALIDATION.md (Nyquist) and no SECURITY.md"
      - "Orphaned exports: save_shared_state, classify_freshness"
      - "Permanent weather-persistence integration assertion suggested by verifier"
  - phase: 02-mvp-detection-to-route
    items:
      - "Human UAT open: Bandipur exit/route suitability; operator confirmation of live Groq path"
      - "02-VALIDATION.md nyquist_compliant: false"
      - "Append-only agent_runs enforced by convention only (no DB trigger/REVOKE)"
      - "CA RNG re-seeded per horizon; 3-seed 'P90' is any-of-3 (MD-05, LO-03); model uncalibrated"
      - "ensemble settlements_at_risk=() (superseded by Phase 3 assess_risk)"
      - "FIRE-01/02 ownership: traceability says Phase 1, delivered in Phase 2"
  - phase: 03-capacity-aware-coordinated-planning
    items:
      - "UAT status testing: 3 pending items (real-graph live run, V3 start-node policy WR-07, sourced capacities D-18)"
      - "WR-01: failed re-plan supersedes last valid pending_review plan (decide with Phase 4 'current plan' semantics)"
      - "WR-06: incident whose only trigger is coalesced has no linked hotspots -> cannot plan"
      - "WR-08: valid_until not refreshed on non-material re-plans and not enforced at read time"
      - "WR-04 residual: V8 numbers not unit-anchored (small integers ground against any plan number)"
      - "WR-02/03/09 SQL verified offline by string assertions only; compose integration re-run pending"
      - "docs/datasets.md lead section stale (describes SYN-* seed)"
      - "Shelter capacities / populations still synthetic estimates (S9 warning)"
      - "update_occupancy has no production caller (by design until Phase 4 approval)"
  - phase: cross-phase
    items:
      - "REQUIREMENTS.md bookkeeping stale: traceability rows Pending; PLAN-01/03/04/07/08, MON-*, FIRE-* unchecked; PLAT-06 prematurely checked"
      - "SUMMARY frontmatter requirements-completed empty for 02-06..09 and 03-01..11"
      - "ROADMAP has no milestone boundary; STATE says completed_phases 2 while init reports 3"
      - "API audit route is /api/v1/audit/{incident_id}; no /incidents/{id} detail route"
      - "scripts/replay_demo.py seeds hotspots by raw SQL, bypassing ingest + trigger path"
nyquist:
  compliant_phases: ["03"]
  partial_phases: ["02"]
  not_validated_phases: []
  missing_phases: ["01"]
  overall: partial
---

# Milestone v1 Audit — Vana-Rakshak

**Audited:** 2026-10-20
**Status:** gaps_found
**Scope:** v1 = all 6 ROADMAP phases (no milestone boundary is defined in ROADMAP.md). Phases 1-3 are executed and verified; Phases 4-6 have not started.

## Verdict

The work that exists is solid. Phases 1-3 each have a verification report with every must-have truth verified (12/12, 14/14, 19/19), security reviews for Phases 2-3 have zero open threats, and the offline suite is green (508 passed, 1 skipped at the Phase 3 re-verification). The milestone is not complete, though. Half the roadmap is unbuilt, and that half includes the core safety value: human approval before dissemination (SAFE-02). There are also cross-phase wiring gaps: the live ingest path, the re-plan entry point and wind-shift detection are not connected to anything.

## Phases

| Phase | Plans | Verification | UAT | Nyquist | Security |
|---|---|---|---|---|---|
| 1 Foundations and Data Contracts | 3/3 | passed 12/12 | n/a | MISSING | none |
| 2 MVP Detection to Route | 9/9 | passed 14/14 (2 human items) | complete | PARTIAL (validated, nyquist_compliant false) | verified, 0 open |
| 3 Capacity-Aware Coordinated Planning | 12/12 | human_needed 19/19 | testing, 3 pending | COMPLIANT | verified, 0 open |
| 4 Human Review and Dissemination Safety | — | missing | — | — | — |
| 5 Command Dashboard and Replay | — | missing | — | — | — |
| 6 Simulation, Calibration, Scale, Evaluation | — | missing | — | — | — |

## Requirements Coverage (3-source cross-reference)

| REQ | Phase | VERIFICATION | SUMMARY | REQUIREMENTS.md | Final |
|---|---|---|---|---|---|
| MON-01 | 1 | partial by design | listed | [ ] | **partial** (no poller) |
| MON-02 | 1 | partial by design | listed | [ ] | **partial** (no poller, no wind-shift detector) |
| MON-03 | 1 | satisfied | listed | [ ] | satisfied |
| MON-04 | 1 | satisfied | listed | [ ] | satisfied |
| FIRE-01 | 1→2 | satisfied (P2) | listed | [ ] | satisfied |
| FIRE-02 | 1→2/3 | satisfied (P3 assess_risk with interpolated ETA) | listed | [ ] | satisfied |
| PLAN-01 | 2/3 | satisfied (parallel via `dispatch.py` asyncio.gather) | listed | [ ] | satisfied |
| PLAN-02 | 2 | satisfied | listed | [x] | satisfied |
| PLAN-03 | 3 | satisfied | listed (03-12) | [ ] | satisfied |
| PLAN-04 | 3 | satisfied | listed (03-12) | [ ] | satisfied |
| PLAN-07 | 3 | satisfied | missing | [ ] | **partial** (bookkeeping) |
| PLAN-08 | 3 | satisfied | missing | [ ] | **partial** (bookkeeping; re-plan entry unwired) |
| PLAT-02 | 2 | satisfied (slice) | listed | [x] | satisfied (user-action audit arrives in P4) |
| PLAT-06 | 2/5 | satisfied (P2 slice) | listed | [x] | **partial** (closes in P5) |
| SAFE-01..05 | 4 | missing | missing | [ ] | **unsatisfied** (not started) |
| PLAT-01, PLAT-04 | 4 | missing | missing | [ ] | **unsatisfied** |
| PLAT-03, PLAT-05 | 5 | missing | missing | [ ] | **unsatisfied** |
| PLAN-05, PLAN-06, PLAT-07 | 6 | missing | missing | [ ] | **unsatisfied** |

**Score:** 9/26 satisfied, 5 partial, 12 unsatisfied. No orphans: every requirement is mapped to a phase, and every requirement for Phases 1-3 appears in a VERIFICATION file.

## Cross-Phase Integration

| # | Link | Status | Evidence |
|---|---|---|---|
| 1 | Ingest → trigger → coordinator | NOT WIRED | `ingest_hotspots`/`ingest_weather`/`record_new_hotspot_trigger` are called only from tests; the coordinator is entered from `scripts/replay_demo.py:221` and `replan.py` |
| 2 | P1 SharedState writer ↔ P3 persist_plan | PARTIAL | Shared schema, but `save_shared_state` is orphaned; P3 has its own SQL writer |
| 3 | P1 freshness classifier → weather / plan freshness | PARTIAL | `classify_freshness` orphaned; the logic exists twice in parallel |
| 4 | Audit `agent_runs` P2 → P3 graph + failed-run flush | WIRED | `audit.py:42`, `runner.py:72` `_flush_failed_run` |
| 5 | P3 plans → `GET /api/v1/incidents/{id}/plan` | WIRED | `incidents.py:175-213` serves status, validation, freshness, parent_plan_id |
| 6 | Clock injection | PARTIAL | `CoordinatorDeps.clock` is injectable; the replay demo uses RealClock |
| 7 | Migrations 0001-0006 ↔ repositories | WIRED | Chain present; table names match |
| 8 | Parallel specialist dispatch | WIRED | `dispatch.py:33,63` |
| 9 | Wind-shift detection | NOT WIRED | No detector |
| 10 | Re-plan entry point | NOT WIRED | `check_and_replan` has no caller |

**Score:** 5/10 wired.

## E2E Flows

| Flow | Status |
|---|---|
| Replay fixture → coordinator → validated versioned plan → API read | COMPLETE, but only via the manual `replay_demo.py` (bypasses ingest/trigger; on the 3-node stub graph every plan fails by design) |
| Live hotspot → ingest → trigger → plan | BROKEN at ingest (no poller; D-09) |
| Material change → re-plan → new version | BROKEN at entry (library tested, no caller) |
| Wind shift → re-plan | BROKEN (no detector) |
| Approve → disseminate | NOT BUILT (Phase 4) |

**Score:** 1/5 complete.

## Nyquist Coverage

| Phase | VALIDATION.md | Compliant | Action |
|---|---|---|---|
| 01 | missing | — | `/gsd-validate-phase 1` |
| 02 | exists (validated) | false | `/gsd-validate-phase 2` |
| 03 | exists (validated) | true | — |

## Tech Debt

The frontmatter lists every item. These matter most before Phase 4:
- **WR-01:** a failed re-plan supersedes the last valid plan. This must be settled together with the Phase 4 "current plan" approval semantics.
- **WR-07:** under the V3 start-node policy, the most urgent groups can be impossible to place. A domain decision is needed.
- **D-18:** shelter capacities and populations are still synthetic estimates.
- **WR-06:** an incident whose only trigger was coalesced cannot be planned.
- **REQUIREMENTS.md / SUMMARY bookkeeping** is stale. Seven satisfied requirements are still unchecked, and PLAT-06 is checked too early.

## Integration checker corrections

The integration checker (haiku) made three claims that the orchestrator overrode after reading the code: parallel dispatch is present (`dispatch.py`), the failed-run audit flush is wired (`runner.py:72`), and settlement ETA is computed (`risk.py:50-71`).

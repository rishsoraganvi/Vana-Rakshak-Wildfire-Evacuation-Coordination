---
phase: 03-capacity-aware-coordinated-planning
verified: 2026-10-20T20:30:00Z
status: human_needed
score: 19/19 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 17/19
  gaps_closed:
    - "03-07: template rationale passes V8 for every generated draft (truth 11) - alerts now carry settlement_name, grounded as a plan name"
    - "D-20/D-21 end to end: a settlement inside the perimeter or P90-only is alerted and the plan is still produced for all other groups (truth 19)"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Run the planner on the REAL Bandipur graph with the real-location seed and an operator-chosen fire, and judge the plan (live stack)"
    expected: "A pending_review plan (or a failed plan whose reasons make operational sense) with routes that follow real roads to real schools; capacities flagged as estimates"
    why_human: >
      The replay demo forces the 3-node stub graph, so every live plan is a failed plan by design, and no
      pending_review plan has been observed on the real graph in the live stack. Offline, the previous
      verification ran the real 570-node graph + 20 OSM shelters + 10 OSM settlements with synthetic fires
      (engulfing fire: honest V5 failure; small fire at one village: V3 failure, see next item). Whether
      the outputs are sensible is a domain judgement.
  - test: "Decide the V3 start-node policy (WR-07 / D-07 / D-21): a settlement whose own road start lies inside the 1 h P50 footprint fails V3 for every shelter"
    expected: "Either confirmed as fail-closed policy, or a rule for 'depart through the P50 zone when it is the only way out, flagged high risk' (and optionally naming the origin-edge cause in the failure reason)"
    why_human: >
      Locked decisions D-07/D-21 and TechSpec V3 make this fail-closed, so it is not a gap, but the planner can only
      produce an approvable plan when the departure edges are outside the P50 footprint. Policy trade-off between
      safety and availability for maintainers and a domain operator. Review finding WR-07 was skipped for this reason.
  - test: "Replace estimated shelter capacities and settlement populations with sourced figures (D-18 remains open)"
    expected: "Rows carry a real capacity_source/pop_source and is_simulated=false; the S9 estimate warning disappears from plans"
    why_human: "No surveyed capacity or Census population exists in the repo; seed CSVs carry real OSM names/locations but all numbers are labelled synthetic (03-12 SUMMARY, check_real_data probe)."
---

# Phase 3: Capacity-Aware Coordinated Planning Verification Report

**Phase Goal:** A Coordinator assembles a validated, versioned integrated plan using dynamic routing and shelter capacity constraints.
**Verified:** 2026-10-20 (re-verification after gap fixes)
**Status:** human_needed (all 19 truths verified; three human/policy items remain, none is a code gap)
**Re-verification:** Yes - after gap closure (CR-01 fix 3d28522 plus WR-02/03/04/05/09/10/11/12 fixes)

## Re-verification Summary

The single blocker from the first verification (a rescue or P90-only alert for a settlement without an evacuee group failed V8 and destroyed an otherwise valid plan) is closed. I re-ran my own earlier reproduction scripts through `run_coordinator` (in-memory repository, shared synthetic graph, no source modified) and read the fix in the code, not the SUMMARY.

| Scenario (scratch script) | Before (50a6924) | Now |
| --- | --- | --- |
| Control: 3 shelters, 1 routable group, no extra alerts | pending_review | pending_review, set-near -> Hall One |
| Extra settlement "Farville" inside the current perimeter (rescue alert) | failed, "V8 deterministic rationale failed grounding", assignments empty, V8 "unknown name: farville" | **pending_review**, alerts `['needs_rescue_response']`, no failing validator, `failure_reasons=()`, set-near -> Hall One still assigned |
| Extra settlement "Farville" reached only by P90 (P90-only alert) | failed, same reason | **pending_review**, alerts `['p90_only_exposure']`, no failing validator, set-near -> Hall One still assigned |

Alert text in the rescue and P90 cases is printed verbatim into the plan ("Farville is inside the active fire perimeter: needs rescue response ...", "Farville is reached only by the P90 forecast (first at 1h): monitor, no evacuation group"), and V8 passes on it.

Mechanism of the fix (read in code): `PlanAlert` gained `settlement_name: str | None` (`packages/wildfire_core/src/wildfire_core/schemas/plan.py:112-114`); `assess_risk` sets it on both alert kinds (`apps/agents/fire/src/agent_fire/risk.py:110, 134`); `grounding._walk` already collects any `settlement_name` key as a plan name (`NAME_KEYS`), so the alert's own settlement becomes a plan fact. `check_grounding` and `finalize_plan` were **not** loosened. The only other `PlanAlert` constructor (`graph.py:123`, cluster/system alerts) does not name settlements.

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
| -- | ----- | ------ | -------- |
| 1  | ROADMAP: property tests prove capacity and double-booking invariants | VERIFIED (regression check) | Properties unchanged (`agent_shelter/tests/test_matching_properties.py`, `coordinator/tests/test_validator_properties.py`, `test_plan_core_properties.py`); all pass in the full offline run. WR-03 changed `update_occupancy` SQL: the active and usable-capacity bound now apply to increases (`delta >= 0` path), and `occupancy + delta >= 0` applies to every delta, so the no-overbooking invariant for reservations is preserved; releases from inactive/over-allocated shelters are now allowed (intended). Matching and V4/V6 untouched. |
| 2  | ROADMAP: invalid plans are blocked | VERIFIED | `IntegratedPlan.status_invariants` and `finalize_plan` unchanged except nothing loosened; the CR-01 test `test_unnamed_alert_mentioning_a_registry_name_still_fails_closed` confirms an ungrounded alert still yields `failed`. Inverse defect (valid plan wrongly blocked) is now closed. |
| 3  | ROADMAP: a material route/shelter change creates a new version | VERIFIED | Offline: `test_perimeter_growth_replans_to_a_parent_linked_version_and_coalesces_repeats`, `test_road_blocked_on_a_route_edge_replans_around_it`, `test_deactivated_shelter_replans_to_another_shelter`, `test_replan_after_the_window_with_an_unchanged_fire_creates_no_version`, `test_occupancy_jump_crosses_but_an_unchanged_decision_makes_no_version` all PASS. WR-12 diff change read: `material_signature` adds uuid-masked sorted `failure_reasons` only when status is `failed`; assignments, node paths, validator statuses and status comparison are unchanged; same-cause failed plans with fresh cluster uuids are not material and different causes are (both tests pass). My probe: comparing a stored plan dict to the same plan gives not-material. |
| 4  | ROADMAP: provenance and freshness present on every plan | VERIFIED | Required schema fields unchanged. The new-run plans in my reproductions carry freshness and provenance (schema-required; `PlanAlert` change is additive and optional). |
| 5  | 03-01: min-cost-flow matching never exceeds capacity, conserves persons, deterministic | VERIFIED | Untouched since first verification; tests pass. |
| 6  | 03-02: contracts, shared `nearest_horizon_h`, config coefficients, fix menu pinned | VERIFIED | WR-11 adds `Settings.validate_phase3_coefficients` (rejects non-positive lane capacity, factor outside (0,1], negative BPR/k-path/snap/buffer values) mirroring `PlanningParams`; `config/defaults.yaml` values still load (tests pass), fix menu validation unchanged. |
| 7  | 03-03: observations vs forecasts split, origin mandatory | VERIFIED | Untouched. |
| 8  | 03-04: shelters table, exact usable capacity, atomic `update_occupancy`, exclusion zone, seed, migration 0006 | VERIFIED (compose-gated SQL relies on orchestrator re-run) | `update_occupancy` is still a single UPDATE with the bound in its WHERE clause and history only after success (WR-03 diff read). WR-03 is string-checked offline only; the live `test_shelters_db` re-run is with the orchestrator. |
| 9  | 03-05: per-horizon edge costs, k=3 paths, BPR, load-only graph | VERIFIED | WR-11 adds a clear `ValueError` before the capacity division in `apply_congestion`; tests pass. |
| 10 | 03-06: `assess_risk` groups/rescue/P90-only/unknown population; V1-V7 | VERIFIED | `test_risk.py` asserts alerts carry `settlement_name`; rescue edge case (settlement inside perimeter has no group, other groups still assessed) and P90-only edge case pass. |
| 11 | 03-07: finalize (S5), V8 strict grounding, template rationale passes V8 for every generated draft | **VERIFIED (was FAILED)** | Reproductions above (rescue and P90-only alert plans reach pending_review, V8 pass). New tests `test_rescue_alert_naming_a_group_less_settlement_does_not_fail_the_plan`, `test_p90_only_alert_naming_...`, `test_llm_text_naming_an_unplanned_settlement_is_still_rejected` pass. Strictness regression probe on the real alert-bearing plan (names registry: Farville, Bandipur, ...): "Farville needs rescue." pass; "Move people to Bandipur." fail (`unknown name: bandipur`); "999 persons" fail (`ungrounded number: 999`); "7 shelters" fail (`ungrounded number: 7`). WR-04 read: `_FIXED_FACTS = {1,3,6,60,180,360}`, validator ordinals `V1..V8` stripped before number harvesting; Hypothesis `test_template_rationale_is_always_grounded` and template tests pass. |
| 12 | 03-07: LLM only picks an enum from the fixed menu; failures fall back deterministically | VERIFIED | Untouched; `test_llm_menu`, `test_resolver` pass. |
| 13 | 03-08: advisory-locked MAX+1 versions, optimistic `state_version`, in-transaction capacity re-check, immutability | VERIFIED | Untouched by fixes. |
| 14 | 03-09: capacity-aware assignment, bounded resolver, distinct fallback planner, preflight fail-closed | VERIFIED | Untouched; properties pass. |
| 15 | 03-10: ten-node graph, parallel specialists, per-cluster weather, failure paths, audit flush on exception | VERIFIED | WR-09 read: `flush_audit_entries` binds `CAST(:status AS run_status)`, `failed` only for the `run_failed` marker (`RUN_FAILED_NODE` shared with `runner._flush_failed_run`); test_audit passes. |
| 16 | 03-11: three detectors, debounce, `replan_incident`, failed plans visible via API | VERIFIED | WR-10 read: `check_and_replan` returns `[]` when the stored `plan_schema_version` is not "3.0" (test `test_check_and_replan_skips_a_phase2_predecessor_instead_of_crashing` passes); WR-02 filters `hotspot_count` by `t.type = 'new_hotspot'` (SQL captured in test); WR-05 docs only. |
| 17 | 03-12: readiness probe, real graph built, seed handoff recorded | VERIFIED (D-18 partly open) | Untouched; see human items. |
| 18 | D-14/D-15: no background worker, on-demand entry only | VERIFIED | Unchanged. |
| 19 | D-20/D-21 end to end: settlement already inside the fire (or P90-only) is flagged as an alert and the plan is still produced for all other groups | **VERIFIED (was FAILED)** | Both reproductions end `pending_review` with the other group assigned to Hall One; the orchestrator's added offline test `test_settlement_inside_the_perimeter_is_alerted_and_the_plan_still_reaches_review` (in `test_pipeline_phase3.py`) passes. |

**Score:** 19/19 truths verified (0 present-but-behavior-unverified).

### Deferred Items

None formally. WR-01 and WR-08 skipped findings overlap with Phase 4 deliverables (re-plan APIs; freshness/degraded-mode endpoints) but ROADMAP Phase 4 text does not name them specifically, so they are recorded as noted debt, not deferred.

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `packages/wildfire_core/src/wildfire_core/schemas/plan.py` (`PlanAlert.settlement_name`) | optional name field | VERIFIED | Present, optional, additive; schema consumers unaffected (full suite passes). |
| `apps/agents/fire/src/agent_fire/risk.py` | alerts populate the name | VERIFIED | Both alert constructors set it. |
| `apps/coordinator/src/coordinator/planning/{finalize,grounding,rationale_template}.py` | assembly + V8 | VERIFIED | Consistent for alert text now; grounding strictness intact. |
| `apps/coordinator/src/coordinator/planning/diff.py` | material signature | VERIFIED | WR-12 extension sound (masked, failed-only). |
| All other first-verification artifacts | | VERIFIED | Unchanged or only touched by the WR fixes reviewed above. |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| `assess_risk` alert | `PlanAlert.settlement_name` -> `grounding._walk` NAME_KEYS -> `plan_names` | alert dump in draft payload | WIRED (now) |
| `finalize_plan` | `check_grounding` (V8) | template + candidate rationale | WIRED, no longer defective for alert text |
| `graph.assemble_plan` | `is_material_change` / `plan_diff` / `persist_plan` | direct | WIRED |
| `replan_incident` / `check_and_replan` | `run_coordinator`, schema-version guard | direct | WIRED |
| `flush_audit_entries` | `run_status` enum via `RUN_FAILED_NODE` | CAST | WIRED |
| `update_occupancy` | production caller | - | NOT WIRED by design (Phase 4 approval reserves seats); informational |

### Data-Flow Trace (Level 4)

Plan `rationale_md` now carries the alert text for non-group settlements (the previous HOLLOW path is fixed); all other flows are as in the first verification and FLOWING.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Offline suite | `.venv/Scripts/python.exe -m pytest apps packages tests/unit -q` (run by me) | 508 passed, 1 skipped in 77 s | PASS |
| Lint | `.venv/Scripts/python.exe -m ruff check .` | All checks passed | PASS |
| CI typing | `mypy packages/wildfire_core apps/agents/shelter/src/agent_shelter` | no issues in 27 files | PASS |
| Control run via `run_coordinator` | scratch `control.py` | pending_review | PASS |
| Rescue alert (inside perimeter) via `run_coordinator` | scratch `rescue_alert.py` | pending_review, 1 rescue alert, set-near assigned | PASS |
| P90-only alert via `run_coordinator` | scratch `p90_alert.py` | pending_review, 1 p90 alert, set-near assigned | PASS |
| V8 strictness on alert-bearing real plan | scratch `reg1.py` | unplanned registry name and ungrounded numbers rejected | PASS |
| Versioning / diff tests | `test_replan_entry.py`, `test_plan_diff.py` (21 tests) | all PASS | PASS |
| Live DB / compose | not run by me (orchestrator re-running integration suite) | n/a | RELIED ON ORCHESTRATOR |

### Probe Execution

No `probe-*.sh` is declared in any PLAN/SUMMARY and none exists. SKIPPED.

### Requirements Coverage

| Requirement | Status | Evidence |
| ----------- | ------ | -------- |
| PLAN-03 | SATISFIED | ETA-aware horizon costs, V2/V3, road-blocked re-plan test. V3 start-node scenario limit: human item 2. |
| PLAN-04 | SATISFIED | Properties, V4/V5, in-transaction re-check (WR-03 keeps the increase bound). Capacities are estimates (human item 3). |
| PLAN-07 | SATISFIED | Fixed menu, <= 3 loops, distinct fallback planner, deterministic chooser default. |
| PLAN-08 | SATISFIED (was BLOCKED partially) | Immutability, versioning, provenance, freshness, grounded rationale and warnings; alerts for rescue and P90 settlements now survive V8. |
| PLAN-01 (parallel dispatch half) | SATISFIED | Unchanged. |

REQUIREMENTS.md bookkeeping (orchestrator action): PLAN-03/04/07/08 are still unchecked and "Pending" and PLAN-01 (Phase 3) still "Pending" in the traceability table.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `planning/grounding.py` | 69-72, `_derived_numbers` | Numbers are grounded by ANY numeric plan fact (provenance params, priority, path_rank, counts): on the real alert-bearing plan "5 routes", "8 vehicles", "4 groups" still pass because 4, 5, 8 occur elsewhere in the payload | WARNING (residual of WR-04, acknowledged by the fixer) | Numbers are not unit-anchored; V8 remains strict for names, uuids and numbers absent from the plan (999, 7 rejected). Design change for the maintainer; not a phase blocker (template text is built from plan data). |
| `docs/datasets.md` | 5-20 | Lead section still describes the seed as invented `SYN-*` rows | WARNING | Stale after 03-12. |
| `coordinator/replan.py` | 86-102 | `new_perimeter_wkt` only used for detection; a perimeter re-plan re-simulates from stored hotspots | WARNING | Now documented by WR-05 (docstring precondition). |
| `planning/diff.py` | | failed plans with different failure reasons compared equal | resolved by WR-12 | closed |

No `TBD`/`FIXME`/`XXX` markers in `apps` or `packages`. No debt-marker blockers.

## Skipped Review Findings (noted debt) and Blocker Classification

All four skipped findings were examined against the phase goal and exit criteria. None breaks a ROADMAP exit criterion or a must-have truth, so none is a phase blocker. All four need a maintainer decision and should be carried into Phase 4/5 planning.

| Finding | What it is | Phase 3 blocker? | Rationale / where to resolve |
| ------- | ---------- | ---------------- | ---------------------------- |
| WR-01 | A failed re-plan supersedes the last valid `pending_review` plan | No (design decision, Phase 4 contract) | D-11/D-16 define a failed plan as an immutable versioned record; behaviour is as specified, with a reviewer-visible downside (last approvable plan becomes non-current after a transient preflight failure). Decide with Phase 4 review APIs ("current plan" semantics) before approval ships. |
| WR-06 | A new incident whose only trigger is coalesced has no hotspots linked, so it cannot get a plan | No for Phase 3 | Lives in Phase 2 ingest and Phase 5 worker linkage; D-14/D-15 keep Phase 3 on-demand only, and plans work when hotspots are linked. Must be fixed when the scheduled worker (Phase 5) creates incidents. |
| WR-07 | Highest-urgency groups may be structurally unplaceable under V3 when their start node lies in the 1 h P50 footprint | No (locked D-07/D-21 policy) | Carried as human verification item 2 (policy decision). Operationally significant: should be settled before any real-incident use. |
| WR-08 | Non-material re-plans never refresh `valid_until`/freshness, and `valid_until` is not enforced at read time | No for Phase 3 criteria (provenance and freshness are present on every plan) | Enforcement needs an API contract field and a clock source (SimClock for replay); belongs with Phase 4 freshness/degraded-mode endpoints. |

Residual items from the fixed findings that also remain open: WR-04 small integers can still be grounded by genuine plan data (design choice for V8 unit anchoring); WR-03 SQL, WR-02 SQL and WR-09 SQL are verified by string/parameter assertions offline only, so the compose-gated integration re-run (orchestrator) should confirm them, ideally with an added inactive-shelter release case.

## Human Verification Required

#### 1. Real-graph planning run in the live stack

**Test:** Run the coordinator on the real Bandipur graph and OSM seed with a fire the operator considers realistic, then read the plan.
**Expected:** A pending_review plan (or an understandable failed plan) with routes along real roads to real schools; estimate warning present.
**Why human:** Live demo uses the 3-node stub graph (failed plans by design); domain judgement of route/shelter sense.

#### 2. V3 start-node policy (WR-07)

**Test:** Review the observed behaviour (every outbound edge is a P50 hit at 1-3 min when the origin is inside the 1 h P50 polygon, plan fails) with a domain operator.
**Expected:** Confirm fail-closed as intended, or define a flagged "least-bad exit" rule.
**Why human:** Policy trade-off between safety and availability; implemented per D-07/D-21.

#### 3. Sourced capacities and populations (D-18)

**Test:** Replace estimates with surveyed figures and real source labels.
**Expected:** `check_real_data.py` reports curated; S9 warning no longer attached.
**Why human:** Data the repository does not contain.

## Gaps Summary

No gaps. Both previously failed truths (11 and 19) are verified by direct reproduction through `run_coordinator` and by reading the fix; the 17 other truths pass the regression check, V8 remains strict for LLM text and unknown names/numbers, and the WR-12 diff change preserves versioning (21 versioning/diff tests pass, including no-version-on-unchanged-world). Status is `human_needed` solely because three operator/policy items remain open (real-graph live run, V3 start-node policy, sourced capacities), plus the orchestrator's pending integration-suite confirmation of the SQL-touching fixes. If the integration suite passes and those human items are accepted or deferred, Phase 3 can be marked complete.

---

_Verified: 2026-10-20_
_Verifier: Claude (gsd-verifier)_

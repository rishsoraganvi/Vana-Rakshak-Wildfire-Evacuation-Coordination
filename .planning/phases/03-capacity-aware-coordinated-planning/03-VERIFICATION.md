---
phase: 03-capacity-aware-coordinated-planning
verified: 2026-10-20T19:00:00Z
status: gaps_found
score: 17/19 must-haves verified
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "The deterministic template rationale passes V8 for every generated draft (03-07 must-have), and a settlement inside the current perimeter or reached only by P90 yields an alert while the plan is still produced for all other groups (D-20, D-21)"
    status: failed
    reason: >
      finalize_plan() builds the deterministic template, which appends every plan alert message
      (rationale_template._alert_lines). The alert messages written by assess_risk name the settlement
      ("Farville is inside the active fire perimeter ...", "Farville is reached only by the P90 forecast ...").
      That settlement has no EvacueeGroup, so its name is in the registry but not in the plan names, and
      check_grounding() reports "unknown name: farville". finalize_plan then takes the "cannot happen by
      construction" branch and returns a FAILED plan with the single reason
      "V8 deterministic rationale failed grounding". So any incident that has one needs_rescue_response or
      p90_only_exposure alert for a settlement other than a planned group loses its whole plan, even though
      V1-V7 pass and every other group was placed. Reproduced by this verifier (read-only scratch scripts,
      in-memory repository, shared synthetic graph): control run = pending_review; same run with one extra
      settlement inside the current perimeter = status failed, failure_reasons
      ("V8 deterministic rationale failed grounding",), shelter_assignments empty, V8 = fail
      ("unknown name: farville"); same with a P90-only settlement = status failed, same reason. The
      Hypothesis test test_template_rationale_is_always_grounded only uses an alert whose message names
      no settlement ("Needs 2 rescue teams"), so the suite is green while the real alert text is untested.
    artifacts:
      - path: "apps/coordinator/src/coordinator/planning/grounding.py"
        issue: "grounding_facts() collects names only from keys settlement_name/shelter_name/name; names that appear only inside alert messages (and other free text the template emits) are neither plan names nor excluded from the registry-name check"
      - path: "apps/coordinator/src/coordinator/planning/finalize.py"
        issue: "finalize_plan() converts a template grounding failure into a failed plan (lines ~267-271) instead of grounding the template's own alert text"
      - path: "apps/coordinator/tests/test_grounding.py"
        issue: "test_template_rationale_is_always_grounded uses a name-free alert message, so the real assess_risk alert wording is never exercised"
    missing:
      - "Ground alert text: add the settlement/shelter names referenced by plan.alerts (via PlanAlert.settlement_id -> registry name, or the alert message itself) to GroundingFacts.plan_names, or make the template compose alert lines from facts that are already grounded"
      - "Regression tests: a valid draft carrying a needs_rescue_response alert and one carrying a p90_only_exposure alert that name a non-group settlement must finalize to pending_review with V8 pass; extend the Hypothesis property so alerts use the real assess_risk message format"
      - "End-to-end test through run_coordinator (in-memory repository) with a settlement inside the current perimeter and another group that is routable: expect pending_review, one rescue alert, assignments for the other group (D-20)"
human_verification:
  - test: "Run the planner on the REAL Bandipur graph with the real-location seed and an operator-chosen fire, and judge the plan"
    expected: "A pending_review plan (or a failed plan whose reasons make operational sense) with routes that follow real roads to real schools; capacities flagged as estimates"
    why_human: >
      The replay demo forces the 3-node stub graph, so every live plan is a failed plan by design, and no
      pending_review plan has been observed on the real graph in the live stack. This verifier ran the
      real 570-node graph + 20 OSM shelters + 10 OSM settlements offline with a synthetic fire: with a fire
      engulfing all villages the plan correctly failed (V5, total estimated capacity too small); with a
      small fire next to one village it failed on V3 (see next item). Whether the outputs are sensible is
      a domain judgement.
  - test: "Decide whether V3 (P50 hit at the nearest horizon fails the plan) is the intended behaviour for a settlement whose own road start lies inside the 1 h P50 footprint"
    expected: "Either confirmed as fail-closed policy (reviewer sees a failed plan and rescue-style handling), or a rule for 'depart through the P50 zone when it is the only way out, flagged high risk'"
    why_human: >
      Observed on the real graph (offline, verifier-run): a settlement at risk because its buffer meets the
      P50 footprint has an origin node inside the 1 h P50 polygon, so every outbound edge is a P50 hit at
      1-3 minutes (nearest horizon = 1 h); V3 fails for every shelter, the resolver and fallback cannot
      repair it, and the plan is failed. This follows D-07/D-21 and TechSpec V3 literally, so it is not
      recorded as a gap, but it means the planner can only produce an approvable plan when the departure
      edges are outside the P50 footprint. Policy decision for the maintainers and a domain operator.
  - test: "Replace estimated shelter capacities and settlement populations with sourced figures (D-18 remains open)"
    expected: "Rows carry a real capacity_source/pop_source and is_simulated=false; the S9 estimate warning disappears from plans"
    why_human: "No surveyed capacity or Census population exists in the repo; seed CSVs now carry real OSM names/locations but all numbers are labelled synthetic (03-12 SUMMARY, check_real_data probe)."
---

# Phase 3: Capacity-Aware Coordinated Planning Verification Report

**Phase Goal:** A Coordinator assembles a validated, versioned integrated plan using dynamic routing and shelter capacity constraints.
**Verified:** 2026-10-20
**Status:** gaps_found (one functional blocker found by exercising the pipeline; everything else verified)
**Re-verification:** No - initial verification

## Goal Achievement

The machinery the phase promised exists, is wired, and is well tested: capacity-safe min-cost-flow matching, ETA-aware k=3 routing with BPR passes, V1-V8, a bounded resolver with a different fallback planner, immutable advisory-locked plan versions with DB trigger, on-demand re-plan with debounce, and required provenance/freshness. I read the code rather than the SUMMARYs, re-ran the offline suite (486 passed, 1 skipped, 48 s), ruff and the CI mypy command (both clean), and drove the pipeline with scratch scripts (nothing in the repo was modified).

One thing the green suite hides: the "valid plan with a rescue or P90-only alert" path (explicit decisions D-20 and D-21) ends in a FAILED plan because the deterministic rationale template fails the project's own V8 grounding check. That is a goal-level defect (a validated plan is not assembled in a scenario the phase specifically designed for), so the status is gaps_found.

### Observable Truths

ROADMAP exit criteria first (non-negotiable), then plan-level must-haves (per plan).

| #  | Truth | Status | Evidence |
| -- | ----- | ------ | -------- |
| 1  | ROADMAP: property tests prove capacity and double-booking invariants | VERIFIED | `agent_shelter/tests/test_matching_properties.py`: 5 `@given` properties at `max_examples=200` (capacity never exceeded, conservation, determinism, nothing unassigned when capacity suffices, per-pair cap). `coordinator/tests/test_validator_properties.py`: V4 passes iff every shelter within capacity, V5 iff each group sum equals persons, V6 fails iff a vehicle appears twice (200 examples each). `test_plan_core_properties.py`: valid drafts stay within capacity and fully assign, failed drafts carry nothing and name a reason, resolver loops never exceed the cap, every producer is validated (30-60 examples). `conftest.py` ci profile derandomized, 200 examples; CI runs `pytest apps packages tests/unit`. Matching code read: `available` map caps each shelter->sink edge, diagnostic unassigned sink, integer weights. Note: "double-booking" is proven for vehicles (V6, trivially empty until Phase 6) and for shelter seats (V4); that is the only meaning available in Phase 3. |
| 2  | ROADMAP: invalid plans are blocked | VERIFIED | `IntegratedPlan.status_invariants` (schema, not convention): `pending_review` requires exactly V1..V8 in order and no failing validator, no failure reasons; `failed` forbids routes/assignments and requires a reason. `finalize_plan` turns any failing validator into a failed plan. `plan_core.plan_draft` sends every producer (flow, each resolver loop, fallback) through the same `run_structural_validators` (spy tests). Persist re-checks capacity in-transaction (`CapacityRecheckFailed` -> `as_failed`). Caveat: the inverse (a valid plan wrongly blocked) is Gap 1 below. |
| 3  | ROADMAP: a material route/shelter change creates a new version | VERIFIED | `planning/diff.py` `is_material_change` compares sorted assignments, per-group node paths, validator statuses, status; volatile fields ignored. `graph.assemble_plan` persists only on material change, else `replan_no_change`. Offline tests pass: perimeter growth moves the plan off SH-1 to v2 with `parent_plan_id`, diff and `superseded` predecessor; road blocked on a route edge reroutes around it; deactivated shelter reassigns; unchanged world after the debounce window creates no version; occupancy jump that does not change the decision creates no version. Live DB (orchestrator): `test_plan_versions_db`, `test_replan_db` passed (versions 1 and 2, parent link, immutability trigger rejects `plan_data` update, status-only update allowed). |
| 4  | ROADMAP: provenance and freshness present on every plan | VERIFIED | `IntegratedPlan.freshness` and `.provenance` are required fields with no default; `finalize_plan` and `as_failed` always receive them; columns `freshness`/`provenance`/`validation`/`parent_plan_id`/`valid_until` in migration 0006 and in `_INSERT_PLAN_SQL`; API `/incidents/{id}/plan` returns stored freshness. `test_pending_and_failed_plans_carry_populated_freshness_and_provenance` passes. Orchestrator live API call returned a failed plan with failure_reasons, alerts, freshness. |
| 5  | 03-01: min-cost-flow matching never exceeds available capacity, conserves persons, names unplaceable groups with reason, splits, deterministic | VERIFIED | `matching.py` read in full; properties above; `agent-shelter` is a workspace member imported by the coordinator. |
| 6  | 03-02: contracts, shared `nearest_horizon_h`, config-driven coefficients, fix menu pinned to next_path/rematch/split | VERIFIED | `schemas/plan.py` read (S5 and failed invariants as above); `config.py` rejects any other `fix_menu_order`; `config/defaults.yaml` holds usable factor 0.6, P50 x10, k=3, BPR 0.15/4, 3 passes, 3 loops, debounce 300 s. `nearest_horizon_h` imported by both `route_checks.py` (V3) and routing. |
| 7  | 03-03 (WR-03/D-17): observations vs forecasts split, origin mandatory | VERIFIED | `parser.py`: `is_forecast=valid_time > issued_at`, `ValueError` on unknown origin, no default. No production caller of `parse_open_meteo`/`record_new_hotspot_trigger` yet (scheduled ingest is Phase 5); only scripts/tests. |
| 8  | 03-04: shelters table, exact usable capacity, atomic `update_occupancy`, exclusion zone, labelled seed, migration 0006 | VERIFIED | Migration read: `ADD VALUE IF NOT EXISTS 'failed'` first and not reused, shelters with CHECKs and GiST, history table, immutability trigger covering all content columns, `road_edge_status`. `usable_capacity` uses `Decimal` + `ROUND_FLOOR`. `update_occupancy` is one UPDATE with `BETWEEN 0 AND floor(capacity*factor)` and history only after success. `list_candidate_shelters` excludes inactive, within buffer of current UNION P90-6h, no capacity. Live DB test passed (orchestrator). `update_occupancy` has no production caller yet (reservation arrives with approval in Phase 4); plans do not reserve seats. |
| 9  | 03-05: per-horizon edge costs, k=3 loopless paths, BPR with list-string tags, load-only graph | VERIFIED | `costs.apply_horizon_costs` (blocked > p50 > p90 > safe, STRtree on full geometry, infinite for blocked/unsafe status), `k_paths`, `congestion.py` (parse_tag via `literal_eval` only for "[" strings, MSA blend), `graph.load_graph` raises `GraphNotBuiltError` instead of downloading. Real graph loads (570 nodes, 1415 edges) and a full coordinator run executed on it. |
| 10 | 03-06: `assess_risk` groups/rescue/P90-only/unknown population; V1-V7 incl. independent geometry checks | VERIFIED | `risk.py` read; V1-V3 read (V2/V3 recompute from edge geometry, V3 flags P90 without failing); V4-V7 read. See Gap 1 for the downstream consequence of the alert wording. |
| 11 | 03-07: finalize (S5), V8 strict grounding, template rationale passes V8 for every generated draft | **FAILED** | Template passes V8 only when alerts name no non-group settlement. Verifier reproduction: `needs_rescue_response` or `p90_only_exposure` alert for a non-group settlement -> `finalize_plan` returns failed plan "V8 deterministic rationale failed grounding". See Gaps. |
| 12 | 03-07: LLM only picks an enum from the fixed menu; every failure falls back to deterministic order; compact payloads | VERIFIED | `groq_adapter.choose_fix_strategy`: menu validated against `FIX_STRATEGY_MENU`, payload = loop + allowed + `Vn:code` counts, strict json_schema, gate returns `strategy=None`; `resolver.llm_chooser` re-checks membership; `default_chooser_factory` uses the deterministic chooser unless `llm_enabled`. Tests `test_llm_menu`, `test_resolver` pass (payload contains only menu names and violation codes). |
| 13 | 03-08: advisory-locked MAX+1 versions, optimistic `state_version`, in-transaction capacity re-check, shared-state snapshots, immutability, repository interface | VERIFIED | `SqlPlanningRepository.persist_plan` read: lock -> `FOR UPDATE` state_version check -> `FOR SHARE` shelter re-check -> MAX+1 -> insert -> status-only supersede -> bump + `shared_state_snapshots`. `InMemoryPlanningRepository` mirrors it; coordinator nodes touch only `deps.repository`. ADR-002 present. |
| 14 | 03-09: capacity-aware assignment, bounded resolver (<=3 loops, menu order), distinct fallback planner, preflight fail-closed, zero-group valid draft | VERIFIED | `plan_core.py`, `resolver.py` (plain `for loop in range(conflict_max_loops)`; strategies re-validate with V1-V7), `fallback_planner.py` read. Tests and Hypothesis properties pass. On the real graph the pipeline produced a failed plan naming each unplaceable group and reason when estimated capacity was insufficient. |
| 15 | 03-10: ten-node graph (Weather -> Fire -> risk -> parallel specialists -> plan), per-cluster weather, failure paths, audit flush on exception | VERIFIED | `graph.py`/`runner.py`/`dispatch.py` read: `asyncio.gather` + `to_thread` + `wait_for` for shelter and traffic_routing specialists, `ToolResult` envelopes, one audit row per specialist, `specialist_unavailable` -> failed plan, missing weather -> `weather_unavailable` fail-closed, `_flush_failed_run` writes `run_failed`. Weather and fire per cluster run sequentially before dispatch by design (Weather must precede Fire). |
| 16 | 03-11: three detectors in EPSG:32643, debounce via advisory lock and injected clock, `replan_incident`, failed plans visible through API | VERIFIED | `triggers.py` (IoU<0.8 or growth>25%, road edge on a route, shelter inactive or occupancy delta >= 10% of usable), `record_trigger` (leader lookup in the 300 s window), `replan.py`; `wind_shift`/`scheduled_refresh`/`manual` rejected with `ValueError`. API selects `status IN ('draft','pending_review','failed')` with validation, freshness, parent link. |
| 17 | 03-12: readiness probe, real graph built, seed handoff recorded | VERIFIED (D-18 partly open) | `scripts/check_real_data.py` + tests; `data/osm/bandipur_road_graph.graphml` present and git-ignored; seed CSVs carry OSM refs/locations, numbers still labelled `synthetic`; the plan's truth allows "replace or explicitly defer". See human items. |
| 18 | D-14/D-15: no background worker, on-demand entry only | VERIFIED | `check_and_replan`/`replan_incident` are library entry points; no daemon in Phase 3. |
| 19 | D-20/D-21 end to end: settlement already inside the fire (or P90-only) is flagged as an alert and the plan is still produced for all other groups | **FAILED** | Same defect as truth 11: the plan is produced as FAILED, with a misleading reason. Verifier reproduction in the Gaps section. `assess_risk` itself behaves correctly (alert + no group); the failure is downstream in `finalize_plan`. |

**Score:** 17/19 truths verified (0 present-but-behavior-unverified).

### Deferred Items

None. No later phase in ROADMAP.md covers rationale grounding of alert text. Phase 4 (review/approval) and Phase 5 (workers/dashboard) do not address it.

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `apps/agents/shelter/src/agent_shelter/matching.py`, `registry.py` | matching + registry | VERIFIED | Substantive, wired from `plan_core`/`graph`. |
| `apps/agents/routing/src/agent_routing/{costs,k_paths,congestion,router,graph}.py` | dynamic costs, k-paths, BPR, load-only graph | VERIFIED | Wired into `plan_core` and `graph.dispatch_specialists`. |
| `apps/agents/fire/src/agent_fire/risk.py` | risk assessment | VERIFIED | Wired in `assess_risk_node`. |
| `apps/coordinator/src/coordinator/validators/*` | V1-V7 | VERIFIED | Wired through `run_structural_validators`. |
| `apps/coordinator/src/coordinator/planning/{plan_core,resolver,fallback_planner,params,diff}.py` | planning core | VERIFIED | |
| `apps/coordinator/src/coordinator/planning/{finalize,grounding,rationale_template}.py` | assembly + V8 | PARTIAL | Wired, but the template/grounding pair is inconsistent for alert text (Gap 1). |
| `apps/coordinator/src/coordinator/{graph,runner,dispatch,deps,repository,replan}.py` | orchestration, persistence, re-plan | VERIFIED | |
| `apps/ingest_worker/src/ingest_worker/triggers.py` | detectors, debounce | VERIFIED | |
| `infra/migrations/versions/0006_phase3_planning.py` | schema + immutability trigger | VERIFIED | |
| `packages/wildfire_core/src/wildfire_core/schemas/{plan,state,tools}.py`, `geo/{horizons,footprint}.py`, `seed.py` | contracts | VERIFIED | |
| `config/seed/*.csv`, `scripts/{seed_*,build_osm_graph,check_real_data}.py`, `docs/datasets.md`, `docs/adr/ADR-002-*.md` | data + docs | VERIFIED | `docs/datasets.md` lead section still says the seed is invented `SYN-SH-01..20`/`SYN-ST-01..10` while the CSVs now carry `OSM-*` refs; stale prose (warning, not blocking). |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| coordinator `graph.plan_evacuation` | `plan_core.plan_draft` | direct call with `deps.chooser_factory` | WIRED | |
| `plan_core` | `match_groups_to_shelters`, `apply_congestion`/`msa_blend`, `run_structural_validators` | imports and calls | WIRED | |
| `resolver` | `groq_adapter.choose_fix_strategy` | `llm_chooser` | WIRED | |
| `graph.assemble_plan` | `finalize_plan`, `is_material_change`, `plan_diff`, `repository.persist_plan` | direct | WIRED | |
| `finalize_plan` | `check_grounding` (V8) | template + candidate rationale | WIRED but defective for alert text (Gap 1) | |
| `replan_incident` | `run_coordinator` with `trigger_id` | direct | WIRED | |
| `SqlPlanningRepository` | `fetch_shelters`, `current_edge_statuses`, `record_trigger` | delegation | WIRED | |
| `route_checks` | `nearest_horizon_h`, `edge_geometry` | imports | WIRED | |
| API `/incidents/{id}/plan` | `plan_versions.validation/freshness/parent_plan_id` | SQL | WIRED | |
| `update_occupancy` | production caller | - | NOT WIRED (by design) | Only tests/seed docs reference it; seat reservation belongs with approval (Phase 4). Informational. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| plan `groups` | persons | `settlements.population` via `assess_risk` | Yes (seed rows, labelled synthetic) | FLOWING |
| plan `shelter_assignments` | available capacity | `shelters` rows -> `usable_capacity - occupancy` | Yes (labelled estimates) | FLOWING |
| plan `routes` | node paths | real graph (570 nodes) or injected fixture | Yes (verifier ran the real graph offline) | FLOWING |
| plan `freshness` | ages | newest hotspot time, per-cluster weather age, graph mtime | Yes | FLOWING |
| plan `provenance` | seeds, run ids, shelter snapshot, params | fire results + registry + settings | Yes | FLOWING |
| plan `rationale_md` | template/LLM text | draft data | Yes, except it is discarded for plans with alerts naming non-group settlements (Gap 1) | HOLLOW for that path |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Offline suite | `.venv/Scripts/python.exe -m pytest apps packages tests/unit -q` | 486 passed, 1 skipped | PASS |
| Lint | `.venv/Scripts/python.exe -m ruff check .` | All checks passed | PASS |
| CI typing | `mypy packages/wildfire_core apps/agents/shelter/src/agent_shelter` | no issues in 27 files | PASS |
| Control run (3 shelters, 1 routable group, no extra alerts) | scratch script via `run_coordinator` + in-memory repo | `pending_review`, assignment set-near -> Hall One | PASS |
| Extra settlement inside current perimeter | same, one added perimeter patch | `failed`, reason "V8 deterministic rationale failed grounding", V8 fail "unknown name: farville" | FAIL (Gap 1) |
| Extra settlement P90-only | same, P90 patch | `failed`, same reason | FAIL (Gap 1) |
| Real graph + 20 OSM shelters + 10 OSM settlements, fire engulfing all villages | scratch script | `failed`, V5 names each unplaceable group (capacity insufficient / no reachable shelter) | PASS (honest failure) |
| Real graph, small fire at one village | scratch script | `failed`, V3 `p50_before_arrival` at 1-3 min (see human item 2) | Observation |
| Live DB / compose checks | not re-run (orchestrator: 9 compose + 3 Groq-backed passed) | n/a | RELIED ON ORCHESTRATOR |

### Probe Execution

No `probe-*.sh` is declared in any PLAN/SUMMARY and none exists in the repository. SKIPPED.

### Requirements Coverage

Requirement IDs declared in PLAN frontmatter: 03-01 PLAN-04; 03-02 PLAN-08, PLAN-03, PLAN-04; 03-03 PLAN-08; 03-04 PLAN-04, PLAN-08; 03-05 PLAN-03; 03-06 PLAN-03, PLAN-04, PLAN-08; 03-07 PLAN-07, PLAN-08; 03-08 PLAN-08; 03-09 PLAN-07, PLAN-04, PLAN-03; 03-10 PLAN-01, PLAN-07, PLAN-08; 03-11 PLAN-03, PLAN-08; 03-12 PLAN-03, PLAN-04. ROADMAP Phase 3 IDs: PLAN-03, PLAN-04, PLAN-07, PLAN-08. All four exist in REQUIREMENTS.md; PLAN-01 (parallel-dispatch half) is also claimed by 03-10. No orphaned IDs.

| Requirement | Source Plans | Description | Status | Evidence |
| ----------- | ------------ | ----------- | ------ | -------- |
| PLAN-03 | 03-02, 03-05, 03-06, 03-09, 03-11, 03-12 | Routes account for blocked/unsafe edges, fire forecast penalties, changing road conditions | SATISFIED | ETA-aware horizon costs, edge-status table, V2/V3, `road_blocked` re-plan test around a blocked edge, congestion passes. (Scenario limit: human item 2.) |
| PLAN-04 | 03-01, 03-02, 03-04, 03-06, 03-09, 03-12 | Match groups to shelters without exceeding conservative usable capacity | SATISFIED | Properties (200 examples), V4/V5, in-transaction re-check, 0.6 usable factor exact decimal. Capacities are estimates (human item 3). |
| PLAN-07 | 03-07, 03-09, 03-10 | Bounded conflict resolution, deterministic fallback when LLM unavailable | SATISFIED | Fixed menu, <=3 loops, distinct greedy fallback, deterministic chooser default, failed plan when both fail. |
| PLAN-08 | 03-02, 03-03, 03-04, 03-06, 03-07, 03-08, 03-10, 03-11 | Immutable, versioned, provenance-linked, freshness-aware plans with grounded rationale and warnings | BLOCKED (partially) | Immutability, versioning, provenance and freshness are satisfied. "Grounded rationale and warnings" breaks in the alert scenario: valid plans are replaced by failed plans (Gap 1). |
| PLAN-01 (parallel-dispatch half, claimed by 03-10) | 03-10 | Parallel dispatch of eligible specialists through typed tool contracts | SATISFIED | `dispatch.run_specialists` with `ToolResult` envelopes; concurrency test passes. |

REQUIREMENTS.md bookkeeping: PLAN-03/04/07/08 are still unchecked and "Pending" in the traceability table, and PLAN-01 still says Pending for Phase 3. The orchestrator should update them once the gap is closed.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `planning/finalize.py` | ~267-271 | Comment "Cannot happen by construction" guards a branch that does happen (alert text) | BLOCKER | Valid plans with alerts become failed plans (Gap 1) |
| `tests/test_grounding.py` | 146-150 | Property test uses a name-free alert message | WARNING | Explains why the defect shipped green |
| `docs/datasets.md` | 5-20 | Lead section still describes seed as invented `SYN-*` rows | WARNING | Stale after 03-12 |
| `coordinator/replan.py` | 86-102 | `new_perimeter_wkt` is used only for detection; the re-run rebuilds the fire from hotspots linked to uncoalesced `new_hotspot` triggers | WARNING | In production a `perimeter_change` re-plan with no new hotspots yields the same fire, so it ends `no_change`. The offline test swaps `fire_fn` to simulate growth. Acceptable until the Phase 5 worker links new hotspots, but worth stating. |
| `planning/diff.py` | 58-71 | Failed plans with identical validator statuses but different failure reasons compare equal | INFO | A re-plan that fails for a different group does not create a new version (D-16 wording says validator status differs). |

No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers in `apps`, `packages`, `scripts`, `config`, `infra`, `docs` or `tests`. No debt-marker blockers.

### Human Verification Required

#### 1. Real-graph planning run

**Test:** Run the coordinator on the real Bandipur graph and OSM seed with a fire the operator considers realistic, then read the plan.
**Expected:** A pending_review plan (or an understandable failed plan) with routes along real roads to real schools; estimate warning present.
**Why human:** Live demo uses the 3-node stub graph (failed plans by design); domain judgement of route/shelter sense.

#### 2. V3 policy for settlements already inside the 1 h P50 footprint

**Test:** Review the observed behaviour (every outbound edge is a P50 hit at 1-3 min, plan fails) with a domain operator.
**Expected:** Confirm fail-closed as intended, or define a flagged "least-bad exit" rule.
**Why human:** Policy trade-off between safety and availability; implemented per D-07/D-21.

#### 3. Sourced capacities and populations (D-18)

**Test:** Replace estimates with surveyed figures and real source labels.
**Expected:** `check_real_data.py` reports curated; S9 warning no longer attached.
**Why human:** Data the repository does not contain.

### Gaps Summary

One goal-affecting gap, one root cause. `assess_risk` (correctly) emits alerts that name settlements without groups; `template_rationale` (correctly, by D-20/D-21) prints them; `check_grounding` (correctly, by D-13) refuses registry names that are not plan names; `finalize_plan` then fails closed. Each piece is individually right, and the composition makes "a settlement is burning" or "a settlement is only in the P90 envelope" destroy an otherwise valid, validated plan. The planner's own tests miss it because the property test's alert contains no settlement name. The fix is small (ground alert-referenced names and add the end-to-end regression tests listed in the gaps frontmatter) and does not touch any other verified truth. After it lands, re-verify truths 11 and 19; everything else here is a quick regression check.

---

_Verified: 2026-10-20_
_Verifier: Claude (gsd-verifier)_

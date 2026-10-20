---
phase: 03-capacity-aware-coordinated-planning
reviewed: 2026-10-20T00:00:00Z
depth: standard
files_reviewed: 55
files_reviewed_list:
  - .github/workflows/ci.yml
  - apps/agents/fire/src/agent_fire/risk.py
  - apps/agents/routing/src/agent_routing/congestion.py
  - apps/agents/routing/src/agent_routing/costs.py
  - apps/agents/routing/src/agent_routing/graph.py
  - apps/agents/routing/src/agent_routing/k_paths.py
  - apps/agents/routing/src/agent_routing/router.py
  - apps/agents/shelter/pyproject.toml
  - apps/agents/shelter/src/agent_shelter/matching.py
  - apps/agents/shelter/src/agent_shelter/registry.py
  - apps/agents/weather/src/agent_weather/agent.py
  - apps/api_gateway/src/api_gateway/routers/incidents.py
  - apps/coordinator/pyproject.toml
  - apps/coordinator/src/coordinator/audit.py
  - apps/coordinator/src/coordinator/deps.py
  - apps/coordinator/src/coordinator/dispatch.py
  - apps/coordinator/src/coordinator/graph.py
  - apps/coordinator/src/coordinator/llm/groq_adapter.py
  - apps/coordinator/src/coordinator/planning/diff.py
  - apps/coordinator/src/coordinator/planning/fallback_planner.py
  - apps/coordinator/src/coordinator/planning/finalize.py
  - apps/coordinator/src/coordinator/planning/grounding.py
  - apps/coordinator/src/coordinator/planning/params.py
  - apps/coordinator/src/coordinator/planning/plan_core.py
  - apps/coordinator/src/coordinator/planning/rationale_template.py
  - apps/coordinator/src/coordinator/planning/resolver.py
  - apps/coordinator/src/coordinator/replan.py
  - apps/coordinator/src/coordinator/repository.py
  - apps/coordinator/src/coordinator/runner.py
  - apps/coordinator/src/coordinator/state.py
  - apps/coordinator/src/coordinator/validators/_common.py
  - apps/coordinator/src/coordinator/validators/capacity_checks.py
  - apps/coordinator/src/coordinator/validators/integrity_checks.py
  - apps/coordinator/src/coordinator/validators/route_checks.py
  - apps/coordinator/src/coordinator/validators/runner.py
  - apps/ingest_worker/src/ingest_worker/triggers.py
  - apps/ingest_worker/src/ingest_worker/weather/parser.py
  - config/defaults.yaml
  - infra/migrations/versions/0006_phase3_planning.py
  - packages/wildfire_core/pyproject.toml
  - packages/wildfire_core/src/wildfire_core/config.py
  - packages/wildfire_core/src/wildfire_core/db/repositories.py
  - packages/wildfire_core/src/wildfire_core/geo/footprint.py
  - packages/wildfire_core/src/wildfire_core/geo/horizons.py
  - packages/wildfire_core/src/wildfire_core/schemas/phase2.py
  - packages/wildfire_core/src/wildfire_core/schemas/plan.py
  - packages/wildfire_core/src/wildfire_core/schemas/state.py
  - packages/wildfire_core/src/wildfire_core/schemas/tools.py
  - packages/wildfire_core/src/wildfire_core/seed.py
  - pyproject.toml
  - scripts/build_osm_graph.py
  - scripts/check_real_data.py
  - scripts/replay_demo.py
  - scripts/seed_settlements.py
  - scripts/seed_shelters.py
findings:
  critical: 1
  warning: 12
  info: 5
  total: 18
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-10-20
**Depth:** standard
**Files Reviewed:** 55
**Status:** issues_found

## Summary

Reviewed the Phase 3 production, script and config files (tests, fixtures, docs and seed CSVs excluded). The offline suite is green (486 passed, 1 skipped), so every finding below is a gap the tests do not exercise.

The planning core is carefully built: min-cost-flow matching, bounded resolver, V1-V7 validators, atomic capacity re-check and immutable versioning are consistent with D-01..D-21. One defect breaks a locked decision outright. Any plan that carries a D-20 "needs rescue" alert or a D-21 "P90-only" alert is converted into a `failed` plan by the V8 grounding gate. I reproduced this with the repo's own test factories. The remaining findings are robustness, data-integrity and behavioural gaps around re-planning, plan supersession and the incidents API.

No structural (fallow) findings were provided, so there is no structural section. The three known pre-existing items (16 mypy errors in `test_phase2_schemas.py`, `agent_routing` import not on `mypy_path` for scripts, and the `anthropic/openai/gpt-oss-20b` label in the replay demo) were not re-reported.

## Critical Issues

### CR-01: A rescue or P90-only alert makes the deterministic rationale fail V8, so the whole plan becomes `failed`

**File:** `apps/coordinator/src/coordinator/planning/finalize.py:267-271` (trigger), `apps/coordinator/src/coordinator/planning/grounding.py:141-157` (cause), `apps/agents/fire/src/agent_fire/risk.py:103-134` (message source)
**Issue:** `assess_risk` writes alert messages that embed the settlement name, for example "`{settlement.name}` is inside the active fire perimeter ..." and "`{settlement.name}` is reached only by the P90 forecast ...". These settlements deliberately have no evacuee group (D-20, D-21). `template_rationale` prints every alert message (`_alert_lines`).

`grounding_facts` only collects `plan_names` from keys in `NAME_KEYS` (`settlement_name`, `shelter_name`, `name`). Alert entries carry only `message` and `settlement_id`, so the rescued settlement's name is not a plan name. The caller passes all settlement names as `registry_names`, so `check_grounding` reports `unknown name: <settlement>`. `finalize_plan` then takes the "cannot happen by construction" branch and returns `failed(("V8 deterministic rationale failed grounding",))`.

Net effect: D-20 ("the plan is still produced for all other groups") and the D-21 P90-only warning are both broken. As soon as a real settlement sits inside the current perimeter, the incident gets a failed plan with an unrelated reason and no approvable content. The hypothesis tests miss it because `test_template_rationale_is_always_grounded` uses the alert text `"Needs 2 rescue teams"`, which contains no registry name.

Reproduced with `apps/coordinator/tests/plan_factory.py`:
```python
alerts = (PlanAlert(kind="needs_rescue_response",
          message="Beta Village is inside the active fire perimeter: needs rescue response (exempt from evacuation matching)",
          settlement_id="b"),)
plan = finalize_plan(valid_draft(alerts=alerts), rationale=RationaleResult("x", True, {}),
                     registry_names=["Mudumalai", "Kargudi", "Beta Village", "Gudalur School"], ...)
# plan.status == "failed", plan.failure_reasons == ("V8 deterministic rationale failed grounding",)
```
**Fix:** Make alert-referenced names plan facts. The cleanest option is a `settlement_name` field on `PlanAlert`, which `NAME_KEYS` already covers:
```python
# plan.py
class PlanAlert(_Frozen):
    ...
    settlement_id: str | None = None
    settlement_name: str | None = None   # picked up by grounding NAME_KEYS
# risk.py: PlanAlert(..., settlement_id=settlement.settlement_id, settlement_name=settlement.name)
```
Also add a regression test using a registry-only settlement name in a rescue alert and a P90-only alert, and run it through `finalize_plan`, not just `check_grounding`.

## Warnings

### WR-01: A failed re-plan supersedes the last valid `pending_review` plan

**File:** `apps/coordinator/src/coordinator/repository.py:328-334` (SQL), `:889-893` (in-memory)
**Issue:** `_SUPERSEDE_SQL` supersedes every earlier plan in `('draft','pending_review','failed')` when any new version is written, including a new `failed` version. A transient preflight failure on a re-plan (weather outage, a specialist timeout, an unsnappable group, a state-version bounce) therefore replaces the reviewer's last approvable plan with a plan that has no approvable content. `get_incident_plan` and `latest_plan` then return only the failed one. For a safety tool, a degraded refresh should not delete the last good plan from the review queue.
**Fix:** Only supersede earlier non-terminal plans when the new plan is `pending_review`. Keep the earlier `pending_review` plan current when the new one is `failed`, and surface the failed version separately (or flag it on the incident). Mirror the change in `InMemoryPlanningRepository.persist_plan`.

### WR-02: `list_incidents` hotspot_count and trigger_type are wrong after any re-plan

**File:** `apps/api_gateway/src/api_gateway/routers/incidents.py:131-144`
**Issue:** `trigger_type` and `hotspot_count` come from the single latest trigger of the incident. Phase 3 now inserts `perimeter_change`, `road_blocked` and `shelter_capacity_change` triggers whose `details` have no `hotspot_ids`. After the first re-plan, `jsonb_array_length(NULL)` yields NULL, which `COALESCE` turns into 0. The list therefore reports 0 hotspots and a re-plan trigger type for an incident that has hotspots.
**Fix:** Restrict the hotspot subqueries to `t.type = 'new_hotspot'`, or sum `jsonb_array_length` over all non-coalesced `new_hotspot` triggers. Keep `trigger_type` as the latest trigger if that is the intent.

### WR-03: `update_occupancy` cannot release occupancy for an inactive or over-allocated shelter

**File:** `apps/agents/shelter/src/agent_shelter/registry.py:141-149`
**Issue:** The single UPDATE requires `AND is_active` and `new_occupancy BETWEEN 0 AND floor(capacity * factor)` for every delta, negative deltas included. If a shelter goes inactive (damaged, closed) while evacuees are recorded in it, their departure (`delta < 0`) raises `CapacityExceeded`, so occupancy can never be decremented. The same happens when a lowered `usable_factor` leaves occupancy above the new usable cap: a release that still ends above the cap is refused. The error type, "capacity exceeded", is also misleading for a release.
**Fix:** Apply the capacity bound only to increases and drop `is_active` for decreases, for example:
```sql
AND occupancy + :delta >= 0
AND (:delta <= 0 OR (is_active AND occupancy + :delta <= floor(capacity * COALESCE(usable_factor, :default_factor))))
```
Keep the history insert in the same transaction.

### WR-04: V8 "strict" grounding auto-passes the integers 1-8, 60, 180, 360

**File:** `apps/coordinator/src/coordinator/planning/grounding.py:67-68`
**Issue:** `_FIXED_FACTS` includes `1,2,3,4,5,6,7,8,60,180,360`. The comment justifies horizons and validator ordinals, but an LLM sentence such as "4 shelters are available" or "5 routes were blocked" passes V8 even when false. The small integers are exactly the counts a rationale is likely to state, so the D-13 guarantee ("every number must appear in plan data") is much weaker than documented.
**Fix:** Ground only numbers that follow a recognised unit or label ("1 h", "3h", "60 min", "V1".."V8"), or drop the small integers and rely on the derived counts already added in `_derived_numbers`. Add a negative test ("7 shelters" with 2 assigned shelters must fail).

### WR-05: Re-plan trigger evidence is never fed into the re-plan

**File:** `apps/coordinator/src/coordinator/replan.py:86-121, 124-166`
**Issue:** `detect_replan_triggers` compares `observation.new_perimeter_wkt`, `edge_statuses` and `shelter_states` with the latest plan. `replan_incident` then runs the full coordinator, which re-derives everything from stored hotspots, `repository.edge_statuses()` and `repository.shelters()`. It ignores the observation entirely. Consequences:
- A `perimeter_change` observation can never change the plan. Fire is re-simulated from the same hotspots and weather, so the footprint is identical and the outcome is `no_change`. There is no producer that persists a new perimeter.
- `road_blocked` and `shelter_capacity_change` only work if the caller wrote the new state to the DB first. The docstring does not say so.
The trigger is therefore detected and recorded, but the re-plan can be a silent no-op.
**Fix:** Document the persistence precondition, or make `check_and_replan` persist the observation (edge statuses, shelter states) before calling `replan_incident`. For perimeter changes, inject the observed perimeter into the run or add a stored-evidence source that `run_fire_ca` consults.

### WR-06: Coalesced `new_hotspot` triggers leave their incident with no hotspots

**File:** `apps/ingest_worker/src/ingest_worker/triggers.py:222-247`, `apps/coordinator/src/coordinator/repository.py:272-283`
**Issue:** `record_new_hotspot_trigger` looks up `previous` across all incidents, then always creates a new incident and inserts a trigger with `coalesced_into=previous`. `_INCIDENT_HOTSPOTS_SQL` selects hotspots only from triggers with `coalesced_into IS NULL`. The new incident's only trigger is coalesced, so `incident_hotspots` returns no rows. `ingest_trigger` then sets `error="No hotspot observations are linked..."`, and the incident can never get a plan. Hotspot ids ingested during a debounce window are lost for planning.
**Fix:** Either do not create an incident when the trigger coalesces (append the hotspot ids to the leader's incident), or have the hotspot query include coalesced triggers whose `incident_id` matches. Scope the `previous` lookup by incident or area as well.

### WR-07: Highest-urgency groups may be structurally unplaceable under the nearest-horizon rule

**File:** `apps/agents/routing/src/agent_routing/router.py:293-337`, `apps/coordinator/src/coordinator/validators/route_checks.py:143-166`, `packages/wildfire_core/src/wildfire_core/geo/horizons.py:19-23`
**Issue:** Groups exist precisely because the settlement buffer touches the P50 footprint, and origin snapping only excludes the current perimeter. Edges are evaluated at end-of-edge arrival time, and any arrival under 120 min maps to the +1 h footprint. For a settlement inside or beside `p50_1h`, the first edge from its snapped node (arrival in a few minutes) is tested against the P50 1 h polygon. Both `evaluate_path.safe` and V3 fail every path. The resolver cannot repair it, the fallback requires strictly safe paths, and D-12 fails the whole plan. The most urgent groups (priority 1, 2) are the ones the planner is least able to place, and a `failed` plan is produced exactly when evacuation is needed. This follows from locked D-07 and D-21, so confirm it with the pilot data before accepting it.
**Fix:** Consider a departure-time grace such as a "0 h" (current perimeter) horizon for arrival under about 30 min, or exempt the first N metres or edges from the origin buffer. At minimum, record the behaviour in the plan failure reason ("origin edge inside P50 1 h") so a reviewer can tell it from a genuine routing failure.

### WR-08: Non-material re-plans can never refresh `valid_until` or freshness, and `valid_until` is not enforced

**File:** `apps/coordinator/src/coordinator/graph.py:798-820`, `apps/api_gateway/src/api_gateway/routers/incidents.py:175-220`
**Issue:** Per D-16 a no-change re-plan writes no version, and plans are immutable. So an unchanged but re-verified plan keeps its original `valid_until` (60 min by default) and freshness block. Nothing in the API or repository compares `valid_until` with the clock, so an expired plan is served as current with no staleness signal.
**Fix:** Expose `valid_until` in `PlanResponse` and flag expiry (`is_expired`) at read time. Optionally record the latest `replan_no_change` timestamp in the audit/incident row so the reviewer can see the plan was re-confirmed.

### WR-09: `agent_runs` records a failed run as `succeeded`

**File:** `apps/coordinator/src/coordinator/audit.py:43`, `apps/coordinator/src/coordinator/runner.py:40-55`
**Issue:** `flush_audit_entries` hard-codes `status = 'succeeded'` for every row. `_flush_failed_run` writes a `run_failed` row through the same path, so a crashed run is stored with status `succeeded`. Anything filtering `agent_runs` by status (dashboards, the Phase 4 review UI) will not see failures.
**Fix:** Derive status from the entry, for example `'failed'` when `node_name == 'run_failed'`, or add a `status` field to `AuditEntry` and bind it.

### WR-10: `check_and_replan` crashes on a Phase 2 predecessor plan

**File:** `apps/coordinator/src/coordinator/replan.py:173-176`
**Issue:** `latest_plan` also returns Phase 2 `draft` rows, and `diff.py` deliberately supports a Phase 2 predecessor (D-16). `check_and_replan` does `IntegratedPlan.model_validate(stored.plan_data)` unconditionally, so a schema "2.0" plan raises `ValidationError` instead of re-planning.
**Fix:** If `plan_data.get("plan_schema_version") != "3.0"`, skip trigger comparison and run the re-plan (or return an empty list explicitly), consistent with `is_material_change`.

### WR-11: Zero lane capacity in config causes `ZeroDivisionError`; config is not validated at load

**File:** `apps/agents/routing/src/agent_routing/congestion.py:139-143`, `packages/wildfire_core/src/wildfire_core/config.py:79-137`
**Issue:** `lane_capacity_vph` values and `link_capacity_factor` are not checked for positivity in `Settings`. `apply_congestion` computes `flow / capacity` before `bpr_time`'s own `capacity_vph <= 0` guard, so a zero entry raises `ZeroDivisionError` mid-plan. Other coefficients (`bpr_alpha`, `k_paths_max_leg_s`, `max_snap_distance_m`) are only validated later in `PlanningParams.from_settings`, so a bad config surfaces during `plan_evacuation` instead of at startup.
**Fix:** Validate `all(v > 0 for v in lane_capacity_vph.values())` and the other coefficient bounds in `validate_phase3_coefficients`, and guard `capacity <= 0` in `apply_congestion`.

### WR-12: Failed plans with different causes are treated as "no material change"

**File:** `apps/coordinator/src/coordinator/planning/diff.py:58-86`
**Issue:** The signature holds assignments, routes, validator statuses and plan status. Two consecutive `failed` plans with no routes or assignments and the same validator statuses compare equal even when the failure reasons (for example a different unplaceable group, or weather missing versus a specialist timeout) differ. The re-plan is recorded as `replan_no_change`, so the reviewer keeps seeing the stale failure reason. This is weaker than D-16's "validator status differ" intent for a failed plan.
**Fix:** Include `failure_reasons` (sorted) in `material_signature` when `status == "failed"`.

## Info

### IN-01: Legacy Phase 2 routing and rationale code is now unused

**File:** `apps/agents/routing/src/agent_routing/router.py:80` (`compute_route`), `costs.py:40` (`apply_fire_penalties`), `graph.py:79` (`load_or_download_graph`), `packages/wildfire_core/src/wildfire_core/config.py:62` (`route_fire_penalty_near`), `apps/coordinator/src/coordinator/llm/groq_adapter.py:80` (`generate_rationale`, `_route_summary`)
**Issue:** No non-test caller remains; `load_or_download_graph` is a deprecated shim that "ignores bbox", and the config key is documented as superseded.
**Fix:** Remove them (and the config key) once the 03-10 rewire is confirmed complete, or mark them `# pragma: no cover` deprecated with a removal date.

### IN-02: `route_cost_matrix` calls congested time "free flow"

**File:** `apps/agents/routing/src/agent_routing/router.py:229-246`
**Issue:** The variable and `LegCost.free_flow_s` hold times computed over `time_attr="congested_time"`, not free-flow `travel_time`. On later congestion passes this is the congested leg time. The horizon pick is correct, but the name misleads readers and any consumer of `LegCost.free_flow_s`.
**Fix:** Rename to `leg_time_s`, or compute real free flow from `travel_time`.

### IN-03: Seed `usable_factor` can silently round up in the database

**File:** `packages/wildfire_core/src/wildfire_core/seed.py:42`, `infra/migrations/versions/0006_phase3_planning.py:37`
**Issue:** `ShelterSeedRow.usable_factor` accepts any float in (0, 1], but the column is `numeric(3,2)`. A CSV value of `0.555` is stored as `0.56`, which is less conservative than the operator intended and affects capacity.
**Fix:** Reject more than two decimals in the validator, for example `round(v, 2) == v`.

### IN-04: Stored row `created_at` differs from the plan's `created_at`

**File:** `apps/coordinator/src/coordinator/repository.py:315-326, 531`
**Issue:** `_INSERT_PLAN_SQL` omits `created_at`, so the row uses the DB default `now()` while `plan_data.created_at` comes from the injected clock. Under a `SimClock` replay the two disagree. The API returns the row value and the plan blob carries the other.
**Fix:** Insert `created_at` explicitly from `final.created_at`.

### IN-05: Immutability trigger blocks UPDATE but not DELETE or TRUNCATE; any status can be set

**File:** `infra/migrations/versions/0006_phase3_planning.py:128-134`
**Issue:** The trigger is `BEFORE UPDATE` only, so `plan_versions` rows can still be deleted. `status` is excluded from the comparison, so a `failed` row can be updated to `pending_review` at the DB level, which bypasses the D-11 "no approvable content" guarantee. Phase 4 should close both.
**Fix:** Add a `BEFORE DELETE` trigger, and restrict status transitions to `X -> superseded` (and the Phase 4 approval states) inside `plan_versions_immutable()`.

---

_Reviewed: 2026-10-20_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

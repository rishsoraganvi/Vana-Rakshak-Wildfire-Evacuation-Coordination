# Phase 3: Capacity-Aware Coordinated Planning - Context

**Gathered:** 2026-10-17
**Status:** Ready for planning

<domain>
## Phase Boundary

The Coordinator assembles a **validated, immutable, versioned integrated evacuation plan** that assigns
evacuee groups (from at-risk settlements) to shelters along fire-safe routes without exceeding
conservative shelter capacity. Delivers: shelter registry + min-cost-flow matching, routing with
dynamic costs / k=3 paths / congestion passes, shared-state versioning, parallel specialist dispatch,
bounded conflict resolution with a deterministic fallback planner, plan assembly with version diffs,
validators V1–V8, and re-plan trigger detection + debounce.

Requirements: PLAN-03, PLAN-04, PLAN-07, PLAN-08 (and the parallel-dispatch half of PLAN-01).

Exit criteria (ROADMAP): property tests prove capacity and double-booking invariants; invalid plans are
blocked; a material route/shelter change creates a new version; provenance and freshness are present on
every plan.

Out of this phase: review/approval/dissemination (Phase 4), dashboard and background workers (Phase 5),
vehicles/drones/calibration (Phase 6).

</domain>

<decisions>
## Implementation Decisions

Already fixed by `generatedPlan/TechSpec.md` (not re-decided here): k=3 shortest paths per group;
min-cost-flow matching (source→groups→shelters→sink); `usable = floor(capacity × usable_factor)`;
shelters inside/near the forecast perimeter excluded; validators V1–V8 gate `pending_review`; ≤ 3
conflict-resolution loops then deterministic fallback planner; LLM may only pick from a fixed strategy
menu via structured output and never computes numbers or invents IDs; trigger thresholds per TechSpec §9;
identical triggers within 5 minutes coalesced. V6 (vehicles) has no producer until Phase 6 and must pass
trivially on an empty `dispatches` list.

### Shelter & population data
- **D-01:** Shelters come from a **curated seed set**: ~15–30 real schools / community halls around the
  pilot cluster, hand-checked, committed as a CSV and loaded by a seed script into a new `shelters`
  table (Alembic migration). Deterministic for tests and CI. — **Reversibility:** costly — adds a table
  and migration that later importers must populate compatibly.
- **D-02:** Evacuee groups: **one group per at-risk settlement**, `persons = settlements.population`
  (existing table), seeded for the pilot cluster.
- **D-03:** Capacity: each shelter row carries a seeded `capacity`; `usable = floor(capacity × 0.6)` with
  `usable_factor` in config; occupancy starts at 0 and changes only via `update_occupancy`.
- **D-04:** pgvector natural-language shelter lookup is **deferred**; shelter tools are
  `list_candidate_shelters`, `match_groups_to_shelters`, `update_occupancy`.

### Road graph for routing
- **D-05:** Routing runs on the **real OSM drive network**, downloaded once with OSMnx and cached to
  `data/osm/` (git-ignored, not committed); loaded from disk thereafter (Phase 2 D-01 intent). CI does
  not download OSM.
- **D-06:** Cached graph covers the **pilot cluster + ~10 km buffer** around the seeded settlements and
  shelters (not the whole AOI bbox).
- **D-07:** Fire penalties are **ETA-aware**: for each group's path, use the forecast horizon nearest the
  arrival time (1 / 3 / 6 h); inside P50 = high penalty, inside P90 = medium, inside current perimeter =
  blocked (∞). Aligns routing with validator V3 ("before ETA"). Closes Phase 2 review MD-02.
- **D-08:** Congestion: spec BPR-style speed reduction from assigned flow (persons → vehicle-equivalents
  via a config ratio), **2–3 re-routing passes**.

### Conflict resolution & LLM
- **D-09:** Fixed fix menu has exactly three strategies: **re-route with next path** (next of k=3 or
  recompute excluding failing edges), **re-match to another shelter**, **split a group** across two
  shelters. "Mark unassigned" is **not** an automatic strategy.
- **D-10:** **Deterministic resolver first**: applies the menu in a fixed order by default. When the LLM
  is enabled, it may choose the menu item via structured output; its choice is validated identically. The
  3-loop cap and fallback planner apply in both modes.
- **D-11:** If validators still fail after 3 loops and the fallback planner, persist a **plan version with
  status `failed`** carrying the validator results and reasons and no approvable content (spec §12, Rule S5).
  — **Reversibility:** costly — introduces a plan status value consumed by Phase 4 review APIs.
- **D-12:** An **unplaceable group fails the whole plan** (V5 fails → `failed` plan record naming the group
  and reason). No partial plans reach review.
- **D-13:** V8 is **strict**: every number and entity ID in LLM rationale must appear in plan data (within
  rounding). On failure, replace with the deterministic template rationale and record the reason; V8 alone
  does not block the plan.

### Re-plan triggers
- **D-14:** Triggers that re-plan in Phase 3: **perimeter_change**, **road_blocked**,
  **shelter_capacity_change** (thresholds per TechSpec §9). `wind_shift`, `scheduled_refresh` and `manual`
  are out of Phase 3.
- **D-15:** Trigger detection + 5-minute debounce are **library functions plus an on-demand entry point**
  that runs a re-plan; tests and replay invoke it directly. No long-running background worker in Phase 3.
- **D-16:** A re-plan creates a **new immutable plan version** (parent link + diff) **only on material
  change** — routes, shelter assignments, or validator status differ. Otherwise record that the re-plan
  ran, with no new version.
- **D-17:** Fold Phase 2 review warnings into Phase 3: **WR-01** (per-cluster weather lookup instead of one
  reading at the mean hotspot) and **WR-03** (fix the weather ingest so live observations match the scoped
  weather query — currently stored as forecasts with origin `replay`, so real incidents never get a plan).

### Post-research decisions (2026-10-17, after 03-RESEARCH.md)
- **D-18:** Seed data: ship a **clearly labelled synthetic seed** for shelters and settlements (every row
  carries `capacity_source='synthetic'` / equivalent provenance, S9) so build and CI are not blocked. Plan a
  `checkpoint:human-action` task for the user to replace it later with curated real CSVs
  (`config/seed/shelters_bandipur.csv`, `config/seed/settlements_bandipur.csv`). Refines D-01.
- **D-19:** Pilot cluster centre is **11.72 N, 76.64 E** (Bandipur); OSM graph and seeds use a ~10 km buffer
  around it. The OSM build is an explicit script the user runs once (`checkpoint:human-action`); the graph
  loader must be load-only and never silently download the whole AOI.
- **D-20:** A settlement **already inside the current fire perimeter** is **exempt from evacuation matching**:
  it is flagged "inside active fire — needs rescue response" as a reviewer-visible alert, and the plan is still
  produced for all other groups. D-12 (unplaceable group fails the whole plan) applies to every other group.
- **D-21:** Accept the researcher's safety defaults as **config-driven values**: P50 penalty ×10, P90 ×3;
  shelters within 1 km of P90-6h ∪ current perimeter are excluded; only settlements intersecting the P50
  forecast form evacuee groups (P90-only intersections produce a warning); a cluster with no matching weather
  fails closed; plans that pass V1–V8 are stored as `pending_review` (approval itself remains Phase 4).
  V3 and routing share the same "forecast horizon nearest per-edge arrival time" rule.
- Note: the trigger enum is named `trigger_type` (not `incident_trigger_type`); all three Phase 3 trigger values
  already exist in it.

### Claude's Discretion
- How CI exercises k-paths, congestion and capacity without downloading OSM (e.g. a small subgraph
  extracted from the cached real graph and committed as a fixture, or a richer synthetic fixture).
- Exact BPR coefficients, vehicle-equivalent ratio, P50/P90 penalty magnitudes, and the deterministic
  ordering of the fix menu.
- Shared-state versioning mechanics (Redis keys vs Postgres rows) within the TechSpec §5 shape.
- How parallel specialist dispatch is implemented in-process (e.g. `asyncio.gather`) behind the same tool
  interface used in Phase 2.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Product specification (source of truth)
- `generatedPlan/TechSpec.md` §4–§6 — services, shared-state shape, Coordinator orchestration rules (parallel dispatch, ≤3 conflict loops, LLM boundaries)
- `generatedPlan/TechSpec.md` §7.3–§7.4 — Routing agent (edge cost, k-paths, BPR congestion, dynamic replan) and Shelter agent (registry, usable capacity, min-cost flow, tools, invariant)
- `generatedPlan/TechSpec.md` §8 — Integrated plan shape and validators V1–V8
- `generatedPlan/TechSpec.md` §9 — Trigger definitions, thresholds, debounce
- `generatedPlan/TechSpec.md` §12 — Degraded modes (validator failure → failed plan shown to reviewer)
- `generatedPlan/Rules.md` — Safety rules S1–S9 (S5: V1–V8 before `pending_review`), property tests (Hypothesis) for validators/capacity
- `generatedPlan/PRD.md` — Plan validity success metric, LLM hallucination risk
- `generatedPlan/Schema.md` — Database schema intent for shelters, plans, versions

### Project planning
- `.planning/REQUIREMENTS.md` — PLAN-01, PLAN-03, PLAN-04, PLAN-07, PLAN-08
- `.planning/ROADMAP.md` — Phase 3 goal, deliverables, exit criteria
- `.planning/phases/02-mvp-detection-to-route/02-CONTEXT.md` — Phase 2 decisions carried forward (D-01 OSM cache, D-09 bounded LLM, D-12 audit)
- `.planning/phases/02-mvp-detection-to-route/02-REVIEW-GAPS.md` — WR-01, WR-03 (folded), other warnings
- `.planning/phases/02-mvp-detection-to-route/02-SECURITY.md` — accepted risks and residual risks
- `docs/adr/ADR-001-phase1-aoi-and-migration-boundary.md` — AOI and migration boundary

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `apps/agents/routing/src/agent_routing/` (`costs.py`, `router.py`): full-edge fire exposure, two-phase Dijkstra with finite blocked fallback, `nearest_node_outside` — base for k-paths and ETA-aware penalties.
- `apps/agents/fire/src/agent_fire/` (`ca_model.py`, `ensemble.py`): per-cluster CA producing P50/P90 at 1/3/6 h — feeds ETA-aware penalties and shelter exclusion.
- `apps/agents/weather/src/agent_weather/agent.py`: scoped `get_weather_snapshot` (location/provider/origin/time) — extend per cluster (WR-01).
- `apps/coordinator/src/coordinator/graph.py`, `runner.py`, `audit.py`: LangGraph Coordinator, `fire_results` per cluster, `_audit` with `model_metadata`.
- `apps/coordinator/src/coordinator/llm/groq_adapter.py`: gated Groq calls with `RationaleResult` metadata — reuse for structured fix-menu choice.
- `apps/ingest_worker/src/ingest_worker/triggers.py`: trigger recording + debounce — extend for the three Phase 3 triggers.
- `packages/wildfire_core/src/wildfire_core/schemas/phase2.py`: `CoordinatorPlan`, `FireSpreadResult`, `RouteResult` — extend into the integrated plan shape.
- `packages/wildfire_core/src/wildfire_core/db/repositories.py`: `save_shared_state` and upserts.

### Established Patterns
- Agents run in-process behind a stable tool interface (TechSpec §4 note); Pydantic v2 at every boundary.
- Deterministic numbers, LLM rationale only; LLM off by default; compact metric payloads (Groq 8k TPM).
- Every Coordinator node writes an audit row; plans persisted in `plan_versions.plan_data`.
- Tests: offline by default, live behind `COMPOSE_SMOKE=1`; tests clean up their own rows.

### Integration Points
- New `shelters` table + seed CSV/script; `settlements` population for groups.
- `plan_versions` gains parent link, diff, and a `failed` status path.
- `trigger_type` enum already includes `perimeter_change`, `road_blocked`, `shelter_capacity_change`.
- Weather ingest (`ingest_worker`) must write observations the scoped query matches (WR-03).

</code_context>

<specifics>
## Specific Ideas

- Strict "no partial plans" stance: if any group cannot be placed after the three fixes, the reviewer sees a failed plan explaining which group and why, not a plan with gaps.
- The real Bandipur road network should drive demos; the 3-node fixture is for unit tests only.

</specifics>

<deferred>
## Deferred Ideas

- pgvector natural-language shelter lookup ("school with ground near X") — later phase.
- data.gov.in school-directory importer with geocoding and capacity estimation — later phase (Phase 3 uses a curated seed).
- `wind_shift`, `scheduled_refresh` and `manual` re-plan triggers — `manual` with Phase 4 review ("changes requested"), others with Phase 5 workers.
- Background polling worker for automatic re-planning — Phase 5.
- Remaining Phase 2 review warnings (WR-02, WR-04..WR-10) — separate cleanup, not Phase 3 scope.
- "Mark unassigned with reason" as a fix strategy — explicitly rejected for Phase 3 (D-12).

</deferred>

---

*Phase: 03-capacity-aware-coordinated-planning*
*Context gathered: 2026-10-17*

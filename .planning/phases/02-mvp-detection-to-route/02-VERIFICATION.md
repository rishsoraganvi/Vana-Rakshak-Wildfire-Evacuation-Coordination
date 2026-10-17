---
phase: 02-mvp-detection-to-route
verified: 2026-10-17T06:05:00Z
status: passed
score: 14/14 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 7/8
  gaps_closed:

    - "PLAT-02: agent_runs.model_metadata never populated (closed by 02-06; live DB now holds non-null metadata on every generate_rationale row created after the fix)"
    - "Live Groq success path never observed (closed by 02-06 MD-11: live rows show llm_called=true, is_fallback=false, finish_reason=stop, response_model=openai/gpt-oss-20b)"
    - "CR-01 wind convention (02-04), CR-02/HI-01 routing exposure and ranking (02-05), CR-03 per-cluster fire (02-07), HI-03/HI-04 weather (02-09), HI-05 LLM gating (02-06), HI-06 loopback + required password (02-08), MD-11 configured model (02-06)"
  gaps_remaining: []
  regressions: []
deferred:

  - truth: "PLAN-01 clause: 'dispatches eligible specialists in parallel through typed tool contracts'"
    addressed_in: "Phase 3"
    evidence: "Phase 3 deliverables in ROADMAP.md include 'parallel specialist dispatch'. Phase 2 graph is linear by design (Weather -> Fire only)."

  - truth: "JWT viewer-role protection on the read-only API"
    addressed_in: "Phase 4"
    evidence: "PLAT-01 is mapped to Phase 4; Phase 2 API is loopback-only (and now Postgres/Redis too, per HI-06)."

  - truth: "Review items MD-01..MD-10 and LO-01..LO-10 not in the gap-closure scope (P90 horizons / tiered penalties in routing, first-non-blocked route choice, per-horizon RNG re-seed, per-node audit status and try/finally audit flush, plan-version race, debounced-trigger incident, LLM grounding checks)"
    addressed_in: "Phase 3 (PLAN-03, PLAN-07, PLAN-08) and later; tracked in 02-REVIEW.md"
    evidence: "Phase 3 covers fire-forecast route penalties, deterministic planner/bounded retries and grounded rationale. These were deliberately excluded from the 02-04..02-09 gap-closure scope (CR-01..03, HI-01..06, MD-11 only)."
human_verification:

  - test: "Suitability of AOI-boundary exit policy and route output for Bandipur"
    expected: "A domain operator judges the selected boundary exit nodes and the resulting route as operationally sensible"
    why_human: "Domain judgment. The replay uses a synthetic 3-node, 4-edge fixture graph (tests/fixtures/osm/bandipur_stub.graphml); after the CR-02 fix its replay route is correctly classified 'blocked' (every route crosses the simulated fire), so the demo never shows a 'safe' route. Carried over from 02-VALIDATION.md manual-only list."

  - test: "Live, repeatable confirmation of Groq success path on the operator's own key"
    expected: "scripts/replay_demo.py prints 'LLM Fallback : No' with LLM Model groq/openai/gpt-oss-20b"
    why_human: "Already evidenced in the live DB (see Truth 12) and by the executor/orchestrator live runs, but it depends on an external provider, a served model id and a secret key; a final operator confirmation is cheap and not reproducible offline. Non-blocking."
---

# Phase 2: MVP Detection to Route Verification Report

**Phase Goal:** A hotspot or replay event produces a basic, auditable evacuation route suggestion for one pilot settlement cluster.
**Verified:** 2026-10-17
**Status:** human_needed (all automated truths verified; two human/domain items remain, no gaps)
**Re-verification:** Yes - after gap closure (plans 02-04 .. 02-09)

## Goal Achievement

The previous blocking gap (PLAT-02 model metadata never populated) is closed in code and in live data, and the previous human-needed item (real Groq never answered) is observed in the live DB. The three critical review findings (CR-01 upwind spread, CR-02 midpoint-only exposure, CR-03 only largest cluster simulated), the six high findings (HI-01..06) and MD-11 are fixed in source, covered by targeted tests, and the offline suite is green (104 passed, 8 skipped, re-run by this verifier). I read the code rather than the SUMMARYs.

### Observable Truths

| #  | Truth | Status | Evidence |
| -- | ----- | ------ | -------- |
| 1  | Replay/hotspot event yields a draft evacuation plan with a route for the pilot cluster | VERIFIED | `runner.py` 8-node graph; live DB latest `plan_versions` row (2026-10-17 05:47) status=draft, is_simulated=true, routes=[('blocked', 3-node path)], clusters + fire_results populated. Route is classified `blocked` on the 3-node synthetic fixture (honest, see Human item 1). |
| 2 | Output contains P50/P90 forecast data (1h/3h/6h) | VERIFIED | Live plan_data `fire_results[0]`: p50_1h and p90_6h WKT non-empty, spread_direction 226.48 for wind-from 45 deg (correct: spread toward SW), rate 592.62 m/h. Offline `test_offline_pipeline_with_real_ca_and_routing_on_fixture_graph` runs real CA + real routing with mocked DB/LLM and asserts non-empty P50/P90 WKT, 8 audit entries, origin moved off burning node 1000002, blocked classification (closes the earlier PLAT-06 gap). |
| 3  | Audit entries cover every Coordinator node/tool call | VERIFIED | Latest live run has exactly 8 `agent_runs` rows (ingest_trigger, run_weather, cluster_hotspots, run_fire_ca, compute_route, generate_rationale, assemble_plan, write_audit) with latency_ms; `test_pipeline_offline` and the live integration test assert 8. Caveat (warning, deferred MD-06): `status` is hard-coded `'succeeded'` and an exception in a node aborts before `write_audit`. |
| 4  | Fallback works with LLM disabled/failing | VERIFIED | Live rows (05:58, 05:46, 05:39, 05:21 UTC): `is_fallback=true, fallback_reason=llm_disabled, llm_called=false`, plans still persisted (`is_llm_fallback=true`). `generate_rationale` gates on llm_enabled/provider/model/key before building a client (no network, no sleep); unit tests `test_generate_rationale_skips_provider_when_disabled / requires_groq_provider / requires_model / requires_api_key`, plus error and empty-response fallbacks. |
| 5  | Core tests pass | VERIFIED | `.venv\Scripts\python.exe -m pytest -q` (offline, no COMPOSE_SMOKE): **104 passed, 8 skipped** (skips are COMPOSE_SMOKE/Groq-gated live tests, run by the orchestrator). |
| 6  | PLAN-01: Coordinator invokes Weather before Fire | VERIFIED | Edge order run_weather -> cluster_hotspots -> run_fire_ca in `runner.py`; `run_fire_ca` consumes `state["weather_snapshot"]` and skips with a warning when it is None. |
| 7  | Read-only API exposes incidents, plan, audit | VERIFIED | `routers/incidents.py`; `test_incidents_api.py` passing; API port published on 127.0.0.1:8000; `fire_result` (singular) no longer referenced anywhere in source, API or demo (grep clean). |
| 8  | PLAT-02: audit records carry model metadata (previous FAILED truth) | VERIFIED | `graph._audit(..., model_metadata=...)`; `generate_rationale_node` passes `result.model_metadata` (and an explicit `inputs_unavailable` record); `audit.flush_audit_entries` `json.dumps` the dict before `CAST(:model_metadata AS jsonb)`. Live DB latest run: generate_rationale row `model_metadata` = {provider groq, model openai/gpt-oss-20b, llm_enabled true, max_completion_tokens 400, timeout_s 30, llm_called true, is_fallback false, finish_reason stop, usage 811 tokens, response_model openai/gpt-oss-20b, reasoning_effort low}; all other nodes NULL. All 8 older rows with NULL metadata are pre-fix (timestamps <= 04:41 UTC). Offline test asserts the flushed generate_rationale row carries metadata and other rows are NULL. Append-only remains by convention (INSERT ... ON CONFLICT DO NOTHING; no DB trigger/REVOKE) - see Requirements. |
| 9  | CR-01 + HI-02 (02-04): wind FROM convention and real spread metrics | VERIFIED | `ca_model._wind_factor` uses `downwind = (from + 180) % 360`; `ensemble.compute_fire_spread` passes `wind_from_deg=weather.wind_dir_deg`; `_spread_metrics` measures front advance from the snapped ignition block over the real horizon, returns direction None below one cell. Verifier probe (read-only): wind from 270 -> spread dir 108.2 (east); from 0 -> 172.9 (south); calm -> direction None. `FireSpreadResult.spread_direction_deg: float | None`. 13 CA tests present and passing incl. westerly/northerly, snapping-invariance, actual-horizon, null-direction. |
| 10 | CR-02 + HI-01 (02-05): full-geometry exposure and rankable blocked routes | VERIFIED | `costs.apply_fire_penalties` tests the OSM `geometry` LineString or endpoint chord with `intersects` on prepared perimeters (endpoint-inside, crossing, boundary-touch, geometry tests present). `router.compute_route` runs Dijkstra with blocked edges hidden first and only then the least-blocked fallback (1e6 x travel_time); `FIRE_PENALTY_BLOCKED` still `inf`; `nearest_node_outside` exported and used. `test_bundled_fixture_route_through_active_fire_is_not_safe` passes. |
| 11 | CR-03 + HI-01 (02-07): every cluster simulated; routes start outside fire; least-exposure blocked choice | VERIFIED | `run_fire_ca` calls `compute_fire_spread` per cluster -> `state["fire_results"]`; `compute_route_node` penalises with `unary_union` of all current/P50 polygons, origin via `nearest_node_outside(union_current)` with a named warning when it moves, blocked candidates ranked by `_blocked_exposure_s`, then travel time, then node id. `CoordinatorPlan.fire_results` (min_length 1) persisted; live plan_data has `fire_results` and the origin-moved warning. Tests: multi-cluster union, origin-moves, least-exposure all present and passing. |
| 12 | HI-05 + MD-11 (02-06): LLM gated by config; configured model; live test fails on silent fallback | VERIFIED | `config/defaults.yaml`: `llm_provider: groq`, `llm_model: openai/gpt-oss-20b`, `llm_enabled: false` (default stays off; demo/test set LLM_ENABLED=true via env). No literal model id in `scripts/replay_demo.py` or `tests/integration/test_coordinator_pipeline.py` (no `llama3` anywhere). The live test asserts `state["is_llm_fallback"] is False` and persisted `is_fallback false` / `llm_called true`. Live DB shows 4 successful non-fallback Groq rows today (05:47, 05:21, 05:03, 05:02 UTC) with finish_reason stop. API coverage matrix recorded in `COVERAGE.md`. |
| 13 | HI-06 (02-08): loopback-only ports, required Postgres password | VERIFIED | `docker-compose.yml`: postgres/redis/api all `127.0.0.1:...`; `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set ...}` for postgres and the api DATABASE_URL; `defaults.yaml` database_url has no password; `Settings.postgres_password` default is empty SecretStr; CI sets an ephemeral `ci-ephemeral-password`. `docker compose port` (read-only) returns 127.0.0.1:5432 / 6379 / 8000. `tests/unit/test_compose_bindings.py` (3 tests) in the offline suite. |
| 14 | HI-03 + HI-04 (02-09): weather scoped by location/provider/origin/time; never fabricated | VERIFIED | `agent.build_snapshot_query` filters bbox of 50 km, `valid_time <= now`, provider, origin, non-NULL measurements, ordered by distance then recency; no `or 0.0` coercion; `LookupError` when none. `run_weather` queries at the hotspot centroid with the incident's own `origin` and `settings.weather_provider`; on failure sets `weather_snapshot=None`, builds nothing synthetic, downstream skips, `assemble_plan` does not persist a plan, and all 8 audit rows are still flushed. Tests present: query-filter, no-coercion, LookupError, origin/hotspot scoping, `test_weather_unavailable_skips_planning_without_fabrication`; live-gated `test_live_query_prefers_matching_origin_and_location` (reported passing by executor/orchestrator; not re-run here per constraint). |

**Score:** 14/14 truths verified (0 present-but-behavior-unverified).

### Previous gaps and human items - disposition

| Previous item | Disposition |
| ------------- | ----------- |
| GAP: PLAT-02 model_metadata never populated | CLOSED (Truth 8, live DB evidence) |
| HUMAN: real Groq never answered / `llama3-8b-8192` rejected | CLOSED (Truth 12; model moved to config, live non-fallback rows with response_model openai/gpt-oss-20b). Residual operator confirmation kept as a non-blocking item. |
| HUMAN: AOI-boundary exit suitability | STILL OPEN (domain judgment) |
| Secondary: integration test did not assert `is_llm_fallback is False` | CLOSED (MD-11) |
| Secondary: no offline test combining real CA + routing with mocked LLM | CLOSED (02-07 offline pipeline test) |
| Secondary: 02-VALIDATION.md still `nyquist_compliant: false`, live checks listed manual-only | STILL STALE (documentation; orchestrator to refresh) |
| Secondary: uncommitted session fixes (replay_demo sys.path, CAST status, migrations env, test scoping) | Working tree is clean apart from untracked `.gsd/`; fixes are committed. |

### Required Artifacts

| Artifact | Status | Details |
| -------- | ------ | ------- |
| `agent_fire/ca_model.py`, `ensemble.py`, `schemas/phase2.py` (02-04) | VERIFIED | FROM-direction kernel, `_spread_metrics`, nullable direction; wired from `compute_fire_spread` |
| `agent_routing/costs.py`, `router.py`, `__init__.py` (02-05) | VERIFIED | `intersects` exposure, `BLOCKED_FALLBACK_COST_FACTOR`, `nearest_node_outside` exported and used by coordinator |
| `coordinator/llm/groq_adapter.py`, `graph.py`, `audit.py`, `config/defaults.yaml`, `COVERAGE.md` (02-06) | VERIFIED | `RationaleResult`, `base_model_metadata`, gating, `json.dumps` metadata, config model |
| `coordinator/state.py`, `runner.py`, `graph.py`, `test_pipeline_offline.py` (02-07) | VERIFIED | `fire_results` list; `_blocked_exposure_s`; real-CA offline test |
| `docker-compose.yml`, `ci.yml`, `tests/unit/test_compose_bindings.py`, `config.py` (02-08) | VERIFIED | See Truth 13 |
| `agent_weather/agent.py`, `test_weather_agent.py`, `graph.py` (02-09) | VERIFIED | See Truth 14 |
| Phase 02-01..03 artifacts (schemas, clustering, OSM fixture, API, migration 0005, replay script) | VERIFIED (regression check) | Live DB at alembic head `0005_phase2_plan_versions`; API tests pass; replay produced plans |

### Key Link Verification

| From | To | Status | Details |
| ---- | -- | ------ | ------- |
| ensemble.compute_fire_spread | ca_model.run_ensemble (`wind_from_deg=weather.wind_dir_deg`) | WIRED | |
| graph.run_fire_ca | compute_fire_spread per cluster | WIRED | |
| graph.compute_route_node | apply_fire_penalties (union via `unary_union`), nearest_node_outside, compute_route | WIRED | |
| generate_rationale -> RationaleResult -> `_audit(model_metadata)` -> flush_audit_entries -> agent_runs.model_metadata | WIRED | Proven end to end in live DB |
| config.defaults.yaml -> `settings.llm_*` -> groq gating | WIRED | env overrides LLM_ENABLED/PROVIDER/MODEL mapped; blank env treated as unset |
| run_weather -> get_weather_snapshot(lat, lon, origin, provider) | WIRED | |
| run_weather None -> run_fire_ca / compute_route / generate_rationale / assemble_plan guards | WIRED | No plan persisted; 8 audit rows flushed |
| compose postgres POSTGRES_PASSWORD <-> api DATABASE_URL | WIRED | Same required interpolation |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
| -------- | ---- | ------ | --------- | ------ |
| plan_data.fire_results | perimeters, direction, rate | CA ensemble on seeded hotspots + scoped weather row | Yes (live DB) | FLOWING |
| plan_data.routes | osm_node_path, classification | Dijkstra on fixture graph with union penalties | Yes (live DB; 'blocked' on 3-node fixture) | FLOWING |
| agent_runs.model_metadata | provider/model/usage/finish_reason | Groq response + settings | Yes (live DB) | FLOWING |
| plan_data.rationale_md | rationale | Groq (non-fallback in live runs 05:47 etc.) or deterministic fallback | Yes | FLOWING |
| plan_data.weather_snapshot | wind/RH/temp | scoped `weather_observations` row (never zero-filled) | Yes | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Offline suite | `.venv\Scripts\python.exe -m pytest -q` | 104 passed, 8 skipped | PASS |
| CA wind convention | `run_ensemble(..., wind_from_deg=270 / 0 / calm)` | 108.2 deg / 172.9 deg / None | PASS |
| Live plan + audit (read-only SQL) | latest `plan_versions`, `agent_runs` | draft, fire_results, route, 8 rows, non-null generate_rationale metadata, is_fallback false | PASS |
| Live fallback evidence | `model_metadata->>'fallback_reason'` | `llm_disabled`, llm_called false, plan persisted | PASS |
| Loopback binding | `docker compose port postgres/redis/api` | 127.0.0.1:5432 / 6379 / 8000 | PASS |
| Alembic head | `select version_num from alembic_version` | `0005_phase2_plan_versions` | PASS |
| Live suite | not run by verifier (orchestrator running it) | n/a | SKIPPED |

### Probe Execution

No `probe-*.sh` declared or present. SKIPPED.

### Requirements Coverage

Requirement IDs declared across PLAN frontmatter: 02-01 FIRE-01, FIRE-02, PLAN-01 (partial); 02-02 PLAN-01, PLAN-02; 02-03 PLAT-02, PLAT-06, PLAN-02; 02-04/05 PLAN-02, PLAT-06; 02-06 PLAT-02, PLAT-06, PLAN-02; 02-07 PLAN-01, PLAN-02, PLAT-06; 02-08 PLAT-02, PLAT-06; 02-09 PLAN-01, PLAN-02, PLAT-06. ROADMAP Phase 2 IDs: PLAN-01, PLAN-02, PLAT-02, PLAT-06. All present in REQUIREMENTS.md; no orphaned Phase 2 IDs.

| Requirement | Status (Phase 2 scope) | Evidence |
| ----------- | ---------------------- | -------- |
| PLAN-01 | SATISFIED for Phase 2 portion; parallel dispatch DEFERRED to Phase 3 | Weather -> Fire ordering and typed contracts verified |
| PLAN-02 | SATISFIED | Live draft plan with route, fire, weather, graph |
| PLAT-02 | SATISFIED for runs/tool-call inputs/outputs/latency/model metadata; append-only is convention not enforcement; user actions n/a until Phase 4 | Truths 3, 8 |
| PLAT-06 | SATISFIED for Phase 2 scope (unit, offline real-CA pipeline, live integration, smoke, compose-binding tests); requirement is cross-phase (Phase 5 also maps it) | 104 offline passing |
| FIRE-01, FIRE-02 | Declared by 02-01; REQUIREMENTS traceability maps them to Phase 1 (document inconsistency, low impact). Phase 2 delivers P50/P90, direction, rate; `settlements_at_risk` still empty (no settlement data) |

### REQUIREMENTS.md state vs reality (orchestrator to edit; not modified here)

Current file state: checkboxes `[x]` on PLAN-02, PLAT-02, PLAT-06; `[ ]` on PLAN-01, FIRE-01, FIRE-02; traceability table rows (lines 86-91) are all still "Pending", including `PLAN-01..02, PLAT-02, PLAT-06 | 2 | Pending`.

1. **PLAN-02 `[x]` - matches reality.** Keep.
2. **PLAT-06 `[x]` - premature.** The `requirements.mark-complete PLAN-02 PLAT-06` call in 02-04 checked it, but PLAT-06 covers "fire, routing, matching, validators, contracts, review flow, and replay behavior" and the traceability table also maps PLAT-06 to Phase 5. Phase 2 satisfies its own slice only. Recommend un-checking (or marking it "Phase 2 slice done, Phase 5 pending") until Phase 5.
3. **PLAT-02 `[x]` - defensible but slightly overstated.** Model metadata is now populated (the previous blocker). Still open: append-only enforcement is by convention only, and "user actions" lack a producer until Phase 4. Either keep `[x]` with a note or move to Phase 4 closure. Verifier recommendation: keep `[x]` for the Phase 2 slice only if the project convention allows per-phase partial completion; otherwise revert.
4. **PLAN-01 `[ ]` - correct** (parallel specialist dispatch is Phase 3). Do not check.
5. **Traceability table** (line 87) still says "Pending" for PLAN-01..02, PLAT-02, PLAT-06 - stale relative to the checkboxes; set PLAN-02 to Complete and the others to Partial/In progress as appropriate.
6. FIRE-01/FIRE-02 are claimed by 02-01 but traceability assigns them to Phase 1 and the boxes are `[ ]`; reconcile ownership.
7. Not REQUIREMENTS.md but related: ROADMAP.md line 35 still reads "5/9 plans executed (4 gap-closure plans pending)" while all nine plan checkboxes are `[x]`; STATE.md still says "3/3 plans; Phase 2 verification pending". `02-VALIDATION.md` still has `nyquist_compliant: false` and lists live checks as manual-only although executed.

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
| ---- | ------- | -------- | ------ |
| `graph.py` / `audit.py` | `agent_runs.status` always `'succeeded'` (also for `run_weather` with an error output); node exception aborts before `write_audit`, nothing persisted (MD-06, out of gap-closure scope) | Warning | Audit trail honest for the happy path; failed runs leave no trace |
| `graph.py` routing | Routing penalises only P50 1h; first non-blocked (even "caution") route accepted (MD-02, MD-03) | Warning | Deferred to Phase 3 (PLAN-03) |
| `ca_model.py` | RNG re-seeded per horizon segment; 3 seeds make "P90" = any-of-3 (MD-05, LO-03) | Warning | Statistical meaning weak; labelled uncalibrated, wide bands |
| `migrations` | No DB-level append-only enforcement on `agent_runs` | Warning | Convention only |
| `config/defaults.yaml` | `llm_enabled: false` default | Info | Intentional (D-08); demo/tests enable via env |

No `TBD`/`FIXME`/`XXX` markers in Phase 2 source (grep clean). No hard-coded model id. No blockers.

### Human Verification Required

1. **Bandipur route/exit suitability** - Test: operator reviews the AOI-boundary exit nodes and routes produced for a realistic OSM graph (not the 3-node stub). Expected: exits and routes are operationally sensible. Why human: domain judgment; the bundled demo can only show a 'blocked' route on the stub graph.
2. **Operator confirmation of live Groq path (non-blocking)** - Test: `.venv\Scripts\python.exe scripts\replay_demo.py` with the operator's key. Expected: `LLM Fallback : No`, model `groq/openai/gpt-oss-20b`. Why human: external provider/secret; already evidenced in the live DB.

### Gaps Summary

No gaps. Every previous gap and human-needed item is closed or reclassified, all gap-closure plans (02-04..02-09) deliver their must-haves in code, tests and live data, and the offline suite is green. Status is `human_needed` solely because the decision tree requires it while the domain-judgment item (and the optional operator confirmation) remain; this should not block moving to Phase 3 if the orchestrator accepts those as non-gating. Out-of-scope review items (MD-01..MD-10, LO-*) are recorded as deferred warnings.

---

_Verified: 2026-10-17_
_Verifier: Claude (gsd-verifier)_

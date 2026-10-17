---
phase: 02-mvp-detection-to-route
verified: 2026-10-17T04:00:00Z
status: gaps_found
score: 7/8 must-haves verified
behavior_unverified: 1
overrides_applied: 0
gaps:
  - truth: "Agent runs store model metadata in audit records (PLAT-02; 02-02 Task 4 'Populate model_metadata in AuditEntry' for generate_rationale)"
    status: failed
    reason: "The model_metadata column (migration 0005), AuditEntry.model_metadata field, flush_audit_entries and the audit API all exist, but coordinator.graph._audit() never sets model_metadata and generate_rationale() returns only (text, is_fallback). Live DB check: all 8 agent_runs rows of the latest replay have model_metadata = NULL, including the generate_rationale row. Model name, provider, token limit and fallback reason are not recorded anywhere in the audit trail."
    artifacts:
      - path: "apps/coordinator/src/coordinator/graph.py"
        issue: "_audit() builds AuditEntry without model_metadata; generate_rationale_node does not pass any"
      - path: "apps/coordinator/src/coordinator/llm/groq_adapter.py"
        issue: "Returns tuple[str, bool]; exposes no model/provider/error metadata for the caller to audit"
    missing:
      - "Populate model_metadata for the generate_rationale audit entry (provider, settings.llm_model, max_tokens, timeout, is_fallback, error type on fallback)"
      - "Add a test asserting generate_rationale audit entry carries non-null model_metadata"
deferred:
  - truth: "PLAN-01 clause: 'dispatches eligible specialists in parallel through typed tool contracts'"
    addressed_in: "Phase 3"
    evidence: "Phase 3 deliverables in ROADMAP.md include 'parallel specialist dispatch'. In Phase 2 only Fire is dispatched after Weather, so there is no eligible set to parallelise; the graph is linear by design."
  - truth: "JWT viewer-role protection on the read-only API (02-03 Task 1 text)"
    addressed_in: "Phase 4"
    evidence: "PLAT-01 is mapped to Phase 4; router module docstring and 02-VALIDATION.md state Phase 2 API is loopback-only pending Phase 4 JWT roles."
behavior_unverified_items:
  - truth: "Successful (non-fallback) Groq rationale generation against the real provider"
    test: "Run scripts/replay_demo.py with a valid GROQ_API_KEY and a currently-served Groq model in LLM_MODEL (e.g. set LLM_MODEL explicitly); inspect the printed 'LLM Fallback' line"
    expected: "LLM Fallback : No; rationale text is model-generated and grounded in the supplied fire/weather/route data"
    why_human: "Every plan_versions row currently in the live DB (latest 6 inspected, all from this session) has is_llm_fallback = true with 'LLM error: BadRequestError'. The hard-coded default model 'llama3-8b-8192' (scripts/replay_demo.py:168, tests/integration/test_coordinator_pipeline.py:134) appears to be rejected by Groq. The live tests still pass because the deterministic fallback masks the failure, so the 'real Groq' success path has never been observed end to end; only a mocked unit test covers it."
human_verification:
  - test: "Live Groq success path (see behavior_unverified_items)"
    expected: "LLM Fallback : No"
    why_human: "Requires a live provider and a valid served model name; fallback currently masks the failure"
  - test: "Suitability of AOI-boundary exit policy for Bandipur"
    expected: "Selected boundary nodes and the resulting route are operationally sensible to a domain operator"
    why_human: "Domain judgment; synthetic road graph used in replay (carried over from 02-VALIDATION.md manual-only list)"
---

# Phase 2: MVP Detection to Route Verification Report

**Phase Goal:** A hotspot or replay event produces a basic, auditable evacuation route suggestion for one pilot settlement cluster.
**Verified:** 2026-10-17
**Status:** gaps_found
**Re-verification:** No - initial verification

## Goal Achievement

The core pipeline is real and works: a replayed hotspot set goes through trigger lookup, weather, DBSCAN clustering, seeded CA ensemble, fire-penalised Dijkstra routing, rationale (LLM with deterministic fallback), plan persistence and audit persistence. One requirement-level gap exists (audit model metadata is never populated), and one important caveat: the live "real Groq" runs all took the fallback path.

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | Replay/hotspot event yields a draft evacuation plan with a route for the pilot cluster | VERIFIED | `coordinator/runner.py` wires 8 nodes ingest_trigger -> run_weather -> cluster_hotspots -> run_fire_ca -> compute_route -> generate_rationale -> assemble_plan -> write_audit. Live DB: latest `plan_versions` row `status=draft`, `is_simulated=true`, plan_data routes = `[('safe', 2 nodes)]`. `scripts/replay_demo.py` seeds incident+5 hotspots+trigger+weather and drives it. |
| 2 | Output contains P50/P90 forecast data (1h/3h/6h) | VERIFIED | Live plan_data `fire_result` has non-empty WKT for current, p50_1h/3h/6h, p90_1h/3h/6h (MULTIPOLYGONs), area 3.5625 km2, confidence medium. `test_ca_model.py::test_ensemble_returns_all_perimeters` and `test_ensemble_deterministic` pass. Note: `settlements_at_risk` is empty in the replay (no settlement data seeded; FIRE-02 is Phase 1 scope). |
| 3 | Audit entries cover every Coordinator node/tool call | VERIFIED | Each of 8 nodes calls `_audit()` with inputs/outputs/latency; live DB shows exactly 8 `agent_runs` rows (one per node name) for the run; `test_pipeline_offline.py` asserts 8 entries and 8 flushed rows; tool calls (weather, CA, route, LLM) occur inside audited nodes. |
| 4 | Fallback works with LLM disabled/failing | VERIFIED | `generate_rationale` catches all exceptions -> `[DETERMINISTIC FALLBACK] ...`, `is_fallback=True`. Independently run with empty API key against the live plan: returned fallback text. Unit tests cover raise and empty-response paths. All live plan rows carry the fallback marker and still persisted. (Caveat: `replay_demo.py` refuses to start without GROQ_API_KEY, and no Coordinator-level test exercises the empty-key path; adapter-level coverage only.) |
| 5 | Core tests pass | VERIFIED | Re-ran `.venv\Scripts\python.exe -m pytest -q`: 55 passed, 7 skipped (the 7 skips are COMPOSE_SMOKE/Groq-gated). Session-reported live run: 62 passed. |
| 6 | PLAN-01: Coordinator invokes Weather before Fire | VERIFIED | `runner.py` edge order run_weather -> cluster_hotspots -> run_fire_ca; `run_fire_ca` consumes `state["weather_snapshot"]`, falls back to stale-flagged snapshot with warning if weather errors. |
| 7 | Read-only API exposes incidents, plan, audit | VERIFIED | `routers/incidents.py` (list/plan/audit), 6 passing unit tests in `test_incidents_api.py`; smoke test GET /api/v1/incidents returns 200 (per session evidence); status-filter 500 fixed (CAST to text). |
| 8 | PLAT-02: audit records include model metadata (and are append-only) | FAILED | `model_metadata` is NULL on every audit row (live DB query), including `generate_rationale`; nothing in `graph.py` sets it (see gaps). Append-only is by convention only (INSERT ... ON CONFLICT DO NOTHING; no DB trigger/REVOKE preventing UPDATE/DELETE); `status` is hard-coded 'succeeded' even when a node degraded. |

**Score:** 7/8 truths verified (1 failed; 1 present-but-behavior-unverified item reported separately: live Groq success path).

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|--------------|----------|
| 1 | Parallel specialist dispatch (second half of PLAN-01) | Phase 3 | ROADMAP Phase 3 deliverables: "parallel specialist dispatch" |
| 2 | JWT viewer auth on `/api/v1` | Phase 4 | PLAT-01 mapped to Phase 4; loopback-only noted in router docstring and VALIDATION |

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `packages/wildfire_core/.../schemas/phase2.py` | Phase 2 contracts | VERIFIED | Used by coordinator, fire, API; schema tests pass |
| `apps/agents/fire/.../ca_model.py`, `ensemble.py` | Seeded CA, P50/P90 | VERIFIED | Real output in live plan; deterministic test passes |
| `apps/agents/weather/.../agent.py` | Weather snapshot | VERIFIED | Wired in `run_weather`; live replay used it |
| `apps/ingest_worker/.../clustering.py` | DBSCAN clusters | VERIFIED | 4 tests pass; wired in `cluster_hotspots_node` |
| `apps/agents/routing/.../{graph,costs,router}.py` | Cached OSM graph, fire penalties, Dijkstra | VERIFIED | 14 tests pass; wired in `compute_route_node` |
| `apps/coordinator/.../{graph,runner,state,audit}.py` | 8-node LangGraph + audit flush | VERIFIED (with gap 8) | Wired and executed live; model_metadata not populated |
| `apps/coordinator/.../llm/groq_adapter.py` | Rationale + fallback | VERIFIED (fallback) / success path unproven live | See behavior_unverified_items |
| `infra/migrations/versions/0005_phase2_plan_versions.py` | plan_versions + audit columns | VERIFIED | Live DB at head `0005_phase2_plan_versions` |
| `apps/api_gateway/.../routers/incidents.py` | 3 read endpoints | VERIFIED | Tests + smoke; no auth (deferred to Phase 4) |
| `scripts/replay_demo.py` | End-to-end demo | VERIFIED | Runs outside pytest after sys.path fix; exits 0 |
| `tests/fixtures/osm/bandipur_stub.graphml` | Offline graph fixture | VERIFIED | Loaded by tests and replay |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| runner.build_graph | 8 node functions | add_node/add_edge | WIRED | Entry `ingest_trigger`, END after `write_audit` |
| ingest_trigger | hotspots | triggers.details.hotspot_ids | WIRED | Incident-scoped hotspot load (not whole-table) |
| run_fire_ca | agent_fire.compute_fire_spread | direct call | WIRED | Largest cluster by point_count |
| compute_route_node | agent_routing | graph + penalties + Dijkstra | WIRED | Origin = cluster centroid; destinations = AOI boundary exit nodes |
| assemble_plan | plan_versions | INSERT status='draft' | WIRED | Incident -> 'planning' |
| write_audit | agent_runs | flush_audit_entries | WIRED | Self-audit entry included in flush |
| AuditEntry.model_metadata | agent_runs.model_metadata | flush_audit_entries | NOT_POPULATED | Plumbing present, no producer |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| plan_data.fire_result | perimeters | CA ensemble on seeded hotspots + weather row | Yes (live DB) | FLOWING |
| plan_data.routes | osm_node_path | Dijkstra on fixture graph | Yes, 1 safe route | FLOWING |
| agent_runs.model_metadata | model_metadata | none | No (NULL) | DISCONNECTED |
| plan_data.rationale_md | rationale | Groq | Fallback text only in all observed live runs | STATIC (fallback) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Offline suite | `.venv\Scripts\python.exe -m pytest -q` | 55 passed, 7 skipped | PASS |
| Latest live plan inspection | read-only SQL via scratch script | draft, 7 WKT fields non-empty, 1 safe route, 8 audit rows | PASS |
| Alembic head | `select version_num from alembic_version` | `0005_phase2_plan_versions` | PASS |
| LLM disabled (empty key) | `generate_rationale(..., groq_api_key="")` | `[DETERMINISTIC FALLBACK] ... (LLM error: APIConnectionError)`, True | PASS |
| model_metadata populated | query agent_runs | all NULL | FAIL |

### Probe Execution

No `probe-*.sh` scripts declared or present. SKIPPED.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| PLAN-01 | 02-01 (partial), 02-02 | Weather before Fire, then parallel specialists via typed contracts | PARTIAL (Phase 2 portion SATISFIED) | Ordering and typed contracts verified; parallel dispatch deferred to Phase 3. REQUIREMENTS.md still shows `[ ]` and "Pending" - consistent with partial, but traceability not updated by plans. |
| PLAN-02 | 02-02, 02-03 | Basic route suggestion from Coordinator+Fire+Weather+road graph | SATISFIED | Live draft plan with safe route; REQUIREMENTS.md `[x]` |
| PLAT-02 | 02-03 | Runs, tool calls, inputs, outputs, latency, model metadata, user actions in append-only audit | PARTIAL / BLOCKED on model metadata | Inputs/outputs/latency verified; model metadata never populated; append-only not DB-enforced; user actions n/a until Phase 4. REQUIREMENTS.md marks `[x]` - overstated. |
| PLAT-06 | 02-03 | Test coverage appropriate to phase | SATISFIED for Phase 2 | Unit, integration (live-gated), smoke, offline pipeline tests; 55 pass offline. Gap: no offline test combines real CA + routing with mocked LLM (offline pipeline test stubs fire result with `POLYGON EMPTY`, graph, and weather); P50/P90 content is only asserted via live run and CA unit tests. |

All four phase requirement IDs (PLAN-01, PLAN-02, PLAT-02, PLAT-06) are present in REQUIREMENTS.md and accounted for. No orphaned Phase 2 requirements: FIRE-01/FIRE-02 are declared by plan 02-01 but REQUIREMENTS.md traceability assigns them to Phase 1 (document inconsistency, low impact).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `scripts/replay_demo.py`, `tests/integration/test_coordinator_pipeline.py` | 168 / 134 | Hard-coded default model `llama3-8b-8192` that Groq appears to reject (BadRequestError) | Warning | Live "real Groq" validation silently exercised only the fallback; `config/defaults.yaml` has `llm_model: ""` |
| `apps/coordinator/src/coordinator/graph.py` | `_audit` | `agent_runs.status` always 'succeeded'; model_metadata never set | Warning/Blocker for PLAT-02 | See gap |
| `tests/integration/test_coordinator_pipeline.py` | assertions | Does not assert `is_llm_fallback is False` | Warning | Test passes on fallback, so it cannot detect a broken LLM path |
| `apps/api_gateway/.../incidents.py` | - | No auth (plan said JWT viewer) | Info | Deferred to Phase 4, loopback-only |

No TODO/FIXME/TBD/XXX markers found in modified Phase 2 source.

### Uncommitted fixes made this session (noted per request)

- `scripts/replay_demo.py`: adds pytest `pythonpath` entries to `sys.path` so it runs outside pytest.
- `apps/api_gateway/src/api_gateway/routers/incidents.py`: `CAST(:status AS text)` fixes AmbiguousParameter 500 when no status filter is given.
- `infra/migrations/env.py`: prefers `DATABASE_URL` (env or repo `.env`) over alembic.ini placeholder.
- `tests/integration/test_migrations_and_ingest.py`: assertions scoped to own rows.

These are reviewed and look correct, but are uncommitted; they must be committed for the verified behavior to be reproducible from the repo.

### Human Verification Required

1. **Live Groq success path** - Run `scripts/replay_demo.py` with a valid key and an explicitly set, currently served `LLM_MODEL`. Expected `LLM Fallback : No`. Why human: needs a live provider/valid model; all observed live runs fell back.
2. **AOI-boundary exit suitability for Bandipur** - domain operator review of selected exits/routes (synthetic graph).

### Gaps Summary

One blocking gap: PLAT-02 requires model metadata in audit records, and plan 02-02 Task 4 required populating it for the LLM node; the field is plumbed end to end but never written (all NULL in the live DB). Fix is small (return/record provider, model, limits, fallback reason from the rationale step and pass to `_audit`) plus one test. Secondary items, not gating on their own: fix the default Groq model so the live LLM path actually succeeds and make the integration test assert `is_llm_fallback is False` when a key is configured; consider DB-level append-only enforcement or soften the PLAT-02 claim; add an offline test running real CA + routing with mocked LLM and asserting non-empty P50/P90 and a route; update REQUIREMENTS.md (PLAN-01 partial, PLAT-02 status) and 02-VALIDATION.md frontmatter/sign-off (still `nyquist_compliant: false`, live checks still listed manual-only although executed).

---

_Verified: 2026-10-17_
_Verifier: Claude (gsd-verifier)_

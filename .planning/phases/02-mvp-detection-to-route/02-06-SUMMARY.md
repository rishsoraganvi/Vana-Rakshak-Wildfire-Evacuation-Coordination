---
phase: 02-mvp-detection-to-route
plan: 06
subsystem: coordinator-llm-audit
tags: [groq, audit, model-metadata, gap-closure, gpt-oss]
requires: []
provides:
  - "RationaleResult and base_model_metadata in the Groq adapter; generate_rationale(fire_results, weather, routes, settings) -> RationaleResult"
  - "model_metadata on every generate_rationale audit row (success, fallback, inputs_unavailable), persisted as jsonb"
  - "Config gating (llm_enabled, provider groq, model, key) before any client construction or sleep"
  - "Config-driven default model openai/gpt-oss-20b; live test and demo fail/warn loudly on silent fallback"
affects: [02-07]
tech-stack:
  added: []
  patterns: ["ordered config gates returning a deterministic fallback with a reason code", "non-secret metadata built from an explicit field list"]
key-files:
  created:
    - .planning/phases/02-mvp-detection-to-route/COVERAGE.md
  modified:
    - apps/coordinator/src/coordinator/llm/groq_adapter.py
    - apps/coordinator/src/coordinator/graph.py
    - apps/coordinator/src/coordinator/audit.py
    - apps/coordinator/tests/test_groq_adapter.py
    - apps/coordinator/tests/test_pipeline_offline.py
    - config/defaults.yaml
    - scripts/replay_demo.py
    - tests/integration/test_coordinator_pipeline.py
    - packages/wildfire_core/src/wildfire_core/config.py
key-decisions:
  - "Default Groq model is the config value openai/gpt-oss-20b (Groq's documented replacement for the shut-down D-08 model); llm_enabled stays false so the operator opts in (HI-05)"
  - "GPT-OSS requests send reasoning_effort=low and include_reasoning=False inside the unchanged 400-token cap (D-09); max_completion_tokens replaces max_tokens"
  - "Blank environment values are treated as unset by load_settings so they cannot shadow config defaults"
  - "Groq prompt carries deterministic metrics only (no WKT polygons, no per-node route paths)"
requirements-completed: []
status: complete
duration: 45min
completed: 2026-10-17
actuals:
  tokens: 30000
  tasks: 3
  commits: 9
---

# Phase 2 Plan 06: Audit model_metadata, LLM gating, configurable model Summary

The generate_rationale audit row now records which model wrote the rationale (or why it fell back), Groq is never contacted unless explicitly enabled, the model is a config value, and a real Groq call has been observed answering end to end.

## Tasks

| # | Task | Commits |
|---|------|---------|
| 1 | Tracer: model_metadata from adapter to audit params (PLAT-02 gap, MD-06 note) | 5d95b76 (RED), b2be2be |
| 2 | Honour llm_enabled / provider; config model; loud live check (HI-05, MD-11) | 6321d5c (RED), 2f89f31, 025ec67 |
| 3 | Groq API coverage matrix and live checks | fd9fcc0 |
| - | Deviation fixes found by live run | 70e5989, 38d5692, 0f88eaf |

## What changed

- groq_adapter.py: frozen `RationaleResult`, `base_model_metadata`, metadata keys provider, model, llm_enabled, max_completion_tokens, timeout_s, llm_called, is_fallback, fallback_reason, finish_reason, usage, response_model, reasoning_effort. Gate order llm_disabled, provider_not_groq, model_not_configured, api_key_missing, all before the client and the sleep. Errors give `error:<ExceptionClass>`. The API key never appears in metadata (tested).
- graph.py: `_audit(..., model_metadata=None)`; generate_rationale_node passes result metadata, or an `inputs_unavailable` record; other nodes stay NULL.
- audit.py: `json.dumps(model_metadata, sort_keys=True)` before `CAST(:model_metadata AS jsonb)`.
- defaults.yaml: llm_provider groq, llm_model openai/gpt-oss-20b, llm_enabled false.
- replay_demo.py: no hard-coded model; setdefault LLM_ENABLED/LLM_PROVIDER; prints `LLM Model` and fallback reason; stderr warning on fallback.
- Integration test asserts `is_llm_fallback is False` and persisted metadata (model, is_fallback false, llm_called true).

## Live results (Compose up, key configured, run against the existing stack)

- (a) Resolved config after load_dotenv: provider `anthropic`, model blank, enabled false. These come from the operator's .env, see Deviation 1.
- (b) After the config fix: `openai/gpt-oss-20b True` in Groq models.list.
- (c) `COMPOSE_SMOKE=1 pytest tests/integration/test_coordinator_pipeline.py -m integration`: **1 passed** (Groq actually answered, is_llm_fallback False).
- (d) `replay_demo.py` (with `LLM_ENABLED=true LLM_PROVIDER=groq` exported): `LLM Model : groq/openai/gpt-oss-20b`, `LLM Fallback : No`, 8 audit entries, exit 0.
- (e) `GET /api/v1/audit/{incident_id}`: generate_rationale entry has non-null model_metadata (is_fallback false, finish_reason `stop`, usage 530 prompt / 236 completion / 766 total tokens, response_model openai/gpt-oss-20b); other 7 entries have null. No truncation, no empty rationale, so the 400-token cap was not touched.

Offline suite: 87 passed, 7 skipped. ruff clean on apps/packages/scripts/tests; mypy on apps/agents/routing/src + apps/coordinator/src: 0 non-import-untyped errors.

## Deviations from Plan

**1. [Rule 3 - Blocking] Blank env var shadowed the config default model**
- **Found during:** Task 3 check (b)
- **Issue:** The operator environment has `LLM_MODEL=` (blank), `LLM_PROVIDER=anthropic`, `LLM_ENABLED=false`. `load_settings` applied the blank LLM_MODEL over defaults.yaml, so the model was blank (model_not_configured) and the served-model check printed False.
- **Fix:** `load_settings` skips env values that are blank after strip. Test `test_blank_env_value_does_not_shadow_config_default`. .env untouched.
- **Files:** packages/wildfire_core/src/wildfire_core/config.py, apps/coordinator/tests/test_groq_adapter.py
- **Commit:** 70e5989

**2. [Rule 1 - Bug] Groq returned 413 because the prompt carried full WKT geometry**
- **Found during:** Task 3 check (c)
- **Issue:** The payload was about 35k chars (~16k tokens): 7 WKT polygons plus node paths. Groq returned 413 `rate_limit_exceeded` (on-demand TPM limit 8000), so every live run fell back. This is the cause behind "all live runs silently fall back" beyond the retired model.
- **Fix:** Payload now excludes the WKT fields and sends route summaries (path_node_count, fire_penalty_edge_count) instead of node paths; prompt dropped to ~530 tokens. Token cap unchanged. Test `test_generate_rationale_payload_omits_bulky_geometry`.
- **Commit:** 38d5692

**3. [Rule 1 - Bug] Demo crashed printing real LLM text on a cp1252 console**
- **Issue:** The rationale contained U+202F, `UnicodeEncodeError` after the plan was persisted.
- **Fix:** stdout/stderr reconfigured with `errors="replace"`.
- **Commit:** 0f88eaf

**4. Operational note (not a code deviation):** because `.env` sets LLM_ENABLED=false and LLM_PROVIDER=anthropic, and `load_dotenv` runs before the demo's `setdefault`, the demo only calls Groq when those are exported in the process environment (done for check (d)). The integration test uses monkeypatch.setenv, which overrides .env. The user may want to change those .env values; I did not edit .env. Also `grep -c "model_metadata=model_metadata" graph.py` is 2 rather than 1 (the AuditEntry construction plus the call site); intent met.

## Known Stubs

None.

## Threat Flags

None. T-02-06-01 and T-02-06-02 mitigations are tested offline (Groq never constructed when gated; key absent from metadata).

## Deferred (per plan)

MD-06 remainder, MD-10, LO-04, LO-05, LO-06, LO-09, DB-level append-only for agent_runs. Note for 02-07: the Groq prompt is now size-bounded per cluster; with many clusters it should stay compact (summaries only) to remain under the on-demand TPM limit of 8000 for openai/gpt-oss-20b.

## Self-Check: PASSED

Verified: COVERAGE.md exists (4 INTEGRATE rows, every OPT-OUT has a reason); commits 5d95b76, b2be2be, 6321d5c, 2f89f31, 025ec67, 70e5989, 38d5692, 0f88eaf, fd9fcc0 are in git log.

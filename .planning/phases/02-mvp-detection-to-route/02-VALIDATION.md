---
phase: "02"
slug: mvp-detection-to-route
status: validated
nyquist_compliant: false
wave_0_complete: true
created: "2026-10-14"
---

# Phase 02 — Validation Strategy

> Offline verification is complete. Live PostgreSQL/Groq and Compose checks remain manual-only because Docker’s engine and a Groq key were unavailable in this run.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `python -m pytest apps/coordinator/tests apps/api_gateway/tests apps/agents/routing/tests -q` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | ~6 seconds offline |

## Sampling Rate

- **After every task commit:** Run the nearest package test file.
- **After every plan:** Run `python -m pytest -q`, Ruff, and strict mypy for changed packages.
- **Before `/gsd:verify-work`:** Full offline suite must be green; service-gated checks are manual-only until Compose/Groq are available.
- **Max feedback latency:** 10 seconds for the offline unit suite.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | FIRE-01 | — | Config does not expose secrets | unit | `python -m pytest tests/unit/test_config.py -q` | ✅ | ✅ green |
| 02-01-02 | 01 | 1 | FIRE-01, FIRE-02 | — | Strict schemas reject invalid contracts | unit | `python -m pytest packages/wildfire_core/tests/test_phase2_schemas.py -q` | ✅ | ✅ green |
| 02-01-03 | 01 | 1 | FIRE-01 | — | Noise points are excluded | unit | `python -m pytest apps/ingest_worker/tests/test_clustering.py -q` | ✅ | ✅ green |
| 02-01-04 | 01 | 1 | PLAN-01 | — | Weather freshness remains explicit | integration | `COMPOSE_SMOKE=1 python -m pytest tests/integration/test_coordinator_pipeline.py -m integration -q` | ✅ | ⬜ manual-only |
| 02-01-05 | 01 | 1 | FIRE-01, FIRE-02 | — | Seeded CA output is deterministic | unit | `python -m pytest apps/agents/fire/tests/test_ca_model.py -q` | ✅ | ✅ green |
| 02-01-06 | 01 | 1 | FIRE-01 | — | Workspace dependencies resolve from lock | automated | `uv lock --check` | ✅ | ✅ green |
| 02-01-07 | 01 | 1 | FIRE-01, FIRE-02 | — | Core model output is repeatable | unit | `python -m pytest apps/agents/fire/tests/test_ca_model.py packages/wildfire_core/tests/test_phase2_schemas.py -q` | ✅ | ✅ green |
| 02-02-01 | 02 | 1 | PLAN-02 | — | Routes distinguish safe, caution, and blocked edges | unit | `python -m pytest apps/agents/routing/tests/test_router.py -q` | ✅ | ✅ green |
| 02-02-02 | 02 | 1 | PLAN-01 | — | LLM text is bounded; errors use deterministic fallback | unit | `python -m pytest apps/coordinator/tests/test_groq_adapter.py -q` | ✅ | ✅ green |
| 02-02-03 | 02 | 1 | PLAN-01 | — | Coordinator state is typed | static | `python -m mypy --python-version 3.12 apps/coordinator/src` | ✅ | ✅ green |
| 02-02-04 | 02 | 1 | PLAN-01, PLAT-02 | — | Node sequence and data flow produce eight audit rows | unit | `python -m pytest apps/coordinator/tests/test_pipeline_offline.py -q` | ✅ | ✅ green |
| 02-02-05 | 02 | 1 | PLAN-01 | — | Graph has eight nodes and the correct entry point | unit | `python -m pytest apps/coordinator/tests/test_graph_structure.py -q` | ✅ | ✅ green |
| 02-02-06 | 02 | 1 | PLAN-02, PLAT-02 | — | Plan/audit migrations preserve the existing audit schema | migration | `python -m alembic -c infra/migrations/alembic.ini upgrade head --sql` | ✅ | ✅ green; live upgrade manual-only |
| 02-02-07 | 02 | 1 | PLAN-02, PLAT-06 | — | Routing, Coordinator, and shared contracts pass | unit | `python -m pytest apps/agents/routing/tests apps/coordinator/tests packages/wildfire_core/tests/test_phase2_schemas.py -q` | ✅ | ✅ green |
| 02-03-01 | 03 | 1 | PLAT-02 | — | Read endpoints serialize summaries and return 404 for missing rows | unit | `python -m pytest apps/api_gateway/tests/test_incidents_api.py -q` | ✅ | ✅ green |
| 02-03-02 | 03 | 1 | PLAT-02 | — | Audit batch writes are idempotent and run through Coordinator | unit | `python -m pytest apps/coordinator/tests/test_audit.py apps/coordinator/tests/test_pipeline_offline.py -q` | ✅ | ✅ green |
| 02-03-03 | 03 | 1 | PLAN-02 | — | Bidirectional GraphML fixture loads with travel times | unit | `python -m pytest apps/agents/routing/tests/test_router.py -q` | ✅ | ✅ green |
| 02-03-04 | 03 | 1 | PLAN-02 | — | Replay refuses to run without a key and reports the missing setup | automated | `python scripts/replay_demo.py` without `GROQ_API_KEY` | ✅ | ✅ green; successful live replay manual-only |
| 02-03-05 | 03 | 1 | PLAN-02, PLAT-02 | — | Full Groq/Postgres pipeline persists a draft and audits | integration | `COMPOSE_SMOKE=1 python -m pytest tests/integration/test_coordinator_pipeline.py -m integration -q` | ✅ | ⬜ manual-only |
| 02-03-06 | 03 | 1 | PLAT-06 | — | Compose replay and loopback API work end to end | smoke | `COMPOSE_SMOKE=1 python -m pytest tests/smoke/test_compose_smoke.py -m smoke -q` | ✅ | ⬜ manual-only |
| 02-03-07 | 03 | 1 | PLAT-06 | — | All tests collect without import errors | automated | `python -m pytest --co -q` | ✅ | ✅ green |
| 02-03-08 | 03 | 1 | PLAN-02, PLAT-02, PLAT-06 | — | Roadmap and requirement traceability match completed plans | automated | `gsd-tools query roadmap.update-plan-progress 02` | ✅ | ✅ green |

## Wave 0 Requirements

- Existing pytest, Ruff, mypy, and Alembic infrastructure covers all offline-verifiable requirements.
- No additional framework installation was required during validation.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Apply revision `0005` to live PostgreSQL | PLAT-02 | Docker engine unavailable; only Alembic offline SQL rendering ran | Start Compose and run `python -m alembic -c infra/migrations/alembic.ini upgrade head`; inspect `plan_versions` and new `agent_runs` columns. |
| Full Coordinator pipeline with real Postgres and Groq | PLAN-02, PLAT-02 | Requires running database and a valid `GROQ_API_KEY` | Set `COMPOSE_SMOKE=1`, configure the key, and run `python -m pytest tests/integration/test_coordinator_pipeline.py -m integration -q`. |
| Replay demo and Compose API smoke | PLAN-02, PLAT-06 | Requires the Compose stack and Groq key for replay | Run `docker compose up -d --build --wait`, then `COMPOSE_SMOKE=1 python -m pytest tests/smoke/test_compose_smoke.py -m smoke -q`. |
| Suitability of the AOI-boundary exit policy for Bandipur operations | PLAN-02 | Domain judgment cannot be established by a synthetic road graph | Review the selected boundary nodes and route suggestions with a domain operator before any operational interpretation. |
| Viewer-role authorization | PLAT-01 | JWT roles are explicitly Phase 4 scope; Phase 2 API is loopback-only | Confirm API remains bound to `127.0.0.1`; implement and test JWT viewer roles in Phase 4 before remote exposure. |

## Validation Sign-Off

- [x] Offline plan requirements have automated verification or Wave 0 coverage.
- [x] Offline tests pass and collect without import errors.
- [ ] Live PostgreSQL migration, Groq integration, and Compose smoke checks are complete.
- [ ] Nyquist compliance is complete.
- [ ] `nyquist_compliant: true` set in frontmatter.

**Approval:** pending live-service checks and Phase 2 goal verification.

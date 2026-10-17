---
phase: 03
slug: capacity-aware-coordinated-planning
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-10-17
---

# Phase 03 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `03-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.2 + hypothesis 6.168.3 |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`; pythonpath must gain `apps/agents/shelter/src`) |
| **Quick run command** | `.venv\Scripts\python.exe -m pytest apps/agents/shelter apps/agents/routing apps/coordinator tests/unit -q -x` |
| **Full suite command** | `.venv\Scripts\python.exe -m pytest apps packages tests/unit -q` |
| **Estimated runtime** | ~30 seconds offline (Hypothesis `ci` profile) |

---

## Sampling Rate

- **After every task commit:** Run the nearest package test file (`pytest <package>/tests -q`), < 10 s
- **After every plan wave:** Run the full suite command, `ruff check .`, `mypy packages/wildfire_core` (+ strict mypy for new agent packages)
- **Before `/gsd-verify-work`:** Full offline suite green, `uv lock --check`, `alembic -c infra/migrations/alembic.ini upgrade head --sql` renders; live checks via `COMPOSE_SMOKE=1`
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

Task IDs are filled in by the planner/executor; requirement → test mapping is fixed here.

| Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|----------|-----------|-------------------|-------------|--------|
| PLAN-04 | Σ assigned ≤ usable − occupancy per shelter; assigned + unassigned = persons | property | `pytest apps/agents/shelter/tests/test_matching_properties.py -q` | ❌ W0 | ⬜ pending |
| PLAN-04 | Splitting; unplaceable group named | unit | `pytest apps/agents/shelter/tests/test_matching.py -q` | ❌ W0 | ⬜ pending |
| PLAN-04 | `update_occupancy` atomic, refuses overflow | unit + live | `pytest apps/agents/shelter/tests/test_registry.py -q`; live `tests/integration/test_shelters_db.py` | ❌ W0 | ⬜ pending |
| PLAN-04 | Shelter exclusion near forecast perimeter (1 km of P90-6h ∪ current) | unit | `pytest apps/agents/shelter/tests/test_exclusion.py -q` | ❌ W0 | ⬜ pending |
| PLAN-03 | Horizon cost attrs (blocked / P50×10 / P90×3), nearest-horizon rule, monotonic penalties | unit/property | `pytest apps/agents/routing/tests/test_costs_horizons.py -q` | ❌ W0 | ⬜ pending |
| PLAN-03 | k=3 distinct loopless paths on synthetic MultiDiGraph | unit | `pytest apps/agents/routing/tests/test_k_paths.py -q` | ❌ W0 | ⬜ pending |
| PLAN-03 | BPR formula, capacity from tags, ≤3 passes, deterministic | unit/property | `pytest apps/agents/routing/tests/test_congestion.py -q` | ❌ W0 | ⬜ pending |
| PLAN-03 | Blocked edge-status excluded; `road_blocked` detection | unit | `pytest apps/coordinator/tests/test_replan_triggers.py -q` | ❌ W0 | ⬜ pending |
| PLAN-07 | Resolver ≤3 loops, fixed order, enum-only LLM choice validated, fallback planner, `failed` names group/reason | unit/property | `pytest apps/coordinator/tests/test_resolver.py apps/coordinator/tests/test_fallback_planner.py -q` | ❌ W0 | ⬜ pending |
| PLAN-07 | LLM disabled/error ⇒ deterministic path | unit | `pytest apps/coordinator/tests/test_llm_menu.py -q` | ❌ W0 | ⬜ pending |
| PLAN-08 | V1–V8 pure functions (V6 trivial on empty dispatches; V8 grounding within rounding) | unit/property | `pytest apps/coordinator/tests/test_validators.py -q` | ❌ W0 | ⬜ pending |
| PLAN-08 | Validator failure ⇒ `failed`, never `pending_review` | unit | `pytest apps/coordinator/tests/test_plan_assembly.py -q` | ❌ W0 | ⬜ pending |
| PLAN-08 | Material diff ⇒ new version only on change; parent link | unit | `pytest apps/coordinator/tests/test_plan_diff.py -q` | ❌ W0 | ⬜ pending |
| PLAN-08 | Provenance + freshness on every plan | unit | `pytest apps/coordinator/tests/test_plan_provenance.py -q` | ❌ W0 | ⬜ pending |
| PLAN-08 | Migration 0006 renders; immutability trigger rejects `plan_data` update | migration + live | `alembic ... upgrade head --sql`; live `tests/integration/test_plan_versions_db.py` | ❌ W0 | ⬜ pending |
| PLAN-01 | Parallel specialist dispatch concurrent, error envelope, timeout | unit | `pytest apps/coordinator/tests/test_dispatch.py -q` | ❌ W0 | ⬜ pending |
| D-14/D-15 | IoU/growth thresholds; 5-min debounce per (incident, type); SimClock | unit | `pytest tests/unit/test_replan_triggers.py -q` | ❌ W0 | ⬜ pending |
| D-17 WR-01 | Per-cluster weather; cluster without weather fails closed | unit | `pytest apps/coordinator/tests/test_weather_per_cluster.py -q` | ❌ W0 | ⬜ pending |
| D-17 WR-03 | Parser stores observations (`valid_time <= issued_at`) with real origin; ingest → snapshot matches | unit + live | `pytest tests/unit/test_weather_parser.py -q`; live `tests/integration/test_weather_ingest_to_plan.py` | partial | ⬜ pending |
| D-20/D-21 | Risk assessment: P50 settlements → groups (ETA, priority); inside-fire exempt with alert; P90-only warning | unit | `pytest apps/agents/fire/tests/test_risk.py -q` | ❌ W0 | ⬜ pending |
| End to end | Synthetic graph + seeded shelters → validated plan; perimeter change ⇒ v2 with diff | integration (offline) + live | `pytest apps/coordinator/tests/test_pipeline_phase3.py -q`; live `COMPOSE_SMOKE=1` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### Planner task mapping (filled at plan time)

| Requirement row | Plan / Task | Notes |
|-----------------|-------------|-------|
| PLAN-04 matching properties | 03-01 T2 | `apps/agents/shelter/tests/test_matching_properties.py` |
| PLAN-04 splitting / unplaceable named | 03-01 T1-T2 | `apps/agents/shelter/tests/test_matching.py` |
| PLAN-04 update_occupancy atomic | 03-04 T3 | unit `test_registry.py`; live `tests/integration/test_shelters_db.py` |
| PLAN-04 shelter exclusion | 03-04 T3 | `apps/agents/shelter/tests/test_exclusion.py` |
| PLAN-03 horizon costs | 03-05 T1 | `apps/agents/routing/tests/test_costs_horizons.py` |
| PLAN-03 k=3 paths | 03-05 T1 | `apps/agents/routing/tests/test_k_paths.py` |
| PLAN-03 BPR congestion | 03-05 T2 | `apps/agents/routing/tests/test_congestion.py` |
| PLAN-03 blocked edge status / road_blocked | 03-05 T1, 03-11 T2 | edge-status blocking is in `test_costs_horizons.py`; road_blocked detection is in `tests/unit/test_replan_triggers.py`. Re-plan entry tests live in `apps/coordinator/tests/test_replan_entry.py`, renamed from the map's `apps/coordinator/tests/test_replan_triggers.py` to avoid a pytest basename collision with `tests/unit/test_replan_triggers.py` |
| PLAN-07 resolver / fallback | 03-09 T2 | `test_resolver.py`, `test_fallback_planner.py` |
| PLAN-07 LLM disabled / error | 03-07 T3 | `test_llm_menu.py` |
| PLAN-08 V1-V8 | 03-06 T1/T3, 03-07 T2 | V1-V7 in `test_validators.py` and `test_validator_properties.py`; V8 in `test_grounding.py`, a separate module because V8 runs after the rationale step |
| PLAN-08 failed, never pending_review | 03-07 T1 | `test_plan_assembly.py` |
| PLAN-08 material diff / parent link | 03-08 T2, 03-11 T1 | `test_plan_diff.py`, `test_replan_entry.py` |
| PLAN-08 provenance + freshness | 03-07 T2, 03-10 T1 | `test_plan_provenance.py`, `test_pipeline_phase3.py` |
| PLAN-08 migration 0006 / immutability | 03-04 T2, 03-08 T3 | `tests/unit/test_migration_0006.py` plus `alembic --sql`; live `tests/integration/test_plan_versions_db.py` |
| PLAN-01 parallel dispatch | 03-10 T2 | `test_dispatch.py` |
| D-14/D-15 thresholds + debounce | 03-11 T2 | `tests/unit/test_replan_triggers.py` |
| D-17 WR-01 per-cluster weather | 03-10 T3 | `test_weather_per_cluster.py` |
| D-17 WR-03 parser / ingest | 03-03 T1-T2 | `tests/unit/test_weather_parser.py`; live `tests/integration/test_weather_ingest_to_plan.py` |
| D-20/D-21 risk assessment | 03-06 T1-T2 | `apps/agents/fire/tests/test_risk.py` |
| End to end + v2 on perimeter change | 03-10 T1, 03-11 T1 | `test_pipeline_phase3.py`, `test_replan_entry.py` |
| Wave 0: .gitignore, graph fixture, Hypothesis profile, shelter package, CI target | 03-01 | |
| Wave 0: migration 0006, config block, repository interface | 03-04, 03-02, 03-08 | |

---

## Wave 0 Requirements

- [ ] `.gitignore`: add `data/` and `cache/`
- [ ] `tests/fixtures/graphs.py` — deterministic synthetic MultiDiGraph builder (≥3 corridors, parallel edges, list-string tags, a bottleneck, a dead end)
- [ ] `conftest.py` with Hypothesis `ci` profile (`derandomize=True`, `deadline=None`)
- [ ] `apps/agents/shelter/` package + workspace/pythonpath wiring, `uv lock`, refreshed `requirements.txt`
- [ ] Alembic 0006 migration; config sub-models in `config/defaults.yaml`
- [ ] Repository interface so coordinator nodes are testable without SQL-substring fakes
- [ ] CI: extend pytest target to `apps packages tests/unit` (or place new tests under `tests/unit`)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real OSM graph build for pilot area | PLAN-03 (D-05, D-19) | Needs network; user runs once | Run `scripts/build_osm_graph.py`; confirm `data/osm/*.graphml` loads |
| Replace synthetic seed with curated real CSVs | PLAN-04 (D-18) | Requires local knowledge/data | Supply `config/seed/*_bandipur.csv`, run seed script, re-run live suite |
| Live Postgres immutability trigger, occupancy CAS, weather ingest → plan | PLAN-04, PLAN-08, D-17 | Needs Compose stack | `set COMPOSE_SMOKE=1&& pytest tests/integration -q` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

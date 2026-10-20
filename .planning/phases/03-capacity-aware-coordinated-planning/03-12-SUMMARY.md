---
phase: 03-capacity-aware-coordinated-planning
plan: 12
subsystem: data
tags: [real-data, osm, seed, readiness-probe, plan-03, plan-04]
requires: [03-04, 03-05, 03-11]
provides:
  - "scripts/check_real_data.py: offline readiness probe (graph built/missing via load_graph, seed provenance synthetic/curated/mixed), exit 0 only when ready"
  - "Real Bandipur OSM drive graph at data/osm/bandipur_road_graph.graphml (git-ignored): 570 nodes, 1415 edges"
  - "Seed CSVs with real OpenStreetMap names and locations (20 schools, 10 villages/hamlets); capacities and populations remain labelled synthetic estimates"
  - "docs/datasets.md Real-data status table, OSM build record (k-path timing, reachability) and seed record"
affects: []
tech-stack:
  added: []
  patterns: ["probe reports pending as exit 1, never a CI gate", "external_ref carries the OSM element id for traceability"]
key-files:
  created:
    - scripts/check_real_data.py
    - tests/unit/test_check_real_data.py
  modified:
    - docs/datasets.md
    - config/seed/shelters_bandipur.csv
    - config/seed/settlements_bandipur.csv
key-decisions:
  - "Task 2 resolved 'built': the user ran build_osm_graph.py; 570 nodes is far below RESEARCH A17's 5-20k but was accepted as a property of the sparse reserve network plus the largest-SCC filter"
  - "Task 3 resolved by the user asking Claude to do it: names and locations come from OpenStreetMap (fetched 2026-10-20), but no surveyed capacity or population exists in OSM, so every estimated number keeps capacity_source/pop_source 'synthetic' and is_simulated true; the S9 estimate warning stays on every plan and check_real_data still reports the seed as synthetic (D-18 is only partly resolved)"
  - "Settlements were chosen only if their nearest real-graph road node is within 1800 m (margin under the 2000 m snap limit); the synthetic ST-07/ST-10 rows would have been unroutable"
  - "The two Hangala schools (~70 m apart, likely one campus) carry usable_factor 0.5 each to avoid double counting"
  - "The 20 SYN-SH and 10 SYN-ST rows were deleted from the local DB (user-approved; no occupancy rows, no FKs on settlements) before loading the OSM rows, because the upsert is keyed on external_ref and would otherwise leave both sets active"
requirements-completed: [PLAN-03, PLAN-04]
status: complete
duration: 60min
completed: 2026-10-20
actuals:
  tasks: 3
  commits: 5
---

# Phase 3 Plan 12: Real-data readiness, OSM graph and seed Summary

An offline probe now reports which real-data steps remain. The real Bandipur road graph is built, and both seed files now point at real schools and villages from OpenStreetMap. Capacities and populations are still estimates and stay labelled as such.

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 (tracer) | Offline readiness probe, unit tests, Real-data status section | 1b509ba |
| 2 (human-action: "built") | Record real OSM graph build, k-path timing, settlement reachability | dc45215 |
| 3 (human-action: done by Claude at the user's request) | OSM-based shelter and settlement seed, seed record | 6674725 |

## What changed

- `check_real_data.py` loads the graph with the load-only `load_graph` and never downloads. It counts seed rows by `capacity_source` / `pop_source` and labels each file synthetic, curated or mixed.
- Real graph: 570 nodes, 1415 edges. A k=3 query across the extent took 0.063 s including the collapse, far under `k_paths_max_leg_s` (5.0 s).
- Seed: 20 nearest named schools. Generic names get "(near <place>)" appended. Capacity estimates by school type: HPS 250, LPS 120, PU college 400, residential 200. The 10 nearest road-reachable villages and hamlets get village 600 and hamlet 250. Each `notes` field and `external_ref` names the OSM element.
- Local DB: old synthetic rows removed. 20 shelters and 10 settlements loaded, all `OSM-*`.

## Verification

- `pytest apps packages tests/unit -q`: 486 passed, 1 skipped (481 before this plan + 5 probe tests).
- `pytest tests/unit/test_seed_rows.py tests/unit/test_check_real_data.py tests/unit/test_repositories_phase3.py apps/agents/shelter -q`: 54 passed with the new CSVs.
- `seed_shelters.py --dry-run` / `seed_settlements.py --dry-run` validate 20 and 10 rows. The loads report 20 and 10.
- `check_real_data.py`: graph built, shelters and settlements synthetic (expected, see decisions).
- `COMPOSE_SMOKE=1 pytest tests/integration -m compose -q`: 9 passed, 1 deselected, after fixing a stale Phase 1 schema-boundary test (see deviations).
- `git status --porcelain data/` is empty.
- API image rebuilt before this plan. `GET /api/v1/incidents/{id}/plan` served a failed replay plan with failure reasons, alerts and freshness.

## Deviations

- Task 3 was not completed by the user supplying curated CSVs. At the user's instruction, Claude sourced real locations from OpenStreetMap and kept the numbers labelled synthetic instead of inventing "curated" figures. D-18 stays open until surveyed capacities and Census populations replace the estimates.

- `test_phase_one_schema_boundary` still asserted that no `shelters` table exists. Migration 0006 (plan 03-04) added it on purpose, so the test had been failing since 03-04. It now expects `shelters` and still forbids `plans`, `plan_reviews` and `vehicles`.

## Open items

- Replace estimated capacities and populations with sourced figures, then set the source and `is_simulated` false.
- `scripts/replay_demo.py` forces the 3-node stub graph, so the demo still produces a failed plan. Production planning uses the real graph.
- mypy: `agent_routing.graph` import-not-found in scripts (routing src missing from `mypy_path`), plus 16 pre-existing errors in `test_phase2_schemas.py`. Fix in the regression gate.
- Demo prints the provider label `anthropic/openai/gpt-oss-20b` (pre-existing metadata label bug).

## Self-Check: PASSED

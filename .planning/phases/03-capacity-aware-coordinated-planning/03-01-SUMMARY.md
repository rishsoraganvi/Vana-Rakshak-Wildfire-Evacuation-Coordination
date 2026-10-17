---
phase: 03-capacity-aware-coordinated-planning
plan: 01
subsystem: shelter-matching
tags: [shelter, min-cost-flow, hypothesis, ci, synthetic-graph, plan-04]
requires: []
provides:
  - "agent_shelter.match_groups_to_shelters(groups, available, costs, *, banned, per_pair_cap) -> MatchResult(legs, unassigned, unplaceable_reasons, total_cost_ds)"
  - "tests.fixtures.graphs.build_synthetic_graph(): deterministic 6x6 MultiDiGraph (CORNER_SW=1, CORNER_NE=36, DEAD_END=37) with parallel edge, bottleneck, mixed lanes tags"
  - "Root conftest.py Hypothesis ci profile (derandomize, no deadline, 200 examples)"
  - "CI unit job runs pytest apps packages tests/unit and mypy on agent_shelter"
  - "data/ and cache/ git-ignored"
affects: [03-02, 03-05, 03-06, 03-09]
tech-stack:
  added: []
  patterns: ["integer-decisecond weights for nx.min_cost_flow", "diagnostic unassigned sink node U", "sorted edge insertion for determinism"]
key-files:
  created:
    - apps/agents/shelter/pyproject.toml
    - apps/agents/shelter/src/agent_shelter/__init__.py
    - apps/agents/shelter/src/agent_shelter/py.typed
    - apps/agents/shelter/src/agent_shelter/matching.py
    - apps/agents/shelter/tests/test_matching.py
    - apps/agents/shelter/tests/test_matching_properties.py
    - tests/__init__.py
    - tests/fixtures/__init__.py
    - tests/fixtures/graphs.py
    - tests/unit/test_graph_fixture.py
    - conftest.py
  modified:
    - pyproject.toml
    - packages/wildfire_core/pyproject.toml
    - apps/coordinator/pyproject.toml
    - uv.lock
    - requirements.txt
    - .github/workflows/ci.yml
    - .gitignore
key-decisions:
  - "uv.lock revision header restored to 5 by hand: local uv 0.12.5 rewrites it to 3, CI pins uv 0.8.17; uv lock --check passes with revision 5"
  - "Tracer test asserts the optimal split {(g1,s6):50,(g1,s36):70} instead of the plan's {(g1,s36):120}, because shelter node 6 is nearer node 1 than node 36 on the synthetic graph"
  - "matching.py annotates the flow graph as nx.DiGraph[Any] and narrows flow nodes with isinstance(tuple) so it type-checks against types-networkx"
requirements-completed: []
status: complete
duration: 40min
completed: 2026-10-17
actuals:
  tokens: 36000
  tasks: 3
  commits: 3
---

# Phase 3 Plan 01: agent-shelter matching, synthetic graph fixture, CI target Summary

Capacity-safe group-to-shelter matching via integer min-cost flow with a diagnostic unassigned sink, proven by 5 Hypothesis properties (200 derandomized examples each), plus a deterministic synthetic road graph and a CI job that now runs package-local tests.

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 | Tracer: agent-shelter workspace package, matcher, synthetic graph, lock refresh | e39a1bf |
| 2 | Capacity, conservation, split, banned-pair and determinism tests and properties; Hypothesis ci profile | 17094e6 |
| 3 | CI runs `pytest apps packages tests/unit`, graph fixture tests, `data/` and `cache/` ignored | cbb07c0 |

Tracer gate (auto mode active): the tracer verify (pytest plus `uv lock --check`) was re-run after the commit and passed, so expansion proceeded.

## What changed

- `agent_shelter.matching` builds the S -> group -> shelter -> T network plus a `U` sink. Weights are `round(cost_s * 10)` integers, edges are inserted in sorted order, and pairs with None, NaN or inf cost, or in `banned`, are skipped. Group-to-shelter capacity is `min(persons, per_pair_cap)`. Groups below 1 person raise `ValueError`; negative availability clamps to 0. Unassigned groups carry reason `no_reachable_shelter` or `insufficient_capacity`.
- `agent-shelter` is a uv workspace member wired into the root workspace, sources, pytest `pythonpath` (plus `"."` so `tests.fixtures.graphs` imports) and mypy path. The coordinator depends on it. `wildfire-core` gained `shapely` and `pyproj` for Plan 03-02; both were already locked, so no new registry package entered `uv.lock`.
- Synthetic graph: 6x6 lattice, primary/secondary/residential classes, `lanes` as `"2"`, `"['1', '2']"` or absent, a slower parallel edge (key 1) between nodes 2 and 3, a single-lane `track` bottleneck between nodes 15 and 16, and dead-end node 37.

## Verification

- `pytest apps packages tests/unit -q`: 126 passed, 1 skipped (22 new tests: 16 in the shelter package, 6 in `test_graph_fixture.py`). The 104/8 baseline was measured over a different test selection, so the skip count is not directly comparable.
- Shelter suite alone: 16 passed (11 unit, 5 properties) in about 23 s.
- `ruff check .` clean. `mypy --ignore-missing-imports apps/agents/shelter/src/agent_shelter` clean.
- `uv lock --check` passes; first lines of `uv.lock` are `version = 1`, `revision = 5`.
- `git check-ignore` confirms `data/osm/...` and `cache/...` are ignored; `GUIDE.md` line kept.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug in plan] Tracer expectation contradicted the optimum**
- **Found during:** Task 1
- **Issue:** The plan asserts `legs == {("g1","s36"): 120}` with `available {"s36": 200, "s6": 50}`. On the synthetic graph shelter node 6 is about 5 hops from node 1 and node 36 about 10, so the min-cost optimum fills s6 (50) first and sends the remaining 70 to s36.
- **Fix:** The tracer test asserts the optimal split and that s6 is cheaper than s36.
- **Files modified:** apps/agents/shelter/tests/test_matching.py
- **Commit:** e39a1bf

**2. [Rule 3 - Blocking] uv lock rewrote the lock revision**
- **Issue:** uv 0.12.5 wrote `revision = 3`, violating the acceptance criterion and risking CI's pinned uv 0.8.17.
- **Fix:** Restored `revision = 5` by hand; `uv lock --check` still passes.
- **Commit:** e39a1bf

**3. [Rule 3 - Blocking, not fixed] types-networkx stubs not installed locally**
- **Issue:** `.venv` lacks `types-networkx` (locked dev dependency) and offline install failed because the wheel is not cached. Plain `mypy apps/agents/shelter/src/agent_shelter` therefore reports `import-untyped` for networkx. No network install was attempted per the run constraints.
- **Mitigation:** Verified with `--ignore-missing-imports`, and wrote the annotations defensively (`nx.DiGraph[Any]`, `isinstance` narrowing). CI installs the stubs through `uv sync --locked`; the stub-typed result is unverified locally.

**4. [TDD note] No RED failure for Task 2**
- The tracer implemented the full matcher semantics from the plan, so the new unit tests and properties passed on first run. They were committed as a `test(...)` commit with no `feat` follow-up. The properties were still run against the implementation and none required a matcher change.

## Deferred Issues

- `mypy packages/wildfire_core` (the existing CI command) reports 16 `no-untyped-def` style errors, all in the pre-existing `packages/wildfire_core/tests/test_phase2_schemas.py` (last touched by Phase 2). Not caused by this plan; out of scope.

## Known Stubs

None.

## Threat Flags

None. No new network endpoints, auth paths or schema changes. T-03-01-01..04 mitigations are in place (integer weights and sink, properties enforced by CI, no registry packages added, `data/` and `cache/` ignored, sorted insertion and determinism property).

## Self-Check: PASSED

- Files exist: matching.py, test_matching.py, test_matching_properties.py, graphs.py, test_graph_fixture.py, conftest.py, apps/agents/shelter/pyproject.toml.
- Commits exist: e39a1bf, 17094e6, cbb07c0.

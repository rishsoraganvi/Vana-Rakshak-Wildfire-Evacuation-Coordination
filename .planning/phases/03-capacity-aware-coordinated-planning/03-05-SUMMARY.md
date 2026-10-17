---
phase: 03-capacity-aware-coordinated-planning
plan: 05
subsystem: routing
tags: [routing, networkx, shapely, strtree, bpr, yen, osmnx, load-only-graph, plan-03]
requires:
  - "03-01: agent-routing workspace member"
  - "03-02: wildfire_core.geo.horizons.nearest_horizon_h, ForecastFootprint, buffer_metric, Phase 3 settings (route_p50_mult, route_p90_mult, bpr_*, lane_capacity_vph, k_paths*, pilot_*)"
  - "03-04: road_edge_status repositories (edge statuses are passed in as a mapping)"
provides:
  - "agent_routing.costs: apply_horizon_costs, refresh_horizon_costs, edge_geometry (public)"
  - "agent_routing.router: snap_points, route_cost_matrix, LegCost, build_route_edges, evaluate_path, PathEvaluation"
  - "agent_routing.k_paths: collapse_to_digraph, k_shortest_paths, KPaths"
  - "agent_routing.congestion: parse_tag, edge_capacity_vph, bpr_time, edge_flows_vph, msa_blend, apply_congestion"
  - "agent_routing.graph: load_graph (load-only, in-process cache), build_graph_for_area, GraphNotBuiltError"
  - "scripts/build_osm_graph.py: explicit human-run OSM build with --check and --dry-run"
affects: [03-06, 03-07, 03-09, 03-10, 03-12]
tech-stack:
  added: []
  patterns: ["one STRtree per graph, one query per perimeter", "collapse MultiDiGraph to DiGraph before Yen", "guarded ast.literal_eval for GraphML list-strings", "atomic temp-file write then os.replace", "load-only runtime with an explicit build script"]
key-files:
  created:
    - apps/agents/routing/src/agent_routing/k_paths.py
    - apps/agents/routing/src/agent_routing/congestion.py
    - scripts/build_osm_graph.py
    - apps/agents/routing/tests/test_costs_horizons.py
    - apps/agents/routing/tests/test_k_paths.py
    - apps/agents/routing/tests/test_congestion.py
    - apps/agents/routing/tests/test_graph_loader.py
  modified:
    - apps/agents/routing/src/agent_routing/costs.py
    - apps/agents/routing/src/agent_routing/router.py
    - apps/agents/routing/src/agent_routing/graph.py
    - apps/agents/routing/src/agent_routing/__init__.py
    - apps/agents/routing/tests/test_router.py
key-decisions:
  - "Blocked means current perimeter or edge status blocked/unsafe; blocked edges are hidden (None weight) from Dijkstra and dropped from the collapsed DiGraph, so an inf cost can never be ranked"
  - "route_cost_matrix times legs on congested_time (free flow when no flow is assigned), picks the horizon with nearest_horizon_h(free_flow_s / 60) and reads that horizon's cost_h Dijkstra; origin == target is LegCost(0, 0, 1)"
  - "evaluate_path uses end-of-edge arrival (conservative) with the same nearest_horizon_h rule validator V3 will use (D-21)"
  - "k_shortest_paths truncation fires only when at least one path exists and the budget is spent (>= so a zero budget returns exactly one path)"
  - "msa_blend iteration 1 returns the new flows exactly; later iterations average over the union of keys"
  - "load_or_download_graph stays as a deprecated wrapper over load_graph so the Phase 2 coordinator keeps importing it until plan 03-10"
  - "build_graph_for_area writes to a .tmp sibling then os.replace, so a failed build leaves no partial graph file"
requirements-completed: []
status: complete
duration: 50min
completed: 2026-10-17
actuals:
  tokens: 15500
  tasks: 3
  commits: 5
---

# Phase 3 Plan 05: Routing upgrade for capacity-aware planning Summary

ETA-aware per-horizon fire costs, edge-status blocking, a settlement-to-shelter cost matrix on the shared nearest-horizon rule, lazy k=3 Yen paths on a collapsed DiGraph, BPR congestion with MSA damping, and a load-only graph loader whose only download path is the explicit `scripts/build_osm_graph.py`.

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 | Tracer: horizon costs, cost matrix, snap, k=3 paths and per-edge exposure on the synthetic graph | f3afab1 |
| 2 (RED) | Failing tests for BPR, tag parsing, MSA | 5650329 |
| 2 (GREEN) | congestion.py with guarded `literal_eval` and capacity from OSM tags | b8fd5c5 |
| 3 (RED) | Failing tests for the load-only loader and build script | 338e561 |
| 3 (GREEN) | load_graph, build_graph_for_area, scripts/build_osm_graph.py | 82cef7f |

Tracer gate (auto mode active): the tracer verify (costs, k-paths and the unchanged `test_router.py`) passed after the commit and again inside every later run, so expansion proceeded.

## What changed

- `costs.py`: `apply_horizon_costs` copies the graph once, builds one list of edge geometries and one `shapely.STRtree`, and runs one `query(..., predicate="intersects")` per non-empty perimeter. Each edge gets `edge_status`, `blocked`, `zone_h{1,3,6}` (blocked > p50 > p90 > safe), `fire_mult_h*`, `congested_time`, `vc_ratio` and `cost_h*`. Multipliers are parameters from config. `apply_fire_penalties` and `compute_route` are untouched.
- `router.py`: `snap_points` (haversine cap on `nearest_node_outside`), `route_cost_matrix` (one Dijkstra per origin on time plus one per horizon), `build_route_edges` (cheapest finite unblocked key, integer-key guard), `evaluate_path` (zones, p50/p90/blocked indices, risk score, safe flag).
- `k_paths.py`: `collapse_to_digraph` inserts edges sorted by (u, v, key) and keeps the cheapest finite unblocked parallel edge; `k_shortest_paths` is `islice` over `nx.shortest_simple_paths` with a time budget and a `truncated` flag. A MultiDiGraph is never passed to Yen.
- `congestion.py`: `parse_tag` (only `[`-prefixed strings reach `ast.literal_eval`, malformed input returns `[value]`), `edge_capacity_vph` (lowest-capacity highway class, `_link` factor, lowest lane count, half the lanes rounded up when two-way), `bpr_time`, `edge_flows_vph`, `msa_blend`, `apply_congestion` (refreshes `cost_h*`, returns max v/c).
- `graph.py`: `load_graph` raises `GraphNotBuiltError` naming `uv run python scripts/build_osm_graph.py`, caches the parsed graph under (resolved path, mtime_ns), and adds speeds and travel times only when some edge lacks `travel_time`. `build_graph_for_area` sets the OSMnx cache to `data/osm/cache`, buffers the centre by 10 km in EPSG:32643, keeps the largest strongly connected component and saves atomically.
- `scripts/build_osm_graph.py`: defaults from settings (`pilot_center_lat/lon`, `pilot_buffer_m`, `osm_cache_path`), `--check` (load-only counts and mtime), `--dry-run`, ODbL attribution, exit 2 on any build failure.

## Verification

- `pytest apps packages tests/unit -q`: 291 passed, 1 skipped (baseline 231 passed, 1 skipped; 60 new tests).
- `ruff check apps/agents/routing scripts`: clean. `ruff format --check` clean on the new and changed source files.
- `mypy apps/agents/routing/src`: only the `import-untyped` errors for networkx (types-networkx not installed locally, known). No other errors in src.
- `scripts/build_osm_graph.py --check --out tests/fixtures/osm/bandipur_stub.graphml`: exit 0, `nodes=3 edges=4`, no network.
- `grep "eval(" congestion.py` matches only `literal_eval(`.
- No OSM download was run. Every osmnx download function is monkeypatched to raise in the loader tests, and the build tests mock `ox.graph_from_polygon`. The real build is left to the user (plan 03-12).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] OSMnx speed imputation raises on graphs with no maxspeed tags**
- **Found during:** Task 3 (build test on the synthetic graph)
- **Issue:** `ox.add_edge_speeds` raises `ValueError` when no edge carries a maxspeed tag and no fallback is given. A sparse rural extract could hit the same error in the real build.
- **Fix:** `_with_travel_times` retries once with `fallback=FALLBACK_SPEED_KPH` (30 km/h) only on that error. Normal imputation is unchanged.
- **Files modified:** apps/agents/routing/src/agent_routing/graph.py
- **Commit:** 82cef7f

**2. [Rule 1 - Bug] `msa_blend(prev, new, 1)` kept previous-only keys at 0.0**
- **Found during:** Task 2 GREEN
- **Issue:** The general formula left stale keys in the result at iteration 1, but the behaviour spec says the result equals `new`.
- **Fix:** iteration 1 returns `dict(new)`.
- **Commit:** b8fd5c5

**3. [Rule 1 - Type] `float ** float` is typed Any**
- **Found during:** Task 3 mypy run
- **Fix:** `bpr_time` uses `math.pow`, so `--strict` has no `no-any-return` error.
- **Commit:** 82cef7f

### Notes

- The plan's `max_leg_s` truncation says "exceeds"; the implementation uses `>=` so `max_leg_s=0` is deterministic on Windows' coarse monotonic clock.
- The build script's shared cache folder is passed as an absolute path from the repo root (`cache_folder` keyword), while `build_graph_for_area` defaults to the relative `data/osm/cache` the plan names.

## Known Stubs

None.

## Threat Flags

None. The only new network-capable path is `build_graph_for_area`, which is already covered by T-03-05-01 and is reachable only from the human-run script.

## Self-Check: PASSED

- Files exist: k_paths.py, congestion.py, build_osm_graph.py, and the four new test files.
- Commits exist: f3afab1, 5650329, b8fd5c5, 338e561, 82cef7f.

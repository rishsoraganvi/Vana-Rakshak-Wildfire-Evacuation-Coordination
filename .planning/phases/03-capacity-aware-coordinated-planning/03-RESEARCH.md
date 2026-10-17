# Phase 3: Capacity-Aware Coordinated Planning - Research

**Researched:** 2026-10-17
**Domain:** Deterministic evacuation planning (min-cost-flow shelter matching, k-path routing with fire/congestion costs, validator gate, immutable plan versions, re-plan triggers) inside an existing LangGraph + Postgres + OSMnx Python workspace
**Confidence:** HIGH on stack, API behaviour and in-repo facts (all probed this session); MEDIUM on performance at real-graph scale and on evacuation coefficients (marked ASSUMED); LOW on seed data (cannot be researched, needs the user)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

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

### Claude's Discretion
- How CI exercises k-paths, congestion and capacity without downloading OSM (e.g. a small subgraph
  extracted from the cached real graph and committed as a fixture, or a richer synthetic fixture).
- Exact BPR coefficients, vehicle-equivalent ratio, P50/P90 penalty magnitudes, and the deterministic
  ordering of the fix menu.
- Shared-state versioning mechanics (Redis keys vs Postgres rows) within the TechSpec §5 shape.
- How parallel specialist dispatch is implemented in-process (e.g. `asyncio.gather`) behind the same tool
  interface used in Phase 2.

### Deferred Ideas (OUT OF SCOPE)
- pgvector natural-language shelter lookup ("school with ground near X") — later phase.
- data.gov.in school-directory importer with geocoding and capacity estimation — later phase (Phase 3 uses a curated seed).
- `wind_shift`, `scheduled_refresh` and `manual` re-plan triggers — `manual` with Phase 4 review ("changes requested"), others with Phase 5 workers.
- Background polling worker for automatic re-planning — Phase 5.
- Remaining Phase 2 review warnings (WR-02, WR-04..WR-10) — separate cleanup, not Phase 3 scope.
- "Mark unassigned with reason" as a fix strategy — explicitly rejected for Phase 3 (D-12).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PLAN-01 (parallel half) | Coordinator dispatches eligible specialists in parallel through typed tool contracts | `asyncio.gather` + `asyncio.to_thread` inside ONE dispatch node (LangGraph fan-out needs reducers and a refactor of every node to partial returns, verified); `ToolResult` envelope per Rules §2.5 |
| PLAN-03 | Routes account for blocked/unsafe edges, fire forecast penalties, changing road conditions | Per-horizon edge cost attributes, ETA-aware horizon selection, BPR congestion passes with MSA damping, `road_edge_status` source, lazy Yen k-paths on a collapsed DiGraph |
| PLAN-04 | Match evacuee groups to shelters without exceeding conservative usable capacity | networkx `min_cost_flow` with integer costs, dummy "unassigned" sink for diagnosis, atomic occupancy CAS, V4/V5, Hypothesis property tests |
| PLAN-07 | Conflict resolution with bounded retries; deterministic fallback when LLM unavailable | Pure-Python bounded resolver (≤3), fixed menu order, greedy fallback planner, `failed` plan status (enum migration), Groq strict structured output for optional LLM choice |
| PLAN-08 | Plans immutable, versioned, provenance-linked, freshness-aware, grounded rationale + warnings | Migration 0006 (parent link, validation, provenance, freshness, immutability trigger), canonical material-diff signature, V8 grounding, template rationale |
</phase_requirements>

## Summary

Phase 2 left a sequential 8-node LangGraph pipeline whose "routes" are **cluster-centroid → AOI-boundary-exit** routes, with `settlements_at_risk` hard-coded to `()` [VERIFIED: apps/agents/fire/src/agent_fire/ensemble.py:75 `settlements_at_risk=(),`]. Phase 3 therefore must do more than add matching: it must (1) add a real settlement risk assessment (settlement buffers ∩ P50 forecast perimeters → groups with ETA), (2) add the `shelters`/occupancy tables and seed, (3) re-base routing from "cluster to exit" to "settlement to shelter", and (4) wrap everything in a validator-gated, immutable, versioned plan. No new third-party package is needed: networkx 3.6.1 (3.7 on py3.12), scipy, shapely, osmnx 2.1.1, hypothesis 6.168.3 and langgraph are all already in `uv.lock`.

Three findings change the obvious design. **(a)** `networkx.shortest_simple_paths` raises `NetworkXNotImplemented` on a MultiDiGraph (verified), and on a pure-Python Yen it costs about 0.03–0.2 s per local leg (<10 km) but 1–9 s per long leg (15–20 km, 5–15k nodes), up to 38 s on a 14k-node grid. So k-paths must run on a collapsed `DiGraph`, lazily, only for the legs the matcher actually selected, with one single-source Dijkstra per group providing the cost matrix (≈0.1 s). **(b)** LangGraph parallel branches raise `InvalidUpdateError` if two nodes return the same key, and every existing node returns the whole mutated state, so real graph-level fan-out would force a refactor of every node; an `asyncio.gather` dispatch node (which TechSpec §6.2 literally names) is the right call. **(c)** `load_or_download_graph` silently downloads the whole 140×100 km AOI bbox when the cache file is missing [VERIFIED: apps/agents/routing/src/agent_routing/graph.py:24-35], which contradicts D-05/D-06; it must become load-only, with an explicit build script.

The riskiest non-code items are data, not algorithms: curated shelters/populations cannot be obtained by research (web search found no school or capacity data for Mangala/Hangala/Mulehole) and the real OSM graph must be downloaded by a human-run script. Plan those as `checkpoint:human-action` tasks and make CI independent of both via a deterministic synthetic graph fixture.

**Primary recommendation:** Build a pure-function planning core (`plan_core`: groups → cost matrix → min-cost-flow → BPR passes → validators → ≤3-loop resolver → greedy fallback → plan or `failed`) in the coordinator package, with thin LangGraph nodes and an `asyncio.gather` dispatch node around it, an additive Alembic migration 0006 (shelters, occupancy history, plan columns, `failed` enum value, immutability trigger), and Hypothesis property tests on the pure functions run against a synthetic graph fixture.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Settlement risk assessment / group creation (ETA, priority) | API / Backend (`agent_fire.risk`) | Database (settlements) | Geometry on fire output; Fire agent owns "assess_risk" (TechSpec §7.1) |
| Shelter registry, usable capacity, exclusion near perimeter, occupancy CAS | API / Backend (`agent_shelter`) | Database (`shelters`, `shelter_occupancy`) | Capacity writes must be transactional and re-checked in-transaction (Rules §6) |
| Min-cost-flow matching | API / Backend (`agent_shelter.matching`) | — | Pure function over cost matrix + availability; deterministic |
| Horizon edge costs, SSSP cost matrix, k-paths, BPR | API / Backend (`agent_routing`) | — | Routing agent owns edge cost (TechSpec §7.3) |
| Parallel specialist dispatch | API / Backend (coordinator `dispatch.py`) | — | Cross-domain orchestration belongs to the Coordinator (Rules §2.1) |
| Conflict resolver, fallback planner, plan assembly, diff | API / Backend (coordinator `planning/`) | — | Cross-domain logic; agents must not import each other (Rules §2.10) |
| Validators V1–V8 | API / Backend (coordinator `validators/`) | — | Pure functions over plan + graph + registry ids |
| Plan versioning, immutability, parent link, provenance | Database (`plan_versions` + trigger) | API / Backend (repository) | Immutability enforced in DB plus app layer (Schema.md §8) |
| Shared-state versioning | Database (`incidents.state_version`, `shared_state_snapshots`) | — | Postgres rows; Redis hot-state deferred (see Assumption A11) |
| Trigger detection + debounce | API / Backend (`ingest_worker.triggers` library) | Database (`triggers`) | Library functions + on-demand entry (D-15) |
| LLM fix-menu choice + rationale | API / Backend (`coordinator.llm`) | External (Groq) | Strict JSON schema, enum only; validated identically (D-10) |
| Seed loading | Scripts (`scripts/seed_*.py`) | Database | Idempotent upsert keyed on `external_ref` |
| Browser / CDN | n/a | n/a | No UI in this phase (Phase 5) |

## Standard Stack

### Core (all already locked in `uv.lock`; versions probed in the project venv this session)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| networkx | 3.6.1 (venv, py3.11) / 3.7 (lock marker for py>=3.12) | `min_cost_flow`, `dijkstra`, `shortest_simple_paths` | Already a dependency of agent-routing (`networkx>=3.4`); no OR-Tools needed at this scale [VERIFIED: uv.lock `name = "networkx"` blocks, `ortools` absent] |
| osmnx | 2.1.1 | Explicit one-time graph download, GraphML cache, nearest nodes | Already used by routing [VERIFIED: uv.lock + venv] |
| shapely | 2.1.2 | Perimeter union, edge/perimeter intersects, IoU | Pinned in root pyproject [VERIFIED: pyproject.toml `"shapely==2.1.2"`] |
| pyproj | 3.7.2 (venv) | EPSG:32643 metric area/IoU | Rules §4 requires projected CRS for metrics |
| langgraph | 1.2.13 in venv, 1.2.15 in lock | Coordinator graph | Existing; `uv sync --locked` aligns the venv |
| hypothesis | 6.168.3 | Property tests | Pinned in dev group [VERIFIED: pyproject.toml `"hypothesis==6.168.3"`] |
| sqlalchemy / alembic / psycopg | 2.0.54 / 1.20.0 / 3.3.6 | Persistence, migrations | Existing |
| groq | 1.7.0 | Optional LLM fix-menu choice | Existing adapter |
| scikit-learn | 1.9.1 | Needed by `ox.nearest_nodes` on unprojected graphs (BallTree) | Already installed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| scipy | 1.17.1 | Not required for matching; optional `scipy.sparse.csgraph` if Yen proves too slow on the real graph | Only if profiling on the real graph demands it |
| pydantic | 2.13.5 | `IntegratedPlan`, `ToolResult`, `ValidationResult`, config sub-models | Every boundary |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| networkx `min_cost_flow` | scipy `linear_sum_assignment` / OR-Tools | `linear_sum_assignment` cannot split groups or express capacities; OR-Tools is a new dependency (supply-chain gate) for a ≤30×30 problem. Not worth it. |
| Yen on collapsed DiGraph | edge-penalty alternatives (verified 0.12 s for k=3, but not true k-shortest) | Use only as the documented fallback if real-graph Yen exceeds budget; TechSpec says k-shortest |
| LangGraph `Send`/parallel branches | `asyncio.gather` in one node | Fan-out needs reducers on every shared key and partial-dict returns from all nodes (verified failure otherwise) |
| Redis hot state | Postgres rows only | Redis adds a failure mode and no Phase 3 consumer; events/pubsub arrive in Phase 4/5 |

**Installation:** no new third-party packages. New internal workspace member `apps/agents/shelter` (`agent-shelter`) requires: its `pyproject.toml`, an entry in `[tool.uv.workspace].members` and `[tool.uv.sources]`, a `pythonpath` entry in `[tool.pytest.ini_options]`, then `uv lock` and `uv export` to refresh `uv.lock` and `requirements.txt` (CI runs `uv sync --locked` [VERIFIED: .github/workflows/ci.yml `- run: uv sync --locked`]).

**Version verification:** versions above were read from the project venv (`importlib.metadata`) and `uv.lock` this session, not from memory.

## Package Legitimacy Audit

No new external packages are introduced by this phase. Every library above is already resolved in `uv.lock` and was approved in Phase 1 (ADR-001: "all selected packages use their official PyPI project names" [VERIFIED: docs/adr/ADR-001-phase1-aoi-and-migration-boundary.md]). The only new package is the internal workspace member `agent-shelter` (local path, no registry).

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| (none new) | — | — | — | — | n/a | Approved (already locked) |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none. Do NOT add `ortools`, `igraph` or `python-igraph` in this phase; if profiling later demands igraph (TechSpec §17 Q2) it needs its own legitimacy checkpoint.

## Architecture Patterns

### System Architecture Diagram

```
trigger (new_hotspot | perimeter_change | road_blocked | shelter_capacity_change)
   |  record_trigger(): coalesce within 300 s per (incident, type)  --coalesced--> stop
   v
[ingest_trigger] hotspots of incident (ALL incident triggers, not only latest new_hotspot)
   v
[cluster_hotspots] --> clusters
   v
[weather per cluster] (WR-01: lookup at each centroid; missing weather => fail-closed)
   v
[fire CA per cluster] --> FireSpreadResult per cluster
   v
[assess_risk] union perimeters per horizon -> Footprint; settlements ∩ P50 buffers -> groups (persons, ETA, priority)
   v
[dispatch_specialists]  asyncio.gather(to_thread) with ToolResult envelope + timeout
   |-- shelter.list_candidate_shelters(footprint exclusion, usable - occupancy)
   |-- routing.cost_matrix(groups -> shelter nodes) : 3 horizon cost attrs, 1 SSSP per group, ETA-aware horizon pick
   |-- (vehicle, drone: Phase 6 placeholders, not called)
   v
[collect + capacity-aware assignment loop <= 3 BPR passes]
   |  match_groups_to_shelters (min-cost flow, int costs)  -> legs (group, shelter, persons)
   |  routing.k_paths for selected legs (lazy Yen, DiGraph)  -> edge flows -> BPR -> new costs -> re-match until signature stable
   v
[validate V1..V8] (pure) ----pass----------------------------> [assemble plan v(n+1)]
   | fail
   v
[resolver loop <= 3]  next_path -> rematch(ban pair) -> split  (deterministic order; LLM may pick from enum)
   | still failing
   v
[fallback_planner] greedy, strict-safe, priority order --pass--> [assemble, used_fallback=true]
   | fail
   v
[persist plan status='failed' with validation + reasons, no approvable content]
   v
[rationale] LLM text -> V8 grounding; on failure deterministic template (+ reason recorded)
   v
[persist] one txn: advisory lock per incident, version = max+1, parent_plan_id, state_version CAS, diff,
          material-change check (re-plan only) -> new row or "replan ran, no change" audit row
   v
[write_audit] (flush in finally so failed runs are audited)
```

### Recommended Project Structure
```
apps/agents/routing/src/agent_routing/
├── graph.py         # load_graph (NEVER downloads), cached by (path, mtime); build_graph_from_polygon() explicit
├── costs.py         # extend: horizon cost attrs cost_h1/h3/h6 + blocked mask; edge status overlay
├── k_paths.py       # collapse_to_digraph(), lazy yen(), path ETA/time-dependent evaluation
├── congestion.py    # edge_capacity_vph(), bpr_time(), msa flow averaging
└── router.py        # existing compute_route kept; add route_cost_matrix()
apps/agents/shelter/src/agent_shelter/
├── registry.py      # list_candidate_shelters(), usable_capacity(), update_occupancy() (atomic CAS)
└── matching.py      # match_groups_to_shelters() min-cost flow + diagnostics
apps/agents/fire/src/agent_fire/risk.py     # assess_risk(settlements, fire_results) -> settlements_at_risk (ETA)
apps/coordinator/src/coordinator/
├── dispatch.py      # run_specialists(): gather + to_thread + timeout + ToolResult
├── planning/        # plan_core.py, resolver.py, fallback_planner.py, diff.py, rationale_template.py
├── validators/      # v1..v8 pure functions + run_all()
├── replan.py        # replan_incident() on-demand entry
└── graph.py/runner.py  # thin nodes; flush audit in finally
packages/wildfire_core/src/wildfire_core/
├── schemas/plan.py, tools.py   # IntegratedPlan, ValidationResult, ToolResult envelope
├── schemas/state.py            # extend SharedState to TechSpec §5 sections
├── db/repositories.py          # shelters, plan_versions, state_version bump
└── config.py                   # nested Routing/Shelter/Thresholds sub-models in defaults.yaml
apps/ingest_worker/src/ingest_worker/triggers.py  # + detect_* and record_trigger()
scripts/build_osm_graph.py, scripts/seed_shelters.py, scripts/seed_settlements.py
config/seed/shelters_bandipur.csv, config/seed/settlements_bandipur.csv
tests/fixtures/graphs.py                          # deterministic synthetic MultiDiGraph builder
```
This follows `generatedPlan/FolderStructure.md` (shelter agent `registry.py`/`matching.py`; routing `k_paths.py`/`congestion.py`; coordinator `validators/`, `fallback_planner.py`).

### Pattern 1: Min-cost-flow matching with a diagnostic "unassigned" sink
**What:** source→group (cap = persons) → shelter (cap = persons, cost = ceil(route seconds)) → sink (cap = usable − occupancy). A group splits across shelters with no extra code; an `U` node with a prohibitive cost isolates exactly which group cannot be placed instead of the opaque `NetworkXUnfeasible` (D-12 needs "naming the group").
**When to use:** every match call; the resolver and fallback reuse it with banned pairs.
**Example:**
```python
# Source: prototype run in this session (300 Hypothesis examples passed, ~10 s); networkx docs for
# min_cost_flow ("not guaranteed to work if edge weights or demands are floating point")
import math
import networkx as nx

def match(groups: dict[str, int], avail: dict[str, int],
          cost_s: dict[tuple[str, str], float | None], *, banned=frozenset()):
    total = sum(groups.values())
    finite = [c for k, c in cost_s.items() if c is not None and math.isfinite(c) and k not in banned]
    big = (len(groups) + len(avail) + 1) * (round(max(finite, default=0) * 10) + 1) + 1
    G = nx.DiGraph()
    G.add_node("S", demand=-total); G.add_node("T", demand=total)
    G.add_edge("U", "T", capacity=total, weight=0)
    for g, p in sorted(groups.items()):
        G.add_edge("S", ("g", g), capacity=p, weight=0)
        G.add_edge(("g", g), "U", capacity=p, weight=big)        # diagnostic sink
    for s, a in sorted(avail.items()):
        G.add_edge(("s", s), "T", capacity=max(0, a), weight=0)
    for (g, s), c in sorted(cost_s.items()):
        if c is None or not math.isfinite(c) or (g, s) in banned:
            continue
        G.add_edge(("g", g), ("s", s), capacity=groups[g], weight=round(c * 10))  # 0.1 s ints
    flow = nx.min_cost_flow(G)
    legs = {(g, n[1]): f for g in groups for n, f in flow[("g", g)].items() if f > 0 and n != "U"}
    unassigned = {g: flow[("g", g)]["U"] for g in groups if flow[("g", g)].get("U", 0) > 0}
    return legs, unassigned
```
Determinism: sorted insertion made two identical calls return identical dicts (verified).

### Pattern 2: k-paths on a collapsed DiGraph, lazy, only for selected legs
**What:** collapse parallel edges to the cheapest `(u, v)` remembering the key, run one single-source Dijkstra per group for the cost matrix, then take `itertools.islice(nx.shortest_simple_paths(D, s, t, weight="w"), 3)` only for legs the matcher selected, and only pull paths 2 and 3 when the resolver asks.
**Why:** `shortest_simple_paths` raises `NetworkXNotImplemented: not implemented for multigraph type` on `MultiDiGraph` (verified). Measured Yen k=3 on random Delaunay road-like graphs of 8k nodes: 14-hop legs 0.03 s, 22-hop 0.12 s, 49-hop 1.25 s (max 2.57 s); single-source Dijkstra to all targets ≈ 0.1 s. A 14,400-node grid took 38 s for one corner-to-corner leg, so never run Yen over all group×shelter pairs.
**Example:**
```python
# Source: prototype in session; networkx docs: weight function may return None to hide edges
def collapse_to_digraph(M, weight):
    D = nx.DiGraph(); D.add_nodes_from(M.nodes(data=True))
    for u, v, k, d in M.edges(keys=True, data=True):
        w = d[weight]
        if not math.isfinite(w):           # blocked: hide the edge (ETA-aware cost may be inf)
            continue
        if not D.has_edge(u, v) or w < D[u][v]["w"]:
            D.add_edge(u, v, w=w, key=k)
    return D
```
Reuse the existing two-phase "hide blocked, then least-blocked fallback" idea only for the single best route; k-paths use the strict (unblocked) graph and return fewer than 3 paths when fewer exist.

### Pattern 3: ETA-aware horizon costs (D-07) without a time-dependent Dijkstra
**What:** precompute three cost attributes per edge (`cost_h1`, `cost_h3`, `cost_h6`): blocked (∞) if the edge geometry intersects the union current perimeter, else `travel_time × p50_mult` if it intersects `p50_{h}`, else `× p90_mult` if it intersects `p90_{h}`, else `travel_time`. For a (group, shelter) pair choose the horizon nearest the free-flow ETA (ties go to the later horizon, i.e. conservative). Penalties are monotone in horizon (burned area is monotone), so the per-pair choice is consistent. V3 re-evaluates the final route edge by edge using cumulative congested arrival time and the same nearest-horizon rule, so the router never emits a plan its own validator rejects.
**Cost note:** each attribute is one pass of perimeter intersection over all edges (use `shapely.STRtree.query`/vectorised `shapely.intersects` instead of a Python loop at 20k+ edges; the current `apply_fire_penalties` loops per edge and `graph.copy()`s each call, so copy once per plan run, not once per congestion pass).

### Pattern 4: BPR with method-of-successive-averages (D-08)
`t = t0·(1 + α·(v/c)^β)`, α = 0.15, β = 4 [CITED: widely used defaults, Sheffi 1985 as cited in arxiv.org/pdf/2211.13514; Spiess 1990 notes β 2–12 in practice]. `v` (veh/h) = Σ persons on the directed edge ÷ `persons_per_vehicle` ÷ `evac_window_h`. Capacity `c` from highway tag × per-direction lanes (see table in Assumptions). Passes: pass 0 free flow → match+route → flows; pass i blends `v = (1 − 1/i)·v_prev + (1/i)·v_new` to damp oscillation; stop at `congestion_passes` (config, default 3) or when the leg signature (sorted `(group, shelter, persons, path_nodes)`) is unchanged. Record `max_vc_ratio` and `congestion_passes_used` in the plan and warn when v/c > 1.0. Convergence in 2–3 passes is **not guaranteed**; the bound is a cap, not a convergence proof.
Cited context for capacities: consultants model about 950–1,000 vehicles/h per lane for evacuations versus 1,700–2,000 normal [CITED: portolavalley.net/home/showpublisheddocument/14983 via search summary].

### Pattern 5: Bounded resolver, fixed menu, optional LLM choice (D-09/D-10)
Implement as a plain bounded `for loop in range(3)` in a library function (testable with Hypothesis without LangGraph; avoids LangGraph's default recursion limit). Each loop runs the validators, collects violations per leg, applies one menu strategy, rebuilds, and re-validates. Recommended deterministic order: **next_path → rematch → split** (cheapest/least disruptive first; congestion-induced V3 violations are what `split` fixes because it lowers v/c and ETA). `rematch` = ban the violating `(group, shelter)` pair and re-run the flow (which may split automatically). A strategy that has nothing to do (e.g. no 2nd path) still consumes its loop. LLM mode: Groq `response_format={"type":"json_schema", "json_schema":{"name":..., "strict": True, "schema": {...enum of the 3 strategies...}}}` is supported with strict constrained decoding on `openai/gpt-oss-20b` (the configured model) [CITED: console.groq.com/docs/structured-outputs]; streaming/tool-use are not supported together with it. The LLM returns only the enum; targets (which leg, which shelter) are always chosen deterministically, so it can never invent IDs. Validate with Pydantic, one repair retry, then deterministic order (Rules §3).
`fallback_planner` must be a *different* algorithm from the flow so it can succeed where the flow loop failed: greedy by priority then persons desc, cheapest strictly-safe `(shelter, path)` with remaining usable capacity, splitting greedily across shelters. It sets `used_fallback=true`.

### Pattern 6: Parallel dispatch (PLAN-01)
One node `dispatch_specialists` calls `run_specialists({"shelters": ..., "costs": ...})` which does `asyncio.gather(*(asyncio.wait_for(asyncio.to_thread(fn), timeout)))`, wraps every result in `ToolResult(ok, data | error{code,message,retryable})` (Rules §2.5), and records one audit entry per specialist. Guard `asyncio.run` for an already-running loop (run in a worker thread) so FastAPI callers do not crash. Verified: three 0.2 s sleeps through `asyncio.run(gather(to_thread))` inside a LangGraph node finished in 0.21 s. Non-critical specialists (vehicle/drone) may time out; routing or shelter failure marks the plan `failed`/incomplete (TechSpec §12).

### Pattern 7: Immutable versioned plans (PLAN-08)
Additive migration `0006`: see Code Examples. Version assignment under `pg_advisory_xact_lock(hashtext(incident_id::text))` (the existing `MAX(version)+1` read at coordinator/graph.py:485-491 races; only the unique constraint protects it). Optimistic shared-state check: the plan records the `incidents.state_version` it was built against; persist re-reads it inside the transaction and aborts (bounded retry) if it moved. Material change signature (D-16), excluding volatile fields (`plan_id`, `route_id` uuid4 defaults, `created_at`, rationale text, warnings, ETA noise): sorted `(group_id, shelter_id, persons)` assignments + per-group route node paths + `{validator_id: status}`. Compare signatures; equal ⇒ write an audit row `replan_no_change` and set `triggers.handled_run_id`, no new version. Different ⇒ new version with `parent_plan_id`, `diff` jsonb, and the previous non-terminal version set to `superseded` (a status-only update the trigger allows).

### Anti-Patterns to Avoid
- **Running Yen for all group×shelter pairs** (minutes of CPU); use SSSP for costs, Yen only for selected legs.
- **Passing a MultiDiGraph to `shortest_simple_paths`** (raises).
- **Parallel LangGraph branches that return the whole state** (`InvalidUpdateError: Can receive only one value per step`, verified).
- **Floating-point weights in `min_cost_flow`** (networkx documents it is "not guaranteed to work"); scale to ints.
- **Implicit OSM download at plan time** (current loader fetches the entire AOI bbox).
- **Mutating `state["audit_entries"]` / `state["warnings"]` in place in parallel code** (shared mutable lists).
- **Using `uuid4` cluster ids for diffs or group ids** (`HotspotCluster.cluster_id` defaults to a fresh uuid per run [VERIFIED: packages/wildfire_core/src/wildfire_core/schemas/phase2.py:13 `cluster_id: str = Field(default_factory=lambda: str(uuid.uuid4()))`]); groups are keyed on `settlements.id`.
- **Letting the LLM name a shelter, group or number** (S4); only an enum.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Assignment with splits and capacities | Greedy/bin-packing as the primary matcher | `nx.min_cost_flow` (integer weights) | Optimal, splits naturally; greedy is only the fallback planner |
| k simple shortest paths | Own Yen | `nx.shortest_simple_paths` on a DiGraph, lazy | Correctness of loopless k-paths; fix the scale problem by laziness, not by rewriting |
| Single-source costs | Custom Dijkstra for the cost matrix | `nx.single_source_dijkstra_path_length` | ~0.1 s at 8k nodes |
| Nearest road node | KD-tree code | `ox.nearest_nodes` (BallTree, scikit-learn present) | Already used in `router.py` |
| Edge/perimeter exposure at scale | Python per-edge loops | `shapely.STRtree` / vectorised `shapely.intersects` | 20k+ edges × 3 horizons |
| Atomic occupancy updates | Read-modify-write in Python | `UPDATE shelters SET occupancy = occupancy + :d WHERE id=:id AND occupancy + :d BETWEEN 0 AND :usable RETURNING occupancy` | Double-booking safety in the DB (Rules §6) |
| Trigger coalescing lock | Process-local dict | `pg_advisory_xact_lock(hashtext(incident||type))` + `triggers.coalesced_into` | Survives multiple workers; no Redis needed in Phase 3 |
| GraphML tag parsing (`highway`/`lanes` can load as `"['a','b']"`) | Regex | `ast.literal_eval` guarded helper | `ox.load_graphml` only converts a fixed dtype list; `highway`, `lanes`, `maxspeed` stay strings [VERIFIED: osmnx/io.py default dtypes read in session] |
| Property-based generation | Hand-written fuzzers | Hypothesis `@st.composite` | Already pinned and required by Rules §8 |

**Key insight:** every algorithm here is textbook and already in networkx/shapely; the real engineering risk is scale (Yen), data correctness (capacities, populations), and the atomicity/immutability of what gets persisted.

## Common Pitfalls

### Pitfall 1: `load_or_download_graph` downloads the whole AOI
**What goes wrong:** with no cache file, a plan run triggers an Overpass download of the 140×100 km bbox from inside the coordinator.
**Why:** current loader falls through to `ox.graph_from_bbox` [VERIFIED: apps/agents/routing/src/agent_routing/graph.py:28-34 `graph = ox.graph_from_bbox( (west, south, east, north), network_type=network_type, )`].
**How to avoid:** make runtime loading load-only (raise `FileNotFoundError` with the exact build command); add `scripts/build_osm_graph.py` using `graph_from_polygon` of the union of 10 km buffers (buffer in EPSG:32643, back to 4326); set `ox.settings.cache_folder = "data/osm/cache"` (default is `./cache`, which would pollute the repo [VERIFIED: ox.settings.cache_folder → `./cache`]); add speeds and travel times before `save_graphml`; cache the loaded graph in-process keyed by `(path, mtime)`.
**Warning signs:** test or demo runs that take minutes or create `./cache`.

### Pitfall 2: `.gitignore` does not ignore `data/` or `cache/`
**What goes wrong:** the cached graph (tens of MB) is committed.
**Why:** `.gitignore` lists `.env .venv/ __pycache__/ ... *.egg-info/ GUIDE.md` only [VERIFIED: .gitignore lines read]. D-05 says "git-ignored".
**How to avoid:** Wave 0 task adds `data/` and `cache/` to `.gitignore` (Rules §7: large data never in git).

### Pitfall 3: Phase 2 never produces `settlements_at_risk`
**What goes wrong:** D-02 ("one group per at-risk settlement") has no producer, so Phase 3 would plan zero groups.
**How to avoid:** implement `agent_fire.risk.assess_risk` in this phase and seed settlements; group rule = settlement buffer (`buffer_m`, default 2000 [VERIFIED: 0002_monitoring.py `buffer_m integer NOT NULL DEFAULT 2000`]) intersects a P50 horizon (matches the `risk_threshold` trigger, TechSpec §9); ETA = earliest including horizon × 60 (interpolation optional); priority by horizon bucket.

### Pitfall 4: Per-cluster weather (WR-01) reorders the graph
**What goes wrong:** `run_weather` currently runs before clustering and keeps one `weather_snapshot` [VERIFIED: apps/coordinator/src/coordinator/runner.py edges `run_weather → cluster_hotspots → run_fire_ca`; graph.py:198-203 mean hotspot lat/lon].
**How to avoid:** cluster first, then look up weather at each `centroid_lat/lon`; state becomes `weather_by_cluster: dict[cluster_id, WeatherSnapshot]`; `CoordinatorPlan.weather_snapshot` (singular) and `generate_rationale(weather)` need a per-cluster form; plan freshness needs an always-present age (WeatherSnapshot only carries `stale_age_min` when stale, `extra="forbid"` so add `age_min`). A cluster with no weather must not silently drop out of V2/V3 (an unsimulated fire is an unblocked fire): recommend fail-closed (see Open Question 4).

### Pitfall 5: WR-03 has four fix points, not one
**What goes wrong:** fixing only `is_forecast` still leaves live incidents unmatched.
**Why:** (1) parser hard-codes `is_forecast=True` [VERIFIED: parser.py:47]; (2) `origin: str = "replay"` default [VERIFIED: parser.py:15]; (3) `record_new_hotspot_trigger` inserts every incident with origin `'replay'` [VERIFIED: triggers.py:57 `VALUES (:code, 'open', 'replay', :summary)`]; (4) the scoped query requires `is_forecast IS false` and `origin = incident origin`, and no live weather fetcher exists (only parser/ingest service; callers are tests).
**How to avoid:** `is_forecast = valid_time > issued_at`, make `origin` a required keyword, pass hotspot origin into the incident insert, and add an integration test that runs `parse_open_meteo` → `ingest_weather` → `get_weather_snapshot`. The current fixture has all times after `issued_at` (07:00/08:00 vs 06:00), so add an observation fixture with times ≤ issued_at.

### Pitfall 6: `ALTER TYPE plan_status ADD VALUE 'failed'` rules
Allowed inside a transaction on PG16 but "the new value cannot be used until after the transaction has been committed" [CITED: postgresql.org/docs/16/sql-altertype.html]. Alembic wraps the migration in one transaction, so 0006 must not reference `'failed'` in an index, CHECK or data insert. There is no DROP VALUE; downgrade is forward-only (document it). Use `ADD VALUE IF NOT EXISTS`. Note `CoordinatorPlan.status` is already `Literal["draft", "failed"]` [VERIFIED: phase2.py:123 `status: Literal["draft", "failed"] = "draft"`] and the DB enum currently lacks `failed` [VERIFIED: 0005_phase2_plan_versions.py:14-15 `CREATE TYPE plan_status AS ENUM ('draft', 'pending_review', 'approved', 'rejected', 'superseded');`].

### Pitfall 7: CONTEXT.md names the trigger enum wrongly
CONTEXT says `incident_trigger_type`; the real type is `trigger_type` [VERIFIED: 0003_incidents_and_triggers.py:16-18 `CREATE TYPE trigger_type AS ENUM ('new_hotspot', 'risk_threshold', 'wind_shift', 'perimeter_change', 'road_blocked', 'shelter_capacity_change', 'scheduled_refresh', 'manual');`]. All three Phase 3 trigger values already exist; no enum migration is needed for triggers.

### Pitfall 8: Existing trigger debounce is not per-incident and always creates an incident
`record_new_hotspot_trigger` debounces on `type = 'new_hotspot' AND detected_at >= cutoff` with no incident filter and inserts a new incident every call [VERIFIED: apps/ingest_worker/src/ingest_worker/triggers.py:40-75 read]. Do not copy it: the new `record_trigger(engine, incident_id, type, details, detected_at, *, debounce_s)` must scope by `(incident_id, type)`, anchor the window on the first uncoalesced trigger, serialise with an advisory lock, and take time from the injected `Clock` (Rules §2.9).

### Pitfall 9: Offline coordinator tests match SQL by substring and raise on anything unknown
`test_pipeline_offline.py` `FakeConnection.execute` raises `AssertionError("Unexpected SQL: ...")` for unmatched statements [VERIFIED: apps/coordinator/tests/test_pipeline_offline.py read]. Any new SQL in graph nodes breaks it. Put all new DB access behind a repository interface injected into nodes so offline tests fake functions, not SQL strings.

### Pitfall 10: CI runs only `tests/unit`
[VERIFIED: .github/workflows/ci.yml `- run: uv run pytest tests/unit -q`]. Package-local suites under `apps/` and `packages/` are not CI targets (the 104-test offline run used `pytest apps packages tests/unit`, which passed 104, skipped 1 this session). Either place the new property tests under `tests/unit/` or extend the CI command; otherwise the exit criterion "property tests prove invariants" is unenforced.

### Pitfall 11: Phase 2 tests/API pin the `draft` status
Integration test asserts `plan["status"] == "draft"` and `replay_demo._fetch_draft` filters `status = 'draft'`; the API serves plans where `p.status IN ('draft', 'pending_review')` [VERIFIED: apps/api_gateway/src/api_gateway/routers/incidents.py:168]. If validated plans become `pending_review` (recommended), update those; a `failed` plan is invisible to the API until its query includes `'failed'` (TechSpec §12 says failures are shown to the reviewer).

### Pitfall 12: A group whose origin is inside the current perimeter
Under D-12 this fails the entire plan (V2 cannot pass). That is the locked strict stance; surface the group and reason, and consider a warning at spec level to the user (Open Question 6).

### Pitfall 13: Real-graph timing is unverified
Yen timings above come from synthetic Delaunay/grid graphs, not the real Bandipur network (not downloadable in this research). Add a timing guard test/log and a configurable `k_paths_max_leg_s` budget; if exceeded fall back to the penalty-alternatives method and flag in warnings.

### Pitfall 14: LangGraph version drift and recursion limit
The venv has langgraph 1.2.13/networkx 3.6.1 on Python 3.11.15 while `uv.lock` has langgraph 1.2.15 and networkx 3.7 for py≥3.12 (CI uses 3.12). Code must work on both networkx 3.6/3.7; run `uv sync --locked` before the final test pass. Keep the conflict loop out of LangGraph cycles (default step limit applies).

### Pitfall 15: Audit rows are only written at the very end
`write_audit` flushes after all nodes [VERIFIED: apps/coordinator/src/coordinator/graph.py:529-543], so an exception drops every audit row (Phase 2 MD-06/WR-10). Phase 3 persists `failed` plans and runs re-plans, so wrap the run in `try/finally` and flush audit entries (and map `agent` to `traffic_routing`/`shelter` where the node is a specialist; `agent_name` already has those values [VERIFIED: 0004_shared_state_audit.py:14-16]).

## Code Examples

### Migration 0006 (additive; sketch)
```python
# Source: derived from existing 0005 style + PostgreSQL docs
def upgrade() -> None:
    op.execute("ALTER TYPE plan_status ADD VALUE IF NOT EXISTS 'failed'")   # do not USE it in this txn
    op.execute("""
    CREATE TABLE shelters (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        external_ref text NOT NULL UNIQUE,              -- seed idempotency key
        name text NOT NULL,
        kind text NOT NULL,                             -- school | community_hall | other
        geom geometry(Point, 4326) NOT NULL,
        nearest_node bigint,                            -- optional; graph-version dependent
        capacity integer NOT NULL CHECK (capacity > 0),
        usable_factor numeric(3,2),                     -- NULL = config default 0.60
        capacity_source text NOT NULL,                  -- S9: visible source
        occupancy integer NOT NULL DEFAULT 0 CHECK (occupancy >= 0),
        is_active boolean NOT NULL DEFAULT true,
        contact text,
        metadata jsonb NOT NULL DEFAULT '{}'::jsonb
    );
    CREATE INDEX ix_shelters_geom ON shelters USING gist (geom);
    CREATE TABLE shelter_occupancy (                    -- append-only history
        id bigserial PRIMARY KEY,
        shelter_id uuid NOT NULL REFERENCES shelters(id),
        incident_id uuid REFERENCES incidents(id),
        occupancy integer NOT NULL CHECK (occupancy >= 0),
        recorded_at timestamptz NOT NULL DEFAULT now(),
        source text NOT NULL DEFAULT 'plan'
    );
    CREATE INDEX ix_shelter_occupancy_shelter ON shelter_occupancy (shelter_id, recorded_at DESC);
    ALTER TABLE plan_versions
        ADD COLUMN parent_plan_id uuid REFERENCES plan_versions(id),
        ADD COLUMN trigger_id uuid REFERENCES triggers(id),
        ADD COLUMN state_version integer,
        ADD COLUMN validation jsonb NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN freshness jsonb NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN diff jsonb,
        ADD COLUMN used_fallback boolean NOT NULL DEFAULT false,
        ADD COLUMN valid_until timestamptz;
    CREATE INDEX ix_plan_versions_parent ON plan_versions (parent_plan_id);
    CREATE FUNCTION plan_versions_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.plan_data IS DISTINCT FROM OLD.plan_data
         OR NEW.rationale_md IS DISTINCT FROM OLD.rationale_md
         OR NEW.validation IS DISTINCT FROM OLD.validation
         OR NEW.provenance IS DISTINCT FROM OLD.provenance
         OR NEW.parent_plan_id IS DISTINCT FROM OLD.parent_plan_id
         OR NEW.version <> OLD.version OR NEW.incident_id <> OLD.incident_id THEN
        RAISE EXCEPTION 'plan_versions rows are immutable except status';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_plan_versions_immutable BEFORE UPDATE ON plan_versions
        FOR EACH ROW EXECUTE FUNCTION plan_versions_immutable();
    """)
```
Add a minimal `road_edge_status` table only if the user confirms Open Question 3; otherwise edge statuses are an explicit input to the routing/validator functions in Phase 3.

### Atomic occupancy update (`update_occupancy`)
```python
# Rules §6: re-check capacity inside the transaction; CAS in one statement
row = conn.execute(text("""
    UPDATE shelters SET occupancy = occupancy + :delta
    WHERE id = :id AND is_active
      AND occupancy + :delta BETWEEN 0 AND floor(capacity * COALESCE(usable_factor, :default_factor))
    RETURNING occupancy"""), {...}).first()
if row is None: raise CapacityExceeded(...)       # no partial write; history row only on success
conn.execute(text("INSERT INTO shelter_occupancy (shelter_id, incident_id, occupancy, source) VALUES (...)"))
```

### Perimeter-change trigger (TechSpec §9: IoU < 0.8 or growth > 25%)
```python
# Source: shapely + pyproj; metric CRS per Rules §4 (EPSG:32643 for this region)
to_utm = pyproj.Transformer.from_crs(4326, 32643, always_xy=True).transform
a, b = shp_transform(to_utm, prev), shp_transform(to_utm, new)
union = a.union(b).area
iou = (a.intersection(b).area / union) if union > 0 else 1.0
growth = ((b.area - a.area) / a.area) if a.area > 0 else (float("inf") if b.area > 0 else 0.0)
crossed = iou < 0.8 or growth > 0.25            # thresholds from config, not literals
```

### Trigger coalescing (per incident+type, anchored on the first uncoalesced trigger)
```sql
SELECT pg_advisory_xact_lock(hashtext(:incident_id || ':' || :type));
SELECT id FROM triggers
 WHERE incident_id = :incident_id AND type = :type AND coalesced_into IS NULL
   AND detected_at > :now - make_interval(secs => :debounce_s)
 ORDER BY detected_at LIMIT 1;           -- leader; if found insert with coalesced_into = leader.id
```

### V8 grounding sketch (strict, within rounding)
```python
NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
def number_grounded(token: str, facts: set[float]) -> bool:
    d = len(token.split(".")[1]) if "." in token else 0
    x = float(token)
    return any(abs(f - x) <= 0.5 * 10 ** (-d) + 1e-9 for f in facts)
# facts = every numeric leaf of the plan + derived counts (len(groups), len(routes), total persons,
# horizons 1/3/6 and their minute values). Strip markdown list markers and heading numbers before scanning.
# Entities: any UUID not in the plan ids fails; any registry name (ALL shelter/settlement names, not just
# those in the plan) that appears in the text but is not in the plan fails. Failure -> template rationale.
```
V8 alone does not block (D-13): store `validation.V8 = {status: "replaced", reason: ...}`; the template is built from plan data and must pass V8 by construction (add a Hypothesis property for this).

### Hypothesis strategy (verified shape)
```python
@st.composite
def instances(draw):
    groups = {f"g{i}": draw(st.integers(1, 500)) for i in range(draw(st.integers(1, 8)))}
    caps = {f"s{j}": draw(st.integers(0, 600)) for j in range(draw(st.integers(1, 8)))}
    occ = {s: draw(st.integers(0, c)) for s, c in caps.items()}
    factor = draw(st.sampled_from([0.4, 0.6, 0.8]))
    avail = {s: max(0, math.floor(c * factor) - occ[s]) for s, c in caps.items()}
    cost = {(g, s): draw(st.floats(1, 5000, allow_nan=False)) for g in groups for s in caps}
    return groups, avail, cost
@settings(max_examples=200, deadline=None)
@given(instances())
def test_capacity_and_conservation(inst): ...   # Σ assigned <= avail; assigned+unassigned == persons
```
Register a `ci` profile (`derandomize=True`) in a `conftest.py` so CI is deterministic. The prototype passed 300 examples in ~10 s [VERIFIED: local run].

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Phase 2: cluster centroid → AOI exit, all-or-nothing blocked fallback | Settlement → shelter with per-horizon costs and BPR | Phase 3 | Routing re-based; `RouteResult` gains shelter/ETA/flags |
| One weather snapshot at mean hotspot | Per-cluster weather | WR-01 | State/plan/rationale signatures change |
| `draft` plans, version = MAX+1 | `pending_review`/`failed`, advisory-locked version, parent link, immutability trigger | Phase 3 | Phase 4 consumes these |
| `shortest_simple_paths` over everything | SSSP + lazy Yen on collapsed DiGraph | this research | Avoids multi-second legs |

**Deprecated/outdated:** `plan_data` key `fire_result` (singular) vs `fire_results` — add `plan_schema_version` (Phase 2 IN-06) so readers handle both; `route_fire_penalty_near` becomes the P50 multiplier (or is superseded by `route_fire_penalty_p50` / `_p90`).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Lane capacity (veh/h per direction-lane, evacuation-conservative): motorway 1800, trunk 1600, primary 1400, secondary 1100, tertiary 900, unclassified/residential/service/track 600, `*_link` ×0.8; default 1 lane per direction when `lanes` missing, `ceil(lanes/2)` for two-way roads | Pattern 4 | Mis-sized bottlenecks; user should confirm or tune in config |
| A2 | `persons_per_vehicle = 4.0`, `evac_window_h = 2.0` (config) | Pattern 4 | Over/under-estimates congestion |
| A3 | Penalty multipliers: P50 ×10, P90 ×3 (config; blocked = ∞) | Pattern 3 | Routes too timid/too bold near fire; safety-relevant, confirm |
| A4 | V3 and routing both use "nearest horizon to per-edge cumulative arrival time, ties to the later horizon" | Pattern 3 | If the user wants "floor"/"ceil" semantics, V3 changes |
| A5 | Validated plans are stored `pending_review`; `draft` is no longer written (Phase 4 will transition from it) | Pattern 7, Pitfall 11 | Phase 4 may prefer `draft` until AwaitReview; test/API churn either way |
| A6 | Shelter exclusion: within 1 km of `P90_6h ∪ current` (config), excluded from candidates | Open Q 5 | Too wide ⇒ no feasible shelters ⇒ `failed` plan; safety-relevant |
| A7 | At-risk group = settlement buffer intersects any P50 horizon (≤6 h); P90-only settlements get a warning, not a group | Pitfall 3 | Under/over-evacuation |
| A8 | `shelter_capacity_change` tolerance = occupancy delta ≥ 10 % of usable or shelter deactivated (config) | Re-plan | TechSpec leaves "tolerance" undefined |
| A9 | ETA = earliest including horizon in minutes (no interpolation) | Pitfall 3 | Coarser ETA than TechSpec "interpolated" |
| A10 | Edge-status source: minimal `road_edge_status` table (keys `osm_u, osm_v, osm_key`, status, source, valid_from/to) | Open Q 3 | Without it `road_blocked` has no producer except function input |
| A11 | Shared state = Postgres rows only (`incidents.state_version` + `shared_state_snapshots`), no Redis in Phase 3 | Responsibility Map | ADR-6 hybrid deferred; Phase 5 adds pub/sub |
| A12 | Resolver order next_path → rematch → split | Pattern 5 | Discretionary; only affects which violations clear first |
| A13 | A cluster with no weather ⇒ fail-closed (no approvable plan) | Pitfall 4 | Alternative: conservative hotspot buffer; changes safety behaviour |
| A14 | Yen timings are from synthetic graphs of 5–15k nodes | Pattern 2 | Real Bandipur graph may be faster or slower |
| A15 | CI should also run `apps` and `packages` tests (or new tests live in `tests/unit`) | Pitfall 10 | Property tests silently unenforced |
| A16 | Fallback planner = greedy strictly-safe by priority/persons | Pattern 5 | Discretionary algorithm choice |
| A17 | Real graph size 5–20k nodes for pilot + 10 km buffer | Pitfall 13 | Affects budgets |
| A18 | Seed shelters/settlements must be supplied/verified by the user; `capacity_source` marks them as estimates (S9) | Open Q 1 | Fabricated capacities would be unsafe |

## Open Questions

1. **Curated shelters and settlements (needs user input).**
   - What we know: schema, CSV columns and loader are specified; D-01 wants ~15–30 schools/halls and D-02 settlement populations. Web search found no school or capacity data for Mangala/Hangala/Mulehole/Bandipur; the only populations found: Hangala 5,597 (2001 census) [CITED: en.wikipedia.org/wiki/Hangala], Bandipura village 1,553 (2011) [CITED: censusindia2011.com/karnataka/chamarajanagar/gundlupet/bandipura-population.html]. A UDISE+ record lists enrolment, not shelter capacity.
   - What's unclear: the actual pilot settlements, shelter names/coordinates, capacity estimates.
   - Recommendation: user supplies `config/seed/shelters_bandipur.csv` (`external_ref,name,kind,lat,lon,capacity,capacity_source,notes`) and `settlements_bandipur.csv` (`name,kind,population,pop_source,lat,lon,buffer_m`), or authorizes an Overpass candidate-extraction helper script they run once (`amenity=school|community_centre`, `place=village|hamlet`) followed by manual curation. Plan a `checkpoint:human-action`; ship a clearly labelled synthetic seed (`capacity_source='synthetic_test'`, `is_simulated`) so CI and demos work meanwhile.
2. **Run the real OSM download.** The executor cannot assume network; the user runs `scripts/build_osm_graph.py` once (Overpass rate limits apply; `ox.settings.requests_timeout` is 180 s). Human-action checkpoint; CI never depends on it.
3. **Edge-status producer for `road_blocked`.** Schema.md defines `road_edges`/`road_edge_status` but no table exists. Recommend a minimal `road_edge_status` table in 0006 (keys by `osm_u, osm_v, osm_key`; no `users` FK since no users table exists). Confirm, or accept function-input-only.
4. **Cluster without weather.** Recommend fail-closed with a `failed` record naming the cluster; alternatives (skip with a conservative hotspot buffer) change safety behaviour.
5. **Shelter exclusion geometry** (A6): confirm product and buffer; safety-relevant (Rules §12.9).
6. **Strict D-12 and burning settlements:** a settlement already inside the current perimeter fails the entire plan. Confirm this is intended.
7. **Plan status naming** (A5): confirm validated plans are `pending_review` now.
8. **Does the pilot incident hotspot (demo at 11.72, 76.64) fall near the chosen settlements?** The demo and stub graph are at that point; the real pilot cluster must be confirmed so seeds and graph buffer centre on it.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python venv (`.venv\Scripts\python.exe`) | all | yes | 3.11.15 | CI uses 3.12 |
| uv | lock/sync, new workspace member | yes | 0.12.5 | — |
| networkx / osmnx / shapely / pyproj / sklearn / hypothesis / langgraph / scipy | core | yes | 3.6.1 / 2.1.1 / 2.1.2 / 3.7.2 / 1.9.1 / 6.168.3 / 1.2.13 / 1.17.1 | `uv sync --locked` aligns to lock |
| Docker CLI | live compose tests | client yes (29.6.1); daemon not confirmed | — | live tests stay `COMPOSE_SMOKE=1` gated and manual |
| PostgreSQL 16 + PostGIS 3.5 + pgvector 0.8.6 | migrations/integration | image pinned in `infra/docker/postgres/Dockerfile`; not started here | 16 | offline tests use fakes; `alembic upgrade head --sql` as offline migration check |
| Network / Overpass API | one-time OSM build | not assumed | — | synthetic fixture for CI; human-run build |
| Groq API key | LLM paths | not read (`.env` is off limits) | — | `llm_enabled: false` default; deterministic resolver/template |
| OR-Tools / igraph | not needed | absent (ortools not in lock) | — | do not add |

**Missing dependencies with no fallback:** curated shelter/settlement data (user), real OSM graph (human-run script). Both only block the real-data demo, not CI or unit/property tests.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 + hypothesis 6.168.3 |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, pythonpath list must gain `apps/agents/shelter/src`) |
| Quick run command | `.venv\Scripts\python.exe -m pytest apps/agents/shelter apps/agents/routing apps/coordinator tests/unit -q -x` |
| Full suite command | `.venv\Scripts\python.exe -m pytest apps packages tests/unit -q` (104 passed, 1 skipped at start of Phase 3) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PLAN-04 | Σ assigned ≤ usable − occupancy for every shelter; assigned + unassigned = persons | property | `pytest apps/agents/shelter/tests/test_matching_properties.py -q` | ❌ Wave 0 |
| PLAN-04 | Splitting; unplaceable group named (infeasible capacity, unreachable shelters) | unit | `pytest apps/agents/shelter/tests/test_matching.py -q` | ❌ Wave 0 |
| PLAN-04 | `update_occupancy` atomic CAS refuses overflow | unit (fake conn) + live | `pytest apps/agents/shelter/tests/test_registry.py -q`; live `COMPOSE_SMOKE=1 pytest tests/integration/test_shelters_db.py` | ❌ Wave 0 |
| PLAN-04 | Shelter exclusion near forecast perimeter | unit | `pytest apps/agents/shelter/tests/test_exclusion.py -q` | ❌ Wave 0 |
| PLAN-03 | Horizon cost attrs (blocked/P50/P90), nearest-horizon tie rule, monotonic penalties | unit/property | `pytest apps/agents/routing/tests/test_costs_horizons.py -q` | ❌ Wave 0 |
| PLAN-03 | k=3 distinct loopless paths on synthetic MultiDiGraph (parallel edges collapse, blocked hidden) | unit | `pytest apps/agents/routing/tests/test_k_paths.py -q` | ❌ Wave 0 |
| PLAN-03 | BPR formula, capacity from tags (`"['a','b']"`, missing lanes), MSA passes ≤3, deterministic | unit/property | `pytest apps/agents/routing/tests/test_congestion.py -q` | ❌ Wave 0 |
| PLAN-03 | Edge-status blocked edge excluded; `road_blocked` detection | unit | `pytest apps/coordinator/tests/test_replan_triggers.py -q` | ❌ Wave 0 |
| PLAN-07 | Resolver ≤3 loops, fixed order, enum-only LLM choice validated, fallback planner, `failed` result names group/reason | unit/property | `pytest apps/coordinator/tests/test_resolver.py apps/coordinator/tests/test_fallback_planner.py -q` | ❌ Wave 0 |
| PLAN-07 | LLM disabled/error ⇒ deterministic path (mock Groq) | unit | `pytest apps/coordinator/tests/test_llm_menu.py -q` | ❌ Wave 0 |
| PLAN-08 | V1–V8 pure functions (fail/flag/pass cases, V6 trivial pass on empty dispatches, V8 grounding within rounding, template always passes V8) | unit/property | `pytest apps/coordinator/tests/test_validators.py -q` | ❌ Wave 0 |
| PLAN-08 | Invalid plans blocked: validator failure ⇒ `failed`, never `pending_review` | unit | `pytest apps/coordinator/tests/test_plan_assembly.py -q` | ❌ Wave 0 |
| PLAN-08 | Material-diff signature (routes/assignments/validators) ⇒ new version only on change; parent link; no-change audit | unit | `pytest apps/coordinator/tests/test_plan_diff.py -q` | ❌ Wave 0 |
| PLAN-08 | Provenance + freshness present on every plan | unit | `pytest apps/coordinator/tests/test_plan_provenance.py -q` | ❌ Wave 0 |
| PLAN-08 | Migration 0006 SQL renders; immutability trigger rejects `plan_data` update (live) | migration/integration | `alembic -c infra/migrations/alembic.ini upgrade head --sql`; live `COMPOSE_SMOKE=1 pytest tests/integration/test_plan_versions_db.py` | ❌ Wave 0 |
| PLAN-01 | Parallel dispatch runs specialists concurrently, ToolResult error envelope, timeout | unit | `pytest apps/coordinator/tests/test_dispatch.py -q` | ❌ Wave 0 |
| Triggers D-14/D-15 | IoU/growth thresholds, debounce coalescing 5 min per (incident,type), SimClock | unit | `pytest tests/unit/test_replan_triggers.py -q` | ❌ Wave 0 |
| D-17 / WR-01 | Per-cluster weather lookup; cluster without weather handled | unit | `pytest apps/coordinator/tests/test_weather_per_cluster.py -q` | ❌ Wave 0 |
| D-17 / WR-03 | Parser marks `valid_time <= issued_at` as observation with real origin; ingest→`get_weather_snapshot` matches | unit + integration | `pytest tests/unit/test_weather_parser.py -q`; live `tests/integration/test_weather_ingest_to_plan.py` | partial (parser test exists) |
| Risk assessment | settlements ∩ P50 → groups, ETA, priority | unit | `pytest apps/agents/fire/tests/test_risk.py -q` | ❌ Wave 0 |
| End to end | synthetic graph + seeded shelters → validated plan; then perimeter change ⇒ v2 with diff | integration (offline fakes) + live gated | `pytest apps/coordinator/tests/test_pipeline_phase3.py -q`; live `COMPOSE_SMOKE=1` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** nearest package test file (`pytest <package>/tests -q`), < 10 s.
- **Per wave merge:** `pytest apps packages tests/unit -q`, `ruff check .`, `mypy packages/wildfire_core` (+ strict mypy for new agent packages).
- **Phase gate:** full offline suite green, Hypothesis `ci` profile, `uv lock --check`, `alembic upgrade head --sql` renders; live checks remain `COMPOSE_SMOKE=1` manual.

### Wave 0 Gaps
- [ ] `.gitignore`: add `data/` and `cache/`
- [ ] `tests/fixtures/graphs.py` — deterministic synthetic MultiDiGraph builder (≥3 distinct corridors, parallel edges, `highway`/`lanes` tags incl. list-strings, a capacity bottleneck, a dead end, node `x/y`, edge `length/travel_time`); optionally add a small committed real-subgraph fixture (< 1 MB, Rules §7) later via `ox.truncate.truncate_graph_dist` + `largest_component(strongly=True)` once the user has the cached graph
- [ ] `conftest.py` with Hypothesis `ci` profile (`derandomize=True`, `deadline=None`)
- [ ] `apps/agents/shelter/` package (pyproject, `tests/`), workspace + pythonpath wiring, `uv lock`, refreshed `requirements.txt`
- [ ] Alembic 0006; config sub-models in `defaults.yaml`
- [ ] Repository interface so coordinator nodes can be tested without SQL-substring fakes
- [ ] CI: extend pytest target to `apps packages tests/unit` (or place new tests under `tests/unit`)

## Security Domain

`security_enforcement` is not set in `.planning/config.json`, so it is treated as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (no auth until Phase 4; AR-06 accepted loopback-only) | — |
| V3 Session Management | no | — |
| V4 Access Control | partial | No new endpoints; if the gateway query gains `'failed'`, keep read-only/loopback (AR-06) |
| V5 Input Validation | yes | Pydantic v2 `extra="forbid"` models for plan/tool/ValidationResult; CSV seed rows validated (lat/lon ranges, capacity > 0, population ≥ 0, no control chars); Groq output validated against strict JSON schema + Pydantic; V7/V8 validators on plan content |
| V6 Cryptography | no (no new crypto) | Never hand-roll; none needed |
| V7 Error handling & logging | yes | Append-only audit rows (S7), failed runs audited via `finally`; errors via `ToolResult` envelope, no swallowed exceptions |
| V12 Files | yes | GraphML is read from a local operator-controlled path only; `ast.literal_eval` (not `eval`) for tag lists; no dynamic paths from request data |
| V14 Config | yes | Coefficients in config, no secrets in seeds; `.env` untouched |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| LLM invents shelter/number or is prompt-injected via data (e.g. shelter name in CSV) | Tampering | LLM returns only an enum; IDs/targets chosen deterministically; V7/V8; text in data files treated as data (Rules §12.10); compact payload only |
| Capacity overbooking / double-booking race | Tampering | Single-statement CAS on `shelters.occupancy`; V4 re-check at persist; advisory lock + unique `(incident_id, version)` |
| Silent mutation of an approved plan | Tampering | Immutability trigger on `plan_versions`; status-only updates; `parent_plan_id` chain |
| SQL injection via ids/names | Tampering | Parameterised `text()` binds only (existing pattern) |
| Fabricated/old weather driving fire forecasts | Tampering | Per-cluster scoped lookup, fail-closed (A13); age recorded in freshness |
| Implicit external download at runtime (SSRF/supply chain/DoS) | DoS/Tampering | Load-only graph loader; explicit build script |
| Data egress to Groq | Info disclosure | Settlement-level, non-personal, compact payload (Groq 8k TPM); gated by `llm_enabled` + key |
| Unverified capacities presented as fact | Repudiation/Integrity | `capacity_source` column shown on plans; S9 label; synthetic seeds flagged `is_simulated` |
| Trigger storm causing plan churn | DoS | 5-min coalescing per (incident, type) under advisory lock; material-change gate (D-16) |

## Sources

### Primary (HIGH confidence)
- Project files read this session: `generatedPlan/TechSpec.md` §4–§9, §12, §14; `generatedPlan/Rules.md`; `generatedPlan/Schema.md` §5–§8, §10; `generatedPlan/FolderStructure.md`; `.planning/phases/03-*/03-CONTEXT.md`; `02-REVIEW-GAPS.md`; `02-SECURITY.md`; `02-VALIDATION.md`; `.planning/ROADMAP.md`, `STATE.md`; code under `apps/`, `packages/wildfire_core`, `infra/migrations/versions/0001–0005`, `config/defaults.yaml`, `.github/workflows/ci.yml`, `pyproject.toml`, `uv.lock`
- Installed-package probes in the project venv: osmnx 2.1.1 signatures (`graph_from_polygon/point/bbox`, `save_graphml`, `load_graphml`, `truncate_*`, `nearest_nodes`), `ox.settings`; networkx docstrings (`network_simplex`, `min_cost_flow`, `shortest_simple_paths`)
- Offline prototypes in the session scratchpad: min-cost-flow split/infeasible/diagnostic sink; Hypothesis property run; Yen timings; LangGraph fan-out and `asyncio.gather` behaviour
- https://www.postgresql.org/docs/16/sql-altertype.html - ADD VALUE inside a transaction block
- https://console.groq.com/docs/structured-outputs - strict json_schema support on `openai/gpt-oss-20b`; no streaming/tool use with it

### Secondary (MEDIUM confidence)
- BPR defaults α=0.15, β=4 (Sheffi 1985; β 2–12 in practice per Spiess 1990), via https://arxiv.org/pdf/2211.13514 and related arXiv papers surfaced by search
- Evacuation capacity 950–1,000 vs 1,700–2,000 veh/h/lane: https://portolavalley.net/home/showpublisheddocument/14983 (search summary, not read in full)
- Populations: https://en.wikipedia.org/wiki/Hangala ; https://www.censusindia2011.com/karnataka/chamarajanagar/gundlupet/bandipura-population.html

### Tertiary (LOW confidence)
- Persons-per-vehicle, evacuation window, lane-capacity table, penalty magnitudes: `[ASSUMED]` (A1–A3)

## Project Constraints (from CLAUDE.md)

No `CLAUDE.md` or `.claude/` directory exists in this repository [VERIFIED: ls returned "No such file"]. Binding project conventions come from `generatedPlan/Rules.md` and are treated with the same authority:
- S1–S9 safety rules; S4 (LLM never computes or invents), S5 (V1–V8 before `pending_review`), S7 (append-only audit), S9 (capacity is an estimate with visible source).
- Pydantic v2 at every boundary; typed tool contracts with `{ok:false,error:{code,message,retryable}}`; time via injected `Clock`; no magic numbers (config); ≤3 conflict loops, tool retries ≤2, timeouts on every external call; agents never import each other.
- Geo: explicit CRS, metric work in EPSG:32643, `(lon, lat)` order; SI units, names carry units.
- Alembic-only schema changes; transactions + in-transaction capacity re-check; GiST on geometry columns; FKs indexed.
- Hypothesis property tests required for validators and capacity/double-booking; mock LLM in CI; no real network in CI; fixtures < 1 MB, large data in gitignored `data/`.
- Research constraints from the caller: `.env`/`.env.example` not read; no commits; no source changes; no OSM download.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all versions read from the venv and `uv.lock`; no new packages
- Architecture: HIGH for flow/validator/versioning design (probed); MEDIUM for resolver semantics and V3 definition (A4, A12)
- Pitfalls: HIGH for in-repo findings (read this session); MEDIUM for real-graph performance (A14, A17)
- Seed data: LOW - needs the user

**Research date:** 2026-10-17
**Valid until:** 2026-11-16 (stable libraries; re-check the lock if langgraph or networkx are bumped)

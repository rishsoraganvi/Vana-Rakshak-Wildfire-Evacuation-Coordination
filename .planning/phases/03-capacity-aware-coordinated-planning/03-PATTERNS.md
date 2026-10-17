# Phase 3: Capacity-Aware Coordinated Planning - Pattern Map

**Mapped:** 2026-10-17
**Files analyzed:** 38 (new + modified)
**Analogs found:** 33 / 38

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `infra/migrations/versions/0006_phase3_planning.py` (new) | migration | DDL | `infra/migrations/versions/0005_phase2_plan_versions.py` | exact |
| `apps/agents/routing/src/agent_routing/graph.py` (modify: load-only) | utility | file-I/O | itself (lines 13-39) | exact |
| `apps/agents/routing/src/agent_routing/costs.py` (modify: cost_h1/h3/h6) | service | transform | itself `apply_fire_penalties` (35-66) | exact |
| `apps/agents/routing/src/agent_routing/k_paths.py` (new) | service | transform | `agent_routing/router.py` (52-151) | role-match |
| `apps/agents/routing/src/agent_routing/congestion.py` (new) | utility | transform (pure) | `agent_routing/costs.py` | role-match |
| `apps/agents/routing/src/agent_routing/router.py` (modify: `route_cost_matrix`) | service | transform | itself `compute_route` | exact |
| `apps/agents/routing/src/agent_routing/__init__.py` (modify exports) | config | - | itself | exact |
| `apps/agents/shelter/pyproject.toml` (new package) | config | - | `apps/agents/routing/pyproject.toml` | exact |
| `apps/agents/shelter/src/agent_shelter/registry.py` (new) | service | CRUD (DB) | `wildfire_core/db/repositories.py` + `ingest_worker/triggers.py` | role-match |
| `apps/agents/shelter/src/agent_shelter/matching.py` (new) | service | transform (pure) | RESEARCH Pattern 1 + `router.py` style | partial |
| `apps/agents/fire/src/agent_fire/risk.py` (new) | service | transform | `agent_fire/ensemble.py` (60-76) + `costs.py` intersects | role-match |
| `apps/coordinator/src/coordinator/dispatch.py` (new) | service | async fan-out | none (asyncio) | no analog |
| `apps/coordinator/src/coordinator/planning/plan_core.py` (new) | service | batch/transform | `coordinator/graph.py::compute_route_node` (302-415) | role-match |
| `apps/coordinator/src/coordinator/planning/resolver.py` (new) | service | transform loop | none | no analog |
| `apps/coordinator/src/coordinator/planning/fallback_planner.py` (new) | service | transform | `router.py` deterministic tie-break | partial |
| `apps/coordinator/src/coordinator/planning/diff.py` (new) | utility | transform | none | no analog |
| `apps/coordinator/src/coordinator/planning/rationale_template.py` (new) | utility | transform | `groq_adapter.py::fallback` (107-127) | exact |
| `apps/coordinator/src/coordinator/validators/v1..v8 + run_all` (new) | utility | pure validation | `ingest_worker/triggers.py::evaluate_new_hotspot` (TriggerDecision) | role-match |
| `apps/coordinator/src/coordinator/llm/groq_adapter.py` (modify: `choose_fix_strategy`) | service | request-response | itself `generate_rationale` (77-192) | exact |
| `apps/coordinator/src/coordinator/replan.py` (new) | controller/entry | request-response | `coordinator/runner.py::run_coordinator` | role-match |
| `apps/coordinator/src/coordinator/graph.py` (modify: nodes, weather per cluster, persist) | controller | request-response | itself | exact |
| `apps/coordinator/src/coordinator/runner.py` (modify: edges, try/finally audit) | config/wiring | - | itself | exact |
| `apps/coordinator/src/coordinator/state.py` (modify) | model | - | itself | exact |
| `apps/coordinator/src/coordinator/audit.py` (modify: agent column) | service | CRUD | itself | exact |
| `packages/wildfire_core/src/wildfire_core/schemas/plan.py` (new: IntegratedPlan, ValidationResult) | model | - | `schemas/phase2.py` | exact |
| `packages/wildfire_core/src/wildfire_core/schemas/tools.py` (new: ToolResult) | model | - | `schemas/phase2.py` | exact |
| `packages/wildfire_core/src/wildfire_core/schemas/phase2.py` (modify: WeatherSnapshot.age_min, status) | model | - | itself | exact |
| `packages/wildfire_core/src/wildfire_core/schemas/state.py` (modify: SharedState sections) | model | - | itself | exact |
| `packages/wildfire_core/src/wildfire_core/db/repositories.py` (modify: shelters, plan_versions, state_version) | service | CRUD | itself | exact |
| `packages/wildfire_core/src/wildfire_core/config.py` + `config/defaults.yaml` (modify) | config | - | itself (Phase 2 additions block) | exact |
| `apps/ingest_worker/src/ingest_worker/triggers.py` (modify: detect_*, record_trigger) | service | event-driven | itself (copy shape, NOT debounce logic) | exact |
| `apps/ingest_worker/src/ingest_worker/weather/parser.py` (modify WR-03) | utility | transform | itself | exact |
| `apps/api_gateway/src/api_gateway/routers/incidents.py` (modify: status filter line 168) | controller | request-response | itself | exact |
| `scripts/build_osm_graph.py` (new) | script | file-I/O | `agent_routing/graph.py` + `scripts/seed_demo.py` | role-match |
| `scripts/seed_shelters.py`, `scripts/seed_settlements.py` (new) | script | batch DB | `scripts/seed_demo.py` | exact |
| `config/seed/shelters_bandipur.csv`, `settlements_bandipur.csv` (new) | data | - | none | no analog |
| `tests/fixtures/graphs.py` (new) | test fixture | - | `apps/agents/routing/tests/test_router.py::make_graph` (18-25) | exact |
| `tests/unit/test_*` property tests (new) | test | - | `tests/unit/test_triggers.py` (FakeEngine) | exact |
| `pyproject.toml`, `.gitignore`, `.github/workflows/ci.yml` (modify) | config | - | itself | exact |

## Pattern Assignments

### `infra/migrations/versions/0006_phase3_planning.py` (migration)
**Analog:** `infra/migrations/versions/0005_phase2_plan_versions.py` (lines 1-58)
```python
"""Add Phase 2 plan versions and Coordinator audit fields."""
from alembic import op

revision = "0005_phase2_plan_versions"
down_revision = "0004_shared_state_audit"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE plan_status AS ENUM ...;
        CREATE TABLE plan_versions ( id uuid PRIMARY KEY DEFAULT gen_random_uuid(), ... );
        CREATE INDEX ix_plan_versions_incident_created ON plan_versions (incident_id, created_at DESC);
        """
    )

def downgrade() -> None:
    op.execute("""DROP INDEX IF EXISTS ...; DROP TABLE IF EXISTS ...;""")
```
- New file: `revision = "0006_phase3_planning"`, `down_revision = "0005_phase2_plan_versions"`; one raw-SQL `op.execute` block; DDL body from RESEARCH "Migration 0006" sketch.
- Run `ALTER TYPE plan_status ADD VALUE IF NOT EXISTS 'failed'` as its own `op.execute`; never reference `'failed'` again in the same migration (Pitfall 6). Downgrade cannot drop the enum value; say so in the docstring.
- Naming: `ix_<table>_<cols>`, `uq_<table>_<cols>`, `jsonb NOT NULL DEFAULT '{}'::jsonb`.

### `apps/agents/routing/src/agent_routing/graph.py` (make it load-only)
**Analog:** the same file, lines 13-39. Keep the load branch and the speeds/travel-time step. Delete the `else` download branch (28-35); move it to `scripts/build_osm_graph.py`, using `graph_from_polygon` instead.
```python
cache_file = Path(cache_path)
if cache_file.exists():
    graph = ox.load_graphml(cache_file)
    logger.info("Loaded OSM road graph from cache: %s", cache_file)
...
graph = ox.add_edge_speeds(graph)
graph = ox.add_edge_travel_times(graph)
```
- If the file is missing, raise `FileNotFoundError` with the `uv run python scripts/build_osm_graph.py` command in the message. Cache the result in-process keyed by `(path, mtime)`; `graph.py` already uses `functools.lru_cache` at line 7. `graph.py:15-18` imports `load_or_download_graph`, and so does `test_router.py:10`. Keep that name as an alias or update both call sites.

### `apps/agents/routing/src/agent_routing/costs.py` (horizon cost attributes)
**Analog:** the same file, `apply_fire_penalties` (35-66). Copy its approach: `_edge_geometry` fallback to the chord, `shapely.prepare`, and one `graph.copy()`. Add three attributes per edge: `cost_h1`, `cost_h3` and `cost_h6`.
```python
current_perimeter = wkt.loads(current_perimeter_wkt)
if not current_perimeter.is_empty:
    shapely.prepare(current_perimeter)
penalized_graph = graph.copy()
for origin, destination, _key, data in penalized_graph.edges(keys=True, data=True):
    geometry = _edge_geometry(penalized_graph, origin, destination, data)
    travel_time = float(data["travel_time"])
    if not current_perimeter.is_empty and current_perimeter.intersects(geometry):
        data["penalised_cost"] = FIRE_PENALTY_BLOCKED
    elif not p50_perimeter.is_empty and p50_perimeter.intersects(geometry):
        data["penalised_cost"] = penalty_near * travel_time
    else:
        data["penalised_cost"] = FIRE_PENALTY_SAFE * travel_time
```
- Precedence is current, then P50, then P90, then safe. Read the multipliers from config (`p50_mult=10`, `p90_mult=3`, D-21); don't hard-code them as module constants. At real-graph scale, vectorise with `shapely.STRtree`. Copy the graph once per plan run, not once per pass.

### `apps/agents/routing/src/agent_routing/router.py` (+`route_cost_matrix`) and `k_paths.py` (new)
**Analog:** `router.py` lines 1-18 for imports and the type alias, and 52-75 for weight functions.
```python
from __future__ import annotations
from collections.abc import Callable
from math import cos, inf, isfinite, radians
from typing import Any, Literal
import networkx as nx
import osmnx as ox
from wildfire_core.schemas.phase2 import RouteResult

_WeightFn = Callable[[int, int, dict[Any, dict[str, Any]]], float | None]

def _edge_cost(attr, weight, *, fallback): ...   # returns None for inf when not fallback
def _unblocked_weight(weight: str) -> _WeightFn:
    def weight_fn(_u, _v, parallel_edges):
        costs = [_edge_cost(attr, weight, fallback=False) for attr in parallel_edges.values()]
        finite = [c for c in costs if c is not None]
        return min(finite) if finite else None
    return weight_fn
```
- `route_cost_matrix`: one `nx.single_source_dijkstra_path_length(graph, origin, weight=_unblocked_weight(attr))` per group. Use the same weight-function factory.
- RouteResult construction: copy lines 110-151 (per-hop edge-key selection, `isinstance(edge_key, int)` guard, safety classification). Set `destination_shelter_id` and `origin_settlement_id`; the fields already exist at `phase2.py:87-89`.
- `k_paths.py`: `collapse_to_digraph` plus `itertools.islice(nx.shortest_simple_paths(D, s, t, weight="w"), k)` (RESEARCH Pattern 2). Don't pass a MultiDiGraph to `shortest_simple_paths`.
- Keep `nearest_node` (21-24) and `nearest_node_outside` (27-49) for snapping settlements and shelters. Ties go to the smallest node id, the same deterministic convention used throughout.

### `apps/agents/routing/src/agent_routing/congestion.py` (new, pure)
**Analog:** the module style of `costs.py`: `from __future__ import annotations`, module-level constants, typed `nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]` signatures, and pure functions. Pass α, β, persons_per_vehicle, evac_window_h and passes in from config. The formula is in RESEARCH Pattern 4.

### `apps/agents/shelter/pyproject.toml` (new workspace member)
**Analog:** `apps/agents/routing/pyproject.toml` (1-13)
```toml
[project]
name = "agent-routing"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = ["networkx>=3.4", "osmnx>=2.0.0", "shapely>=2.0.0", "wildfire-core"]
[tool.uv.sources]
wildfire-core = { workspace = true }
```
- Use `name = "agent-shelter"` with deps `networkx>=3.4`, `shapely>=2.0.0`, `sqlalchemy` and `wildfire-core`. Also add it to root `pyproject.toml` in three places: `[tool.uv.workspace].members` (line ~30), `[tool.uv.sources]`, and the `[tool.pytest.ini_options].pythonpath` list (line ~57). Then run `uv lock`.

### `apps/agents/shelter/src/agent_shelter/registry.py` (CRUD)
**Analog:** `packages/wildfire_core/src/wildfire_core/db/repositories.py`. Functions take `engine: Engine`, open one transaction with `with engine.begin()`, and use `text()` SQL with `CAST(:x AS jsonb)`:
```python
def save_shared_state(engine: Engine, state: SharedState) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO shared_state_snapshots (incident_id, version, state)
                    VALUES (:incident_id, :version, CAST(:state AS jsonb))"""),
            {"incident_id": state.incident_id, "version": state.version,
             "state": state.model_dump_json()},
        )
```
- `update_occupancy`: a single-statement CAS `UPDATE ... RETURNING` (RESEARCH "Atomic occupancy update"). If the result is `None`, raise `CapacityExceeded`. Insert the history row in the same `engine.begin()` block.
- `usable_capacity = floor(capacity * (usable_factor or settings.shelter_usable_factor))`.

### `apps/agents/shelter/src/agent_shelter/matching.py` (pure)
**Analog:** no in-repo min-cost flow. Use RESEARCH Pattern 1 as written: integer weights, the diagnostic `U` node, and sorted insertion for determinism. For return types, follow the frozen-dataclass decision style of `triggers.py` (lines 12-15, `@dataclass(frozen=True) class TriggerDecision`) or a Pydantic model with `extra="forbid"`.

### `apps/agents/fire/src/agent_fire/risk.py` (new)
**Analog:** `ensemble.py` (60-76) builds `FireSpreadResult(..., settlements_at_risk=())`. `risk.py` produces that tuple of `SettlementRisk2` (`phase2.py:37-52`, whose exposure literals `inside_p50_1h` and so on already exist). For intersects, follow `costs.py` (`wkt.loads` plus `shapely.prepare` plus `.intersects`). Key groups on `settlements.id`, never on `cluster_id`, which is a uuid4 per run (`phase2.py:13`). Settlements inside the current perimeter get a rescue flag (D-20) and are left out of groups.

### `apps/coordinator/src/coordinator/graph.py` (new nodes and changes)
**Imports analog:** lines 1-41 (agents are imported via packages and `coordinator.*` is absolute). New imports include `from agent_shelter.registry import ...` and `from coordinator.planning.plan_core import ...`.
**Node + audit pattern:** each node takes `started_ms = time.monotonic_ns() // 1_000_000`, does its work, calls `_audit(...)`, and returns state. `_audit` is at lines 108-125:
```python
def _audit(state, node_name, inputs, outputs, started_ms, model_metadata=None) -> None:
    entry = AuditEntry(incident_id=state["incident_id"], run_id=state["run_id"], node_name=node_name,
        inputs_json=json.dumps(inputs, sort_keys=True, default=str),
        outputs_json=json.dumps(outputs, sort_keys=True, default=str),
        latency_ms=max(0, time.monotonic_ns() // 1_000_000 - started_ms),
        model_metadata=model_metadata)
    state["audit_entries"].append(entry.model_dump(mode="json"))
```
**Persist pattern:** see `assemble_plan` (lines 476-527). Replace the racy `SELECT COALESCE(MAX(version),0)+1` (lines 485-491) with `SELECT pg_advisory_xact_lock(hashtext(:incident_id))` inside the same `.begin()` block, then MAX+1. Write the new columns (`parent_plan_id`, `validation`, `freshness`, `provenance`, `diff`, `used_fallback`, `state_version`) and the status `pending_review` or `failed`. Keep the `is_simulated` derivation from incident origin (line 504). Move all new SQL into repository functions passed into nodes (Pitfall 9).
**WR-01:** `run_weather` (195-244) moves after `cluster_hotspots`, with one `get_weather_snapshot` per cluster centroid. If a cluster has no weather, fail closed.

### `apps/coordinator/src/coordinator/runner.py`
**Analog:** the same file, lines 22-42 (`add_node` / `add_edge` chain) and 45-61 (`initial_state` dict). New order: `ingest_trigger -> cluster_hotspots -> run_weather -> run_fire_ca -> assess_risk -> dispatch_specialists -> plan (core) -> generate_rationale -> assemble_plan -> write_audit`. Add new state keys to `initial_state` and to `state.py`'s TypedDict at the same time. Wrap `invoke` in try/finally and flush audit on failure (Pitfall 15), reusing `flush_audit_entries`.

### `apps/coordinator/src/coordinator/llm/groq_adapter.py` (+`choose_fix_strategy`)
**Analog:** `generate_rationale` (77-192). Copy the order exactly: build the payload, build `fallback()`, check the gate, call the API, then catch any `Exception`.
```python
api_key = settings.groq_api_key.get_secret_value().strip()
gate: str | None = None
if not settings.llm_enabled: gate = "llm_disabled"
elif settings.llm_provider != "groq": gate = "provider_not_groq"
elif not settings.llm_model.strip(): gate = "model_not_configured"
elif not api_key: gate = "api_key_missing"
if gate is not None:
    return fallback(gate, f"LLM unavailable: {gate}", llm_called=False)
...
response = Groq(api_key=api_key).chat.completions.create(model=..., messages=..., timeout=settings.llm_request_timeout_s, **request_kwargs)
...
except Exception as error:
    name = type(error).__name__
    return fallback(f"error:{name}", f"LLM error: {name}", llm_called=True, effort=reasoning_effort)
```
- Add `response_format={"type": "json_schema", "json_schema": {"name": "fix_strategy", "strict": True, "schema": {enum of next_path|rematch|split}}}`. Validate the reply with Pydantic, allow one repair retry, and otherwise use deterministic order. Reuse `_metadata(...)` (line 33) so audit `model_metadata` keeps the same shape.

### `apps/coordinator/src/coordinator/planning/rationale_template.py`
**Analog:** the inner `fallback()` in `groq_adapter.py` (107-127), which builds deterministic text from plan data only:
```python
text = (f"[DETERMINISTIC FALLBACK] Fire spread CA: {total_area:g} km2 across "
        f"{len(fire_results)} cluster(s). Routes: {len(routes)}. Human review required. ({detail})")
```
- Every number must come from plan fields so that V8 passes by construction.

### `apps/coordinator/src/coordinator/validators/*`
**Analog:** `ingest_worker/triggers.py` lines 12-25, a pure function that returns a frozen decision with an explicit reason string:
```python
@dataclass(frozen=True)
class TriggerDecision:
    crossed: bool
    reason: str
def evaluate_new_hotspot(count: int, threshold: int) -> TriggerDecision:
    if threshold < 1: raise ValueError("threshold must be positive")
    return (TriggerDecision(True, "new_hotspot_threshold_crossed") if count >= threshold
            else TriggerDecision(False, "below_new_hotspot_threshold"))
```
- Write `ValidationResult(validator_id, status: pass|fail|replaced, reasons, violations)` as a Pydantic model in `schemas/plan.py`. V6 passes when `dispatches` is empty. V8 regex grounding is in RESEARCH.

### `apps/ingest_worker/src/ingest_worker/triggers.py` (+`detect_perimeter_change`, `detect_road_blocked`, `detect_shelter_capacity_change`, `record_trigger`)
**Analog:** the same file. Copy the `evaluate_*` / `record_*` split, the `engine.begin()` block and the jsonb `details` insert (lines 63-85). **Do NOT copy** the debounce query at lines 41-52, which has no incident filter, or the incident INSERT with hard-coded `'replay'` (lines 53-62); see Pitfall 8. Instead:
- Take the advisory lock on `incident||type` and scope the query by `(incident_id, type)`. Use the leader as `coalesced_into`. Get time from the injected `Clock` (`wildfire_core.clock`), as `weather/parser.py:11-14` does.
- WR-03: `record_new_hotspot_trigger` must pass the hotspot origin into the incident insert instead of `'replay'`.

### `apps/ingest_worker/src/ingest_worker/weather/parser.py` (WR-03)
**Analog:** the same file. Line 15 has `origin: str = "replay"`; make it required with no default. Line 47 has `is_forecast=True`; change it to `is_forecast=valid_time > issued_at`. Add a fixture for observations with times at or before `issued_at`. The scoped query is `agent_weather/agent.py:36` (`is_forecast.is_(False)`) and `:55-56` (origin filter).

### `packages/wildfire_core/src/wildfire_core/schemas/plan.py`, `tools.py`
**Analog:** `schemas/phase2.py`. Every model uses `model_config = ConfigDict(extra="forbid")`, `Field(ge=...)` bounds, `Literal` enums, tuples rather than lists, `Field(default_factory=lambda: str(uuid.uuid4()))` for ids, and `@model_validator(mode="after")` for cross-field rules (lines 96-100). The `CoordinatorPlan` shape (117-131) is the base for `IntegratedPlan`. Widen the status to `Literal["pending_review", "failed"]` and add `validation`, `freshness`, `provenance`, `parent_plan_id`, `used_fallback`, `alerts` (D-20) and `assignments`.
- `WeatherSnapshot` (25-34) gets `age_min: int` (it is `extra="forbid"`, so the field must be declared).

### `packages/wildfire_core/src/wildfire_core/config.py` + `config/defaults.yaml`
**Analog:** the "Phase 2 additions" block in `Settings` (config.py 54-62) and the flat yaml keys (`route_fire_penalty_near: 5.0`). Add a commented "Phase 3 additions" block with defaults: `shelter_usable_factor: 0.6`, `route_p50_mult: 10`, `route_p90_mult: 3`, `shelter_exclusion_buffer_m: 1000`, `bpr_alpha: 0.15`, `bpr_beta: 4`, `persons_per_vehicle`, `evac_window_h`, `congestion_passes: 3`, `k_paths: 3`, `k_paths_max_leg_s`, `conflict_max_loops: 3`, `trigger_debounce_s: 300`, `perimeter_iou_threshold: 0.8`, `perimeter_growth_threshold: 0.25`, `pilot_center_lat/lon: 11.72/76.64`, `pilot_buffer_m: 10000`. The research's nested sub-models are optional; the flat style matches the existing code.

### `scripts/seed_shelters.py`, `scripts/seed_settlements.py`, `scripts/build_osm_graph.py`
**Analog:** `scripts/seed_demo.py` (1-30+): `argparse`, `load_settings()`, `create_db_engine(settings.database_url.get_secret_value())`, one `engine.begin()` block, and idempotent `INSERT ... SELECT ... WHERE NOT EXISTS`. For seeds, prefer `ON CONFLICT (external_ref) DO UPDATE` (the `on_conflict_do_update` pattern in repositories.py 32-41). Geometry goes through `ST_SetSRID(ST_MakePoint(lon, lat), 4326)` (repositories.py:30). Every row carries `capacity_source='synthetic'` (D-18).
- `build_osm_graph.py`: reuse `load_or_download_graph`'s save step (`cache_file.parent.mkdir(...)`, `ox.save_graphml`). Set `ox.settings.cache_folder = "data/osm/cache"` and build with `graph_from_polygon` (a 10 km buffer around 11.72 N, 76.64 E in EPSG:32643).

### `tests/fixtures/graphs.py` and property tests
**Fixture analog:** `apps/agents/routing/tests/test_router.py` lines 18-25:
```python
def make_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node(1, x=0.0, y=0.0)
    graph.add_edge(1, 2, key=7, length=100.0, travel_time=10.0, penalised_cost=10.0)
```
Scale this up deterministically (a grid with parallel edges, integer keys, `x`/`y`, `length`, `travel_time`, `highway` and `lanes` attributes).
**DB-fake analog:** `tests/unit/test_triggers.py` lines 20-37 (a `FakeConnection.execute` that dispatches on the SQL prefix, plus a `FakeEngine.begin` contextmanager). Put tests under `tests/unit/`, because CI runs only `tests/unit` (Pitfall 10). Use `hypothesis` (pinned in pyproject dev group line 49).

## Shared Patterns

### Module header / typing
**Source:** every module, e.g. `agent_routing/costs.py` lines 1-9. Start with `from __future__ import annotations`, use typed `nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]` signatures, and keep imports absolute across workspace packages.

### Pydantic boundary models
**Source:** `schemas/phase2.py`. Use `ConfigDict(extra="forbid")`, tuples for collections, and `model_dump(mode="json")` before json/jsonb.

### DB access
**Source:** `repositories.py` and `graph.py:480-517`. Use `with engine.begin() as connection:` and `text()` with named params. JSON goes through `CAST(:x AS jsonb)` with `json.dumps(..., sort_keys=True)`. UUIDs are wrapped with `UUID(...)`. Engine creation goes through `create_db_engine(settings.database_url.get_secret_value())`.

### Audit
**Source:** `graph.py::_audit` (108-125) and `audit.py::flush_audit_entries` (13-49). Every node and every specialist call adds one entry. `audit.py:42` hard-codes the agent as `'coordinator'`; parameterise it per entry (`traffic_routing`, `shelter`).

### LLM gating
**Source:** `groq_adapter.py` lines 129-139. The LLM is off by default. When the gate is closed, don't construct a client; return the deterministic result instead and record a `fallback_reason` in `model_metadata`.

### Determinism
**Source:** `router.py:35` and `47` (ties go to the smallest id) and the `sort_keys=True` dumps. Sort every insertion into flow graphs and every signature.

## No Analog Found

| File | Role | Data Flow | Reason / Use instead |
|---|---|---|---|
| `coordinator/dispatch.py` | service | async fan-out | No asyncio code in the repo. Use RESEARCH Pattern 6 (`asyncio.gather` + `to_thread` + `wait_for`, run in a worker thread if a loop is already running). |
| `coordinator/planning/resolver.py` | service | bounded loop | Use RESEARCH Pattern 5 (`for loop in range(3)`, order next_path, rematch, split). |
| `coordinator/planning/diff.py` | utility | transform | Use RESEARCH Pattern 7 (material signature: sorted assignments + node paths + validator statuses). |
| `agent_shelter/matching.py` | service | transform | Use RESEARCH Pattern 1 code exactly. |
| `config/seed/*.csv` | data | - | Synthetic, labelled, D-18/D-19. |

## Metadata
**Analog search scope:** `apps/`, `packages/`, `infra/migrations/`, `scripts/`, `tests/`, `config/`
**Files scanned:** ~75 Python files; 14 read in detail
**Pattern extraction date:** 2026-10-17

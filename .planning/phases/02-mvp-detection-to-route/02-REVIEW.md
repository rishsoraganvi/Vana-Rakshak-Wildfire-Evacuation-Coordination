---
phase: 02-mvp-detection-to-route
reviewed: 2026-10-17T03:12:49Z
depth: deep
files_reviewed: 29
files_reviewed_list:
  - packages/wildfire_core/src/wildfire_core/schemas/phase2.py
  - packages/wildfire_core/src/wildfire_core/config.py
  - config/defaults.yaml
  - pyproject.toml
  - docker-compose.yml
  - apps/agents/weather/src/agent_weather/agent.py
  - apps/agents/fire/src/agent_fire/ca_model.py
  - apps/agents/fire/src/agent_fire/ensemble.py
  - apps/agents/fire/tests/test_ca_model.py
  - apps/ingest_worker/src/ingest_worker/clustering.py
  - apps/ingest_worker/src/ingest_worker/triggers.py
  - apps/agents/routing/src/agent_routing/graph.py
  - apps/agents/routing/src/agent_routing/costs.py
  - apps/agents/routing/src/agent_routing/router.py
  - apps/agents/routing/tests/test_router.py
  - apps/coordinator/src/coordinator/graph.py
  - apps/coordinator/src/coordinator/runner.py
  - apps/coordinator/src/coordinator/state.py
  - apps/coordinator/src/coordinator/llm/groq_adapter.py
  - apps/coordinator/src/coordinator/audit.py
  - apps/coordinator/tests/test_groq_adapter.py
  - infra/migrations/versions/0005_phase2_plan_versions.py
  - infra/migrations/env.py
  - apps/api_gateway/src/api_gateway/routers/incidents.py
  - apps/api_gateway/src/api_gateway/main.py
  - apps/api_gateway/tests/test_incidents_api.py
  - scripts/replay_demo.py
  - tests/integration/test_coordinator_pipeline.py
  - tests/integration/test_migrations_and_ingest.py
findings:
  critical: 3
  high: 6
  medium: 11
  low: 10
  total: 30
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-10-17T03:12:49Z
**Depth:** deep (cross-module tracing plus small probes of the CA model and routing pipeline)
**Files Reviewed:** 29
**Status:** issues_found

Severity mapping: **Critical** and **High** are BLOCKERs (wrong behaviour, a safety or security problem, or a risk of losing data). Fix them before the plan output is used for anything beyond a demo. **Medium** and **Low** are WARNINGs: they make the code less correct or less robust.

## Summary

Phase 2 builds the full chain: trigger, weather, DBSCAN, CA ensemble, routing, Groq rationale, plan and audit, then the read API. SQL is parameterised throughout, so no injection was found. The API is published on loopback only. Secrets use `SecretStr` and stay out of warnings and audit rows.

The deterministic numbers that matter for safety are wrong in ways the tests do not catch:

1. **The fire model spreads fire upwind.** It treats `wind_dir_deg` as the direction the wind blows *toward*. The stored data is Open-Meteo `wind_direction_10m`, which is the direction the wind comes *from*. A probe with wind from 270° (blowing east) gave a P50 spread direction of 253°, i.e. west.
2. **A route can start inside the active fire and still be rated "safe".** Routing checks only edge midpoints. A probe on the bundled fixture confirmed this: the origin node is inside the current perimeter, and both routes come back `safe` with no penalised edges.
3. **Only the largest cluster is simulated.** Routes for every other cluster ignore that cluster's own fire.

The weather path also has problems. Location is ignored, missing values are silently replaced with 0, and when weather is unavailable a fake observation stamped `now` is created. The API then reports that fake weather as fresh.

The LLM is called even when `llm_enabled: false`. Postgres and Redis are published on all interfaces, with default and no credentials respectively.

The four uncommitted fixes from this session are correct as far as they go:
- `CAST(:status AS text)` avoids psycopg's AmbiguousParameter error.
- The `%%` escaping in `env.py` is correct for configparser.
- `sys.path` bootstrapping in `replay_demo.py` works.
- Scoping the integration test queries is correct.

However, the trigger test now future-dates rows, and this pollutes the shared DB (MD-09).

## Critical Issues

### CR-01: CA wind kernel uses the wrong wind-direction convention, so fire spreads upwind

**File:** `apps/agents/fire/src/agent_fire/ca_model.py:19-21`, `:40-41` (data source: `apps/ingest_worker/src/ingest_worker/weather/parser.py:51`)
**Issue:** `_wind_factor` is largest when `spread_dir_deg == wind_dir_deg`. The stored value comes from Open-Meteo `wind_direction_10m`, the meteorological "from" direction. Real wind therefore pushes fire *into* the wind. Probe: `run_ensemble(wind_speed_ms=8, wind_dir_deg=270, …)` (westerly wind, blowing east) returned `spread_direction_deg=253.36` with the P50 centroid west of ignition. `test_wind_factor_downwind` (`test_ca_model.py:8-17`) encodes the wrong "blowing toward" assumption, so the bug passes CI. Every P50/P90 polygon, route penalty and rationale built on live weather points the wrong way.
**Fix:**
```python
def _wind_factor(wind_speed_ms: float, wind_from_deg: float, spread_dir_deg: float) -> float:
    downwind_deg = (wind_from_deg + 180.0) % 360.0   # meteorological FROM -> TOWARD
    theta = math.radians(spread_dir_deg - downwind_deg)
    return float(math.exp(WIND_COEFF * wind_speed_ms * (math.cos(theta) - 1.0)))
```
Rename the parameter or field (`wind_from_deg`) and rewrite the test: wind *from* 270 must give spread toward about 90°.

### CR-02: Edge fire exposure uses only the edge midpoint, so routes through the active fire are rated "safe"

**File:** `apps/agents/routing/src/agent_routing/costs.py:29-40`
**Issue:** Only the midpoint of each edge is tested with `contains`. An edge that starts inside, ends inside, or cuts across the current perimeter or P50 polygon gets `penalised_cost == travel_time` when its midpoint is outside. Probe on `tests/fixtures/osm/bandipur_stub.graphml` with the replay-demo cluster: origin node `1000002` is inside the current perimeter, yet `compute_route` returned `('safe', (1000002, 1000001), ())` and `('safe', (1000002, 1000003), ())`. On long rural OSM edges this misses most crossings. `contains` also excludes points on the boundary.
**Fix:** Test the edge geometry, falling back to a straight segment between the two nodes:
```python
geom = data.get("geometry") or LineString([(ox_, oy_), (dx_, dy_)])
if not current_perimeter.is_empty and geom.intersects(current_perimeter):
    data["penalised_cost"] = FIRE_PENALTY_BLOCKED
elif not p50_perimeter.is_empty and geom.intersects(p50_perimeter):
    data["penalised_cost"] = penalty_near * travel_time
```
Use `shapely.prepared.prep()` on the polygons, and add a test where the edge midpoint is outside but an endpoint is inside.

### CR-03: Only the largest cluster is simulated, but every cluster is routed against that one fire

**File:** `apps/coordinator/src/coordinator/graph.py:225-235`, `:264-270`, `:277-320`
**Issue:** `run_fire_ca` keeps only `max(clusters, key=point_count)`. `compute_route_node` then routes *every* cluster over a graph penalised only by that single fire. A second cluster's own burning area adds no penalty, so its routes can go straight through it and be rated `safe`. `CoordinatorPlan.fire_result` is singular, so the plan cannot show the gap.
**Fix:** Run `compute_fire_spread` for every cluster. Union all current perimeters and P50 polygons (`unary_union`) before calling `apply_fire_penalties`. Store `fire_results: tuple[FireSpreadResult, ...]`. If you keep the single-cluster MVP, at minimum skip routing for clusters without a fire result and add a plan warning.

## High Issues

### HI-01: Infinite penalty plus routes starting inside the fire: Dijkstra cannot rank routes, and the "blocked" fallback is arbitrary

**File:** `apps/coordinator/src/coordinator/graph.py:279`, `:293-310`; `apps/agents/routing/src/agent_routing/costs.py:12,36`; `router.py:31`
**Issue:** The route origin is `nearest_node(cluster centroid)`. By construction that is inside the 3x3-cell (750 m) current perimeter. On a real OSM graph, edges near the origin get `inf` cost (the fixture escaped this only because its edges are long; see CR-02). Once any `inf` cost is on the path, NetworkX's `vu_dist < seen[u]` (`inf < inf`) is always false. The first path discovered wins, not the shortest or safest. Every candidate then comes back `blocked`, and the route kept (`blocked_route`) is arbitrary and may cross more fire than needed.
**Fix:** Start routes from the nearest node *outside* the current perimeter, or from settlements. Replace `inf` with a large finite penalty (for example `1e6 * travel_time`) so Dijkstra still ranks routes, or use a weight callback that returns `None` for blocked edges and run a separate "least-blocked" search only when no path exists.

### HI-02: Spread direction and rate measure the shift of the P50 centroid plus grid-snapping error, not how fast the fire front moves

**File:** `apps/agents/fire/src/agent_fire/ca_model.py:144-156`
**Issue:**
- `spread_rate_m_per_h` is the distance from the hotspot centroid to the *centroid* of the 3h P50 mask, divided by 3. When spread is symmetric, the centroid barely moves and the rate is about 0 even for a large fire.
- When there is no spread, snapping ignition to the grid (`round()` at :91-92) creates a fake offset. Probe with calm wind (`wind_speed_ms=0`): `spread_direction_deg=130.63` and `spread_rate_m_per_h=73.61`.
- The `/3.0` is hard-coded even when 180 is not in `horizons_min` (fallback at :141).

These numbers go into the plan and the LLM rationale as if they were deterministic facts.
**Fix:** Measure from the snapped ignition-cell centre, not the raw centroid. Compute the rate as the maximum distance from ignition to the P50 boundary (`p50_poly.hausdorff_distance(ignition_poly)` or the max over boundary vertices) divided by the actual horizon in hours. Below a minimum displacement, report the direction as `None` or as the wind direction.

### HI-03: When weather is unavailable, a fake observation stamped "now" is created and the API reports it as fresh

**File:** `apps/coordinator/src/coordinator/graph.py:174-183`; `apps/agents/weather/src/agent_weather/agent.py:50-53`; consumer `apps/api_gateway/src/api_gateway/routers/incidents.py:80-81`
**Issue:**
- On any weather exception, the code builds a `WeatherSnapshot` with `valid_time=datetime.now(UTC)`, wind 0, RH 0, temperature 0, and `stale_age_min=None`.
- The CA model runs on these made-up inputs, and the plan is saved as a normal draft.
- `_freshness` computes `weather_age_min` from that `valid_time`, so `GET /incidents/{id}/plan` shows weather that is **about 0 minutes old** when there was none.
- Separately, `get_weather_snapshot` turns NULL wind direction, speed, RH and temperature into `0.0` (`or 0.0`) without saying so.
**Fix:** Do not invent observations. Leave `state["weather_snapshot"] = None`, skip the CA step (or run a clearly labelled worst-case scenario), and set `is_stale=True` and `valid_time=None`. Make the snapshot fields `Optional` and raise or warn when a required field is NULL instead of substituting 0.

### HI-04: Weather agent ignores location, provider and origin

**File:** `apps/agents/weather/src/agent_weather/agent.py:11-21`
**Issue:** `lat` and `lon` are accepted but never used. The query takes the newest non-forecast row from the whole table, whatever its location, provider or `origin`. Replay or test rows (`replay_demo.py:96-107` inserts `origin='replay'` with `valid_time=now`) will be used by live incidents. Any second AOI or station gives the wrong weather.
**Fix:** Filter by distance (`ST_DWithin(geom, ST_MakePoint(:lon,:lat)::geography, :radius_m)` or a lat/lon bounding box), `valid_time <= now()`, and an origin that matches the incident's origin. Order by distance and then by recency.

### HI-05: The LLM is called even when `llm_enabled` is false or `llm_provider` is not Groq

**File:** `apps/coordinator/src/coordinator/llm/groq_adapter.py:41-48`; `apps/coordinator/src/coordinator/graph.py:336-341`
**Issue:** `settings.llm_enabled` (default `false` in `config/defaults.yaml:11`) and `llm_provider` (default `anthropic`) are never checked; a grep finds no reader outside `config.py`. Whenever `GROQ_API_KEY` is set, the full fire, weather and route payload goes to an external provider, even though the operator disabled the LLM. That is an unauthorised data egress and a config-control bypass. With `llm_model: ""`, it also makes a failing network call and adds a 1 s sleep to every run.
**Fix:**
```python
if not settings.llm_enabled or settings.llm_provider != "groq" or not settings.llm_model:
    return _fallback(fire_result, routes, reason="llm_disabled"), True
```

### HI-06: Postgres and Redis are published on all interfaces with default or no credentials

**File:** `docker-compose.yml:9-11`, `:24-25`; `config/defaults.yaml:14`; `packages/wildfire_core/src/wildfire_core/config.py:52`
**Issue:** The API port was correctly bound to `127.0.0.1` (`docker-compose.yml:42`). Postgres (`"${POSTGRES_PORT:-5432}:5432"`) and Redis (`"${REDIS_PORT:-6379}:6379"`) still bind `0.0.0.0`. Postgres falls back to password `change_me`, which is also hard-coded in `defaults.yaml` and `Settings.postgres_password`. Redis has no auth. Anyone on the LAN can read or modify draft evacuation plans, audit rows and incidents, which defeats the "local-only until Phase 4 JWT" decision.
**Fix:** Use `"127.0.0.1:${POSTGRES_PORT:-5432}:5432"` and `"127.0.0.1:${REDIS_PORT:-6379}:6379"`. Make `POSTGRES_PASSWORD` required (`${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}`), and remove the credential from `defaults.yaml` and the `Settings` default.

## Medium Issues

### MD-01: `fire_penalty_edges` stores the MultiDiGraph parallel-edge key (almost always 0), not an edge identifier

**File:** `apps/agents/routing/src/agent_routing/router.py:43-52`, `:70-74`
**Issue:** `edge_key` is the multigraph key from `get_edge_data(u, v)`, usually `0`. `fire_penalty_edges` ends up as `(0, 0, 0, …)`, which cannot identify which road segments were penalised. The audit and plan data are therefore lossy.
**Fix:** Store `(u, v, key)` triples or OSM way ids (`edge_data.get("osmid")`), and change the schema to `tuple[tuple[int, int, int], ...]`.

### MD-02: Routing uses only P50 at 1 h; P90 and the 3 h/6 h horizons are ignored, and exits can sit inside predicted fire

**File:** `apps/coordinator/src/coordinator/graph.py:265-276`, `:56`
**Issue:** Penalties use only `p50_1h_wkt`. The conservative P90 and longer horizons have no effect, even though rural evacuations and staging can take more than an hour. `_aoi_boundary_exit_nodes` excludes only nodes inside the *current* perimeter, so an exit can be inside P50 or P90.
**Fix:** Penalise against the union of P90 polygons up to the expected evacuation horizon (or tiered penalties: P50 1h > P90 1h > P50 3h …), and exclude exits inside P50 or P90.

### MD-03: Route selection takes the first non-blocked route, even "caution", without looking for a "safe" one

**File:** `apps/coordinator/src/coordinator/graph.py:294-306`
**Issue:** Candidates are tried in straight-line (degree) distance order, and the first non-`blocked` route is accepted. A `caution` route through P50 is chosen even when a `safe` route to another exit exists.
**Fix:** Compute routes to all exits, then choose by `(classification rank, penalised cost, travel time)`.

### MD-04: Ignition ignores the cluster's extent, and an out-of-grid centroid is silently clamped to the grid edge

**File:** `apps/agents/fire/src/agent_fire/ca_model.py:91-95`
**Issue:** Ignition is always a 3x3-cell block around the centroid, whatever the cluster's bbox or hotspot count. Large clusters are underestimated. `np.clip` moves an out-of-bbox centroid to the grid edge with no error. Probe: `centroid_lat=12.5` with the bbox north edge at 11.80 produced a perimeter at about lat 11.80. The fire is placed in the wrong location silently.
**Fix:** Raise `ValueError`, or warn and expand the grid, when the centroid is outside the bbox. Ignite every cell that contains a hotspot, or the cluster's bbox, instead of a fixed 3x3 block.

### MD-05: The random generator is re-seeded for every horizon, so the same random draws repeat

**File:** `apps/agents/fire/src/agent_fire/ca_model.py:58`, `:100-107`
**Issue:** `_run_single` calls `np.random.default_rng(seed)` on every call. Each horizon segment (0-60, 60-180, 180-360) restarts the same random stream, so step k of every segment uses identical random draws. This biases the ensemble statistics: correlated draws, too little spread, and confidence that is inflated.
**Fix:** Create `rng = np.random.default_rng(s)` once per seed in `run_ensemble` and pass it into `_run_single`.

### MD-06: Audit trail is incomplete and unreliable

**File:** `apps/coordinator/src/coordinator/audit.py:25`, `:39-41`; `apps/coordinator/src/coordinator/runner.py:33-41`; `graph.py:124`, `:376-379`, `:424-437`
**Issue:**
- Every row is written with `status='succeeded'`, including nodes that fell back or failed.
- The graph is strictly linear with no error handling. An exception in any node aborts the run before `write_audit`, and nothing is persisted. Examples: `UUID(str(hotspot_id))` on a malformed id, `scalar_one()` on a missing incident, an `IntegrityError` on the plan version.
- The plan and the audit rows are committed in separate transactions.
- `model_metadata` (model, tokens, finish_reason) is never populated, although `agent_runs` has `llm_model`, `tokens_in` and `tokens_out` columns.
- If it were populated, passing a raw `dict` to `CAST(:model_metadata AS jsonb)` fails, because psycopg 3 cannot adapt `dict` to a text param.
**Fix:**
- Wrap node bodies, or `run_coordinator`, in try/finally so audit entries are always flushed, with the failing node marked `status='failed'` and `error` set.
- Record the per-node status in `AuditEntry`.
- Pass `json.dumps(model_metadata)`.
- Have `generate_rationale` return model, usage and finish_reason metadata.

### MD-07: Plan version race, and the incident status is overwritten without checking its current value

**File:** `apps/coordinator/src/coordinator/graph.py:380-386`, `:409-412`
**Issue:** `COALESCE(MAX(version),0)+1` is computed without a lock. Two concurrent runs for the same incident hit `uq_plan_versions_incident_version`, and the losing run crashes with no audit (see MD-06). `UPDATE incidents SET status='planning'` runs regardless of the current status, so re-running the coordinator moves an `active` or `resolved` incident back to `planning`.
**Fix:** Take `SELECT … FROM incidents WHERE id=:id FOR UPDATE` before computing the version, or retry on `IntegrityError`. Use `UPDATE … SET status='planning' WHERE id=:id AND status IN ('open','watching')`.

### MD-08: Debounced triggers still create a new incident that the coordinator can never plan

**File:** `apps/ingest_worker/src/ingest_worker/triggers.py:41-62`; `apps/coordinator/src/coordinator/graph.py:106-110`
**Issue:**
- A trigger inside the debounce window still inserts a brand-new incident, and its only trigger gets `coalesced_into` set.
- `ingest_trigger` filters `coalesced_into IS NULL`, so that incident never finds hotspots and always ends in an error.
- The lookback has no upper bound (`detected_at >= :cutoff` without `<= :detected_at`), so out-of-order or future triggers count as "previous".
- No lock guards check-then-insert.
**Fix:** When `previous` exists, attach the trigger to the previous trigger's incident instead of creating one. Add `AND detected_at <= :detected_at`. Serialise with `pg_advisory_xact_lock(hashtext('new_hotspot'))`.

### MD-09: The modified trigger integration test future-dates rows, never deletes them, and pollutes the shared DB

**File:** `tests/integration/test_migrations_and_ingest.py:58-64`, `:84-85`
**Issue:** `detected_at = max(MAX(detected_at), now) + 1 day` moves forward by another day on every run, and the test never deletes its triggers or incidents. Because of MD-08's missing upper bound, every real `new_hotspot` trigger recorded later in the same Compose DB (the one the demo and dev use) sees the future test trigger as "previous" and is coalesced. The coordinator then drops it. The test also asserts `len({incident_id}) == 2`, which locks in the duplicate-incident behaviour from MD-08.
**Fix:** Run inside a transaction that is rolled back, or delete the inserted `triggers` and `incidents` rows in a `finally`. Use a dedicated test schema or database. Fix MD-08 and assert that the coalesced trigger shares the first incident.

### MD-10: LLM output is not checked for truncation or grounding, and is stored and served raw

**File:** `apps/coordinator/src/coordinator/llm/groq_adapter.py:49-52`; `apps/coordinator/src/coordinator/graph.py:394-402`; `apps/api_gateway/src/api_gateway/routers/incidents.py:188`
**Issue:**
- `max_tokens` limits length, but `finish_reason == "length"` is not checked, so a rationale cut off mid-sentence is accepted as authoritative.
- The content is not checked against the deterministic payload (made-up numbers or places), even though the system prompt forbids them.
- `rationale_md` goes to Postgres and back out through the API without sanitising. That is a stored-markdown/HTML injection risk once the Phase 3 UI renders it.
- `llm_rationale_max_tokens` and `llm_request_timeout_s` have no bounds (`config.py:62-63`).
**Fix:**
- Reject or flag `finish_reason != "stop"`.
- Cap the stored length.
- Strip HTML and render markdown safely on the client.
- Add `Field(ge=1, le=2000)` and `Field(ge=1, le=120)`.
- Optionally reject rationales that contain numbers not found in the payload.

### MD-11: The demo and the "real Groq" test default to a retired model, and nothing checks that the LLM actually answered

**File:** `scripts/replay_demo.py:167-168`; `tests/integration/test_coordinator_pipeline.py:134`, `:138-164`; `tests/smoke/test_compose_smoke.py:20-28`
**Issue:** Both default `LLM_MODEL` to `llama3-8b-8192`, which Groq has retired. Neither the integration test nor the demo-exit-0 smoke test checks `is_llm_fallback is False`. Every run therefore falls back quietly while the tests "verify" a real Groq pipeline (PLAN-02 / PLAT-02 evidence).
**Fix:** Default to a current Groq model id taken from config, not a literal. Add `assert state["is_llm_fallback"] is False` to the real-Groq test, and make the demo print or exit non-zero when it falls back unexpectedly.

## Low Issues

### LO-01: Phase 2 numeric settings have no bounds and mostly no environment-variable override

**File:** `packages/wildfire_core/src/wildfire_core/config.py:57-63`, `:85-101`
**Issue:** `fire_grid_resolution_m=0` causes `ZeroDivisionError` (`ca_model.py:87`). An empty `fire_ensemble_seeds` makes `np.stack([])` raise. A negative `dbscan_eps_deg` or `route_fire_penalty_near < 1` gives nonsensical penalties. Only `GROQ_API_KEY` and `OSM_CACHE_PATH` have environment-variable mappings.
**Fix:** Add `Field(gt=0)` / `Field(min_length=1)` / `Field(ge=1.0)`, and map the remaining knobs in `_ENV_MAP` if they are meant to be configurable.

### LO-02: Longitude cells are not scaled by cos(latitude), and `temperature_c` is unused

**File:** `apps/agents/fire/src/agent_fire/ca_model.py:24-25`, `:87-89`, `:117-118`, `:140`
**Issue:** The same `cell_deg` is used for latitude and longitude. At 11.7°N, cells are about 2% narrower east-west than the reported `resolution_m`, so `affected_area_km2` is overstated. `_moisture_factor` accepts `temperature_c` but ignores it.
**Fix:** Use `cell_deg_lon = cell_deg / cos(radians(mid_lat))`. Either use temperature or remove the parameter.

### LO-03: "P90" is actually the union of any 1 of 3 seeds

**File:** `apps/agents/fire/src/agent_fire/ca_model.py:132-134`
**Issue:** With 3 seeds, `freq` can only be 0, 1/3, 2/3 or 1. "P90" (`>=0.1`) is "burned in any seed" and "P50" is "2 of 3". The labels suggest statistical confidence the ensemble does not have.
**Fix:** Document the semantics in the schema or rationale, or raise the seed count (for example 20 or more) so the percentiles mean something.

### LO-04: Audit endpoint returns the oldest entries first and truncates the latest run; unused parameter in `_freshness`

**File:** `apps/api_gateway/src/api_gateway/routers/incidents.py:217-218`, `:77`
**Issue:** `ORDER BY created_at ASC LIMIT :limit` hides the newest runs once an incident has more than 200 entries. The `incident_id` parameter of `_freshness` is unused.
**Fix:** Order by `created_at DESC` (or filter by latest `run_id`), and drop the unused argument.

### LO-05: `replay_demo.py` bootstrapping is fragile and has no environment guard

**File:** `scripts/replay_demo.py:19-22`, `:181-207`
**Issue:**
- `sys.path.insert(0, …)` in a loop reverses the configured precedence.
- It runs at import time.
- It raises `KeyError` if the pytest config moves.
- The script seeds rows into whatever `DATABASE_URL` points at, with no `APP_ENV` check.
- The engine is not disposed on the error path.
**Fix:** Iterate `reversed(...)` or use `sys.path[:0] = [...]`, or better, `uv run` with workspace packages installed. Refuse to run when `APP_ENV` is not `dev` or `test`, and use `try/finally: engine.dispose()`.

### LO-06: `python-dotenv` is imported directly but is only a transitive dependency

**File:** `infra/migrations/env.py:8`; `scripts/replay_demo.py:13`; `pyproject.toml:6-27`
**Issue:** It is available only because `uvicorn[standard]` pulls it in. If uvicorn's extras change, alembic breaks with `ModuleNotFoundError`.
**Fix:** Add `python-dotenv` to `[project].dependencies`.

### LO-07: Migration 0005 back-fills `agent_runs.created_at` with the migration time

**File:** `infra/migrations/versions/0005_phase2_plan_versions.py:37`
**Issue:** Existing Phase 1 rows get `now()` instead of their `started_at`, which corrupts the order of the audit timeline.
**Fix:** Add the column as nullable, run `UPDATE agent_runs SET created_at = COALESCE(started_at, now())`, then `SET NOT NULL` and `SET DEFAULT now()`.

### LO-08: API unit tests match fake SQL by substring, so the `:status IS NULL` bug fixed this session has no regression test

**File:** `apps/api_gateway/tests/test_incidents_api.py:39-51`
**Issue:** `FakeConnection` routes SQL by substring and never executes it. It could not catch the psycopg `AmbiguousParameter` error, and nothing guards the CAST fix.
**Fix:** Add a Compose-gated test that calls `GET /incidents` and `GET /incidents?status=open` against real Postgres.

### LO-09: Unconditional 1 s sleep, and SDK retries multiply the timeout

**File:** `apps/coordinator/src/coordinator/llm/groq_adapter.py:42-48`
**Issue:** `time.sleep(1)` runs on every call, even when the LLM is disabled (see HI-05). The Groq client's default `max_retries=2` makes the worst-case latency about `3 × llm_request_timeout_s`.
**Fix:** Remove the sleep, or rate-limit properly, and pass `max_retries` explicitly.

### LO-10: Weather rows dated in the future count as fresh

**File:** `apps/agents/weather/src/agent_weather/agent.py:44-46`
**Issue:** A negative `age_min` gives `is_stale=False`, so clock skew or a mislabelled forecast row is accepted as current.
**Fix:** Filter `valid_time <= now()` in the query (see HI-04), or treat a negative age beyond a small tolerance as invalid.

---

_Reviewed: 2026-10-17T03:12:49Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_

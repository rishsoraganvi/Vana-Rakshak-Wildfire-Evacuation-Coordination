---
phase: 02-mvp-detection-to-route
scope: gap-closure plans 02-04..02-09 (git diff 146f12d..HEAD -- . ':!.planning')
reviewed: 2026-10-17T06:05:00Z
depth: deep
files_reviewed: 26
files_reviewed_list:
  - .github/workflows/ci.yml
  - apps/agents/fire/src/agent_fire/ca_model.py
  - apps/agents/fire/src/agent_fire/ensemble.py
  - apps/agents/fire/tests/test_ca_model.py
  - apps/agents/routing/src/agent_routing/__init__.py
  - apps/agents/routing/src/agent_routing/costs.py
  - apps/agents/routing/src/agent_routing/router.py
  - apps/agents/routing/tests/test_router.py
  - apps/agents/weather/src/agent_weather/agent.py
  - apps/agents/weather/tests/test_weather_agent.py
  - apps/coordinator/src/coordinator/audit.py
  - apps/coordinator/src/coordinator/graph.py
  - apps/coordinator/src/coordinator/llm/groq_adapter.py
  - apps/coordinator/src/coordinator/runner.py
  - apps/coordinator/src/coordinator/state.py
  - apps/coordinator/tests/test_groq_adapter.py
  - apps/coordinator/tests/test_pipeline_offline.py
  - config/defaults.yaml
  - docker-compose.yml
  - packages/wildfire_core/src/wildfire_core/config.py
  - packages/wildfire_core/src/wildfire_core/schemas/phase2.py
  - packages/wildfire_core/tests/test_phase2_schemas.py
  - scripts/replay_demo.py
  - tests/integration/test_coordinator_pipeline.py
  - tests/unit/test_compose_bindings.py
  - tests/unit/test_config.py
findings:
  critical: 1
  warning: 10
  info: 9
  total: 20
status: issues_found
---

# Phase 02 Gap Closure (02-04..02-09): Code Review Report

**Reviewed:** 2026-10-17T06:05:00Z
**Depth:** deep. I traced calls across modules and ran small offline probes from the session scratchpad: CA spread metrics, routing edge cases, and SQL compilation of the weather query. The offline suite also ran: `pytest apps packages tests/unit` gave 104 passed, 1 skipped. The live/COMPOSE_SMOKE suite was not run.
**Files Reviewed:** 26
**Status:** issues_found

**Severity mapping.**
- **critical** = BLOCKER: wrong behaviour, a security problem or a broken ship path. It must be fixed before shipping.
- **warning** = should fix: weaker correctness or robustness.
- **info** = minor quality issue.

The original review used critical/high/medium/low. "High" maps to **critical** when it is a definite break of correctness, security or the ship path, and to **warning** when it is a degraded edge case. No new finding met the bar for a security-critical rating.

## Summary

Each gap plan implements the fix the original review recommended, and the probes confirm the main safety fixes:

- **CR-01 (wind direction).** Wind *from* 270° now spreads the fire toward 80–97°. Wind from 0° spreads it toward 184°.
- **CR-02 (edge exposure).** Exposure is now tested on the full edge geometry with `intersects`.
- **HI-01 (routes through fire).** Blocked edges are hidden first, then a least-blocked fallback runs with finite costs. A probe confirmed it picks the path with the least exposure.
- **HI-05 (LLM gating).** The LLM is now gated on `llm_enabled`, provider, model and key.
- **HI-03 (fake weather).** Weather is no longer invented.
- **Security.** The weather query is fully parameterised. The compiled SQL binds every value, including a hostile `origin` string. No secret reaches audit rows, warnings, or the LLM payload.

**One fix breaks CI (CR-01 below).** HI-06 now requires `POSTGRES_PASSWORD` and drops `change_me`. The CI `alembic upgrade` step was not updated. It has no `DATABASE_URL`, and no `.env` exists in CI, so it falls back to the `change_me` URL in `alembic.ini`. That fails authentication, so the compose-smoke job cannot pass.

The other findings are where the fixes interact:
- One weather snapshot, taken at the mean of all hotspots, is now applied to every cluster that is simulated separately.
- The weather query has no age limit.
- No ingested weather row can match the query, so non-demo incidents can no longer get a plan.
- With gpt-oss reasoning tokens counted against the 400-token cap, a truncated rationale is accepted as a real one.
- The demo turns the LLM on even when config turns it off.
- The spread rate depends on grid resolution.

## Status of original findings

| ID | Verdict | Notes |
|----|---------|-------|
| CR-01 | **fixed** | `_wind_factor` turns the FROM direction into the downwind bearing (`ca_model.py:19-28`), and the probe confirms it. `scipy.convolve2d` flips the kernel, which is what makes the kernel orientation correct. |
| CR-02 | **fixed** | Exposure uses the full edge geometry or the chord between endpoints, with `intersects`; polygons are prepared (`costs.py:17-66`). |
| CR-03 | **fixed** | Every cluster is simulated, and routing uses `unary_union` of the current and P50-1h polygons. `CoordinatorPlan.fire_results` requires at least one result. Caveat: every cluster shares one weather snapshot (WR-01). P90 and longer horizons are still ignored (original MD-02, not claimed). |
| HI-01 | **fixed** | Origin is `nearest_node_outside`. Dijkstra hides blocked edges first, then falls back to finite costs. The blocked candidate kept is the one with the least exposure. Caveats: WR-08 (relocating the origin is invisible in `RouteResult`) and WR-09 (connectivity is not checked). |
| HI-02 | **fixed (metric)** | Distance is measured from the snapped ignition centre, using front advance over the real horizon. Direction is None below one cell. The rate the model produces still scales with grid resolution (WR-07). |
| HI-03 | **fixed** | No invented snapshot: the run is skipped with a warning, and NULL rows are filtered out instead of being set to 0. Side effect: WR-03. |
| HI-04 | **fixed** | Filters on a lat/lon box, provider, origin, `valid_time <= now` and complete rows; sorts by distance, then recency. Also closes LO-10. Caveats: WR-01 and WR-02. |
| HI-05 | **fixed** (adapter) | The gate runs before any client is built and before the sleep (`groq_adapter.py:129-141`). The demo overrides the config gate (WR-05). |
| HI-06 | **fixed, with a regression** | Compose binds to loopback, the password is required, and the default credential is gone from `defaults.yaml` and `Settings`. The CI migration step is now broken (CR-01), and `alembic.ini` still contains `change_me` (IN-01). |
| MD-11 | **partially fixed** | The model now comes from config (`openai/gpt-oss-20b`), and the integration test asserts `is_llm_fallback is False` and checks the metadata. But the demo still exits 0 when it falls back. `tests/smoke/test_compose_smoke.py:19-28` checks only the exit code, and a blank `LLM_ENABLED` silences the demo warning (WR-05). |
| PLAT-02 model_metadata (MD-06 sub-item) | **fixed** | `generate_rationale` returns provider, model, usage, finish_reason and fallback reason. `audit.py:26-28` `json.dumps` the value before `CAST(... AS jsonb)`. The dedicated `llm_model`, `tokens_in` and `tokens_out` columns are still NULL (IN-04). |

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: CI compose-smoke migration step authenticates with the removed `change_me` password, so the job fails

**File:** `.github/workflows/ci.yml:26,37,41`; `infra/migrations/alembic.ini:4`; `infra/migrations/env.py:16-18`
**Issue:** HI-06 sets `POSTGRES_PASSWORD: ci-ephemeral-password` at job level, so the container's password is now that value.
- The step `uv run alembic -c infra/migrations/alembic.ini upgrade head` (line 37) has no `DATABASE_URL`. Only the later pytest step sets it (line 41).
- `.env` is gitignored and not tracked, so `env.py`'s `load_dotenv` finds nothing.
- Alembic therefore uses `sqlalchemy.url = postgresql+psycopg://wildfire:change_me@localhost:5432/wildfire` from `alembic.ini`.
- The postgis image uses scram password auth for TCP connections from the host, so the migration fails authentication.
- The compose-smoke job cannot reach the integration tests. Before HI-06, the compose default `change_me` matched `alembic.ini` by accident.

`tests/unit/test_compose_bindings.py` checks only `docker-compose.yml`, so CI was not covered.
**Fix:** Set `DATABASE_URL` once at job level and remove the placeholder credential:
```yaml
  compose-smoke:
    env:
      POSTGRES_PASSWORD: ci-ephemeral-password
      DATABASE_URL: postgresql+psycopg://wildfire:ci-ephemeral-password@localhost:5432/wildfire
    steps:
      ...
      - run: uv run alembic -c infra/migrations/alembic.ini upgrade head
      - run: uv run pytest tests/integration -m compose -q
        env:
          COMPOSE_SMOKE: "1"
          REDIS_URL: redis://localhost:6379/0
```
In `alembic.ini`, replace the URL with a placeholder that cannot authenticate, or make `env.py` raise when `DATABASE_URL` is unset.

## Warnings

### WR-01: One weather snapshot, taken at the mean of all hotspots, drives every cluster's fire simulation

**File:** `apps/coordinator/src/coordinator/graph.py:198-220`, `:274-288`
**Issue:** CR-03 now simulates every cluster, but `run_weather` still makes one lookup, at the mean of *all* hotspots. Every cluster's CA run then uses that one snapshot.
- The AOI is about 140 × 100 km. Two clusters at opposite ends get weather from a point between them, which may match neither.
- Worse, the mean may be more than the lookup radius from any observation, while each cluster has weather nearby. The lookup then raises `LookupError` and the whole run ends with no plan.

The HI-04 location scoping does not reach the per-cluster model that CR-03 introduced.
**Fix:** Look up weather per cluster at `cluster.centroid_lat/lon`, store `weather_snapshots: dict[cluster_id, WeatherSnapshot]`, and pass each cluster its own snapshot in `run_fire_ca`. Skip only the clusters that have no weather, and add a warning for each.

### WR-02: Weather lookup sorts by distance first and has no age limit, so a stale row nearby beats a fresh one

**File:** `apps/agents/weather/src/agent_weather/agent.py:34-56`
**Issue:**
- `ORDER BY squared distance, valid_time DESC` returns the newest row at the *nearest coordinates*, even if it is days old, ahead of a 10-minute-old row one grid cell further away. Open-Meteo rows carry the grid-snapped `payload.latitude/longitude`, so nearby points have different coordinates.
- There is no lower bound on `valid_time`. An arbitrarily old observation still drives the CA; it is only labelled `is_stale`, and `run_fire_ca` goes ahead with a warning.
- The filter is a ±50 km square, so its corners reach about 70 km, but the error says "within 50 km".
**Fix:** Add `obs.c.valid_time >= now - timedelta(minutes=max_age_min)`, using a configurable `weather_max_age_min`. Sort by recency bucket, then distance, or reject candidates older than the stale threshold before ranking by distance. Either filter by true distance (haversine in `WHERE`) or reword the message to "within a ±50 km box".

### WR-03: No ingested weather row can satisfy the coordinator's query, so non-demo incidents can never produce a plan

**File:** `apps/ingest_worker/src/ingest_worker/weather/parser.py:15,47`; `apps/agents/weather/src/agent_weather/agent.py:36,59-60`; `apps/coordinator/src/coordinator/graph.py:223-229`, `:462-465`
**Issue:**
- `parse_open_meteo` is the only weather writer. It stores every row with `is_forecast=True` and `origin='replay'` by default.
- The query requires `is_forecast IS false` and `origin = <incident origin>`.
- The only rows that match are inserted by hand in `scripts/replay_demo.py:96-107`.
- HI-03 removed the invented observation, so every `live`, `manual` or `simulated` incident now ends at `assemble_plan` with "Cannot persist a draft without fire and weather results".

Before these plans, such incidents produced a plan, although on invented data. This gap existed before, but the gap plans turned it from bad data into no plan at all, and nothing in the tests or docs warns about it.
**Fix:** Have the ingest path write observations with `is_forecast=False` for hours `<= issued_at`, with the real origin of the data. Alternatively, let the weather agent accept the nearest-hour forecast row with `is_forecast=True` and label it as such. Add an integration test that ingests through `parse_open_meteo` and then runs `run_weather`.

### WR-04: gpt-oss reasoning tokens count against the 400-token cap, and a truncated rationale is accepted as non-fallback

**File:** `apps/coordinator/src/coordinator/llm/groq_adapter.py:143-158`, `:160`, `:171-187`; `config/defaults.yaml` (`llm_rationale_max_tokens: 400`)
**Issue:**
- 02-06 switched the default to `openai/gpt-oss-20b` and replaced `max_tokens` with `max_completion_tokens=400`.
- For reasoning models, hidden reasoning tokens count against `max_completion_tokens`, even with `reasoning_effort="low"` and `include_reasoning=False`.
- `finish_reason` is recorded in metadata but never checked. A rationale cut off mid-sentence (`finish_reason == "length"`) is returned with `is_fallback=False`, stored as the plan's `rationale_md`, and passes the new "LLM did not fall back" assertions.

The original MD-10 flagged this, and the model switch makes it much more likely.
**Fix:**
```python
if finish_reason != "stop":
    raise ValueError(f"Groq rationale incomplete (finish_reason={finish_reason})")
```
Raise the default cap for reasoning models (for example 1024), or keep a separate content budget. Add a unit test with `finish_reason="length"`.

### WR-05: Replay demo overrides `llm_enabled: false` from config; a blank `LLM_ENABLED` silently disables the LLM and hides the fallback

**File:** `scripts/replay_demo.py:181-185`, `:237-241`; `tests/smoke/test_compose_smoke.py:19-28`
**Issue:**
- `os.environ.setdefault("LLM_ENABLED", "true")` means the demo sends fire, weather and route data to Groq even when the operator set `llm_enabled: false` in config. Only an exported environment variable wins. HI-05 was about config control of data egress; the demo makes config advisory again.
- In the other direction, `load_dotenv` runs first. If `.env` contains `LLM_ENABLED=` (blank), `setdefault` does nothing. The 02-06 blank-as-unset rule in `config.py:116-119` then falls back to `false`.
- The demo then makes no LLM call, prints `LLM Fallback : Yes (llm_disabled)`, and skips the stderr warning because `settings.llm_enabled` is False. It still exits 0, and the smoke test passes. This is the silent fallback MD-11 was meant to remove.
**Fix:** Do not change `LLM_ENABLED` in the demo; require config or env to enable it, and fail fast with a clear message if it is disabled. Exit non-zero when `llm_metadata["is_fallback"]` is true, unless `--allow-fallback` is passed. Have the smoke test assert that `"LLM Fallback  : No"` is in stdout.

### WR-06: `POSTGRES_PASSWORD` is put into `DATABASE_URL` without URL encoding

**File:** `docker-compose.yml:37`
**Issue:** The password is now operator-chosen and required. Characters such as `@ : / ? # % [ ]`, which strong-password generators commonly produce, are inserted into `postgresql+psycopg://user:<pw>@postgres:5432/db` as raw text. The URL then parses wrong: the host becomes the text after `@`, and `#` starts a fragment. The API fails to connect with a confusing error, and part of the password can appear in the "could not translate host name" message. `.github/workflows/ci.yml:41` has the same pattern.
**Fix:** Document that the password must be URL-safe, or have the API build the URL from separate `POSTGRES_USER/PASSWORD/HOST/DB` variables with `sqlalchemy.engine.URL.create(...)`, which escapes the password. Add a unit test that rejects passwords that are not URL-safe in compose-driven settings.

### WR-07: The reported spread rate scales with grid resolution, so the "m/h" figure is a CA artefact

**File:** `apps/agents/fire/src/agent_fire/ca_model.py:16`, `:70-75`, `:117-124`
**Issue:** The HI-02 metric now measures front advance correctly, but the model it measures advances about one cell per 6-minute step whatever the cell size. Probe: identical inputs with calm wind and RH 30 give `spread_rate_m_per_h=387.25` at 250 m and `729.49` at 500 m. P50-3h area moves from 4.81 to 11.75 km² as well. These numbers go into `plan_data` and the LLM payload as deterministic facts, and `fire_grid_resolution_m` is a config knob.
**Fix:** Scale the per-step ignition probability, or the step duration, with `resolution_m`, for example `STEP_DURATION_MIN = base_min * resolution_m / 250`. Add a test that the rate stays within a tolerance across 250 m and 500 m. At minimum, label the rate as model-relative in the schema description and the rationale prompt.

### WR-08: The relocated route origin is not recorded in `RouteResult`; a route is rated "safe" though its first leg crosses the active fire

**File:** `apps/coordinator/src/coordinator/graph.py:334-355`; `apps/agents/routing/src/agent_routing/router.py:138-151`
**Issue:** HI-01 moves the origin to the nearest road node outside the union perimeter.
- `osm_node_path` starts at that node, so `safety_classification` can be `safe`.
- But the cluster centroid, which is the route's nominal origin (`origin_cluster_id`), is inside the fire. The leg from the centroid to the relocated node goes through the current perimeter.
- The only record of this is a free-text plan warning. `RouteResult` has no field for it, so a downstream consumer (the Phase 3 UI, the LLM rationale) sees a `safe` route "from cluster X".

This brings back, one level up, the "route starting inside the fire rated safe" problem that CR-02 described.
**Fix:** Add `origin_relocated: bool` and `origin_offset_m: float` to `RouteResult`. When relocated, cap the classification at `caution` (or `blocked` if the offset path intersects the perimeter), and include the flag in the LLM route summary.

### WR-09: `nearest_node_outside` checks neither connectivity nor egress

**File:** `apps/agents/routing/src/agent_routing/router.py:27-50`; `apps/coordinator/src/coordinator/graph.py:337-403`
**Issue:** The origin is chosen only by distance among uncovered nodes.
- On a bbox-truncated OSM graph, the nearest uncovered node can be in a small disconnected component, such as a track cut off by the AOI clip. `compute_route` then returns None for every exit, and the plan says "No graph route found", although the next-nearest outside node would route safely.
- Likewise, a dead-end node whose only edge intersects the perimeter forces the blocked fallback.
**Fix:** Restrict candidates to nodes in the same weakly connected component as at least one exit. Or iterate over the k nearest outside nodes and keep the first that gives a non-blocked route, recording the choice as in WR-08.

### WR-10: One cluster's failure drops routing (or the whole run) for every cluster

**File:** `apps/coordinator/src/coordinator/graph.py:279-288`, `:310-405`
**Issue:** CR-03 multiplies the number of CA runs and routing loops per incident.
- `run_fire_ca` has no error handling, so an exception in any cluster's `compute_fire_spread` aborts the LangGraph run before `write_audit`, and nothing is saved (original MD-06).
- In `compute_route_node`, one `try/except` wraps the loop over all clusters. An exception for one cluster, such as `KeyError` on a node missing `travel_time`, or the `RuntimeError`/`TypeError` raised inside `compute_route`, throws away the routes already computed for the others and records only `Route computation unavailable: <Name>`.
**Fix:** Wrap each cluster's CA call and each cluster's routing in its own `try/except`. Record a warning naming the cluster, and continue. Keep the outer `try` only for loading the graph and applying penalties.

## Info

### IN-01: `alembic.ini` still contains the `change_me` credential

**File:** `infra/migrations/alembic.ini:4`
**Issue:** HI-06 removed the default password everywhere else. This placeholder is the direct cause of CR-01, and the compose-bindings test does not cover it.
**Fix:** Use a placeholder that cannot authenticate (`postgresql+psycopg://set-DATABASE_URL@invalid/none`), or raise in `env.py` when `DATABASE_URL` is unset.

### IN-02: `Settings.postgres_password` and its `POSTGRES_PASSWORD` mapping are dead code

**File:** `packages/wildfire_core/src/wildfire_core/config.py:52`, `:98`
**Issue:** No code reads `settings.postgres_password`. The field adds a second place where the password can be configured, and it can drift from `DATABASE_URL`.
**Fix:** Remove the field and its mapping, or build `database_url` from it (see WR-06).

### IN-03: Fallback `model_metadata` has a different shape depending on the path

**File:** `apps/coordinator/src/coordinator/graph.py:425-433` versus `apps/coordinator/src/coordinator/llm/groq_adapter.py:39-59`
**Issue:** On the `inputs_unavailable` path, the node builds the metadata dict by hand and leaves out `reasoning_effort`. Consumers of the audit JSON see an inconsistent schema.
**Fix:** Expose `_metadata` (or a public `fallback_metadata(settings, reason)`) and use it in the node.

### IN-04: `agent_runs.llm_model`, `tokens_in` and `tokens_out` columns are still never populated; every row is `status='succeeded'`

**File:** `apps/coordinator/src/coordinator/audit.py:35-43`
**Issue:** The metadata now exists in `model_metadata` JSON, but the typed columns from migration 0004 stay NULL. An LLM fallback or failed node is still written as `succeeded` (original MD-06, not claimed by these plans).
**Fix:** Map `model_metadata["model"]` and `usage.prompt_tokens/completion_tokens` into the columns, and derive `status` from `is_fallback` or the node's error.

### IN-05: Fallback rationale sums `affected_area_km2` across clusters

**File:** `apps/coordinator/src/coordinator/llm/groq_adapter.py:111-113`
**Issue:** Clusters whose P50 polygons overlap are counted twice, so the deterministic fallback text overstates the affected area. `replay_demo.py:153` does the same.
**Fix:** Report the area of the `unary_union` of the P50-3h polygons, or list areas per cluster.

### IN-06: The `plan_data` key changed from `fire_result` to `fire_results` without a schema version

**File:** `apps/coordinator/src/coordinator/graph.py:467-479`; `packages/wildfire_core/src/wildfire_core/schemas/phase2.py:124`
**Issue:** Existing `plan_versions.plan_data` rows use the old singular key. No reader exists today, but the Phase 3 UI or replay tooling will meet both shapes.
**Fix:** Add `plan_schema_version` to `CoordinatorPlan`, or migrate the old rows.

### IN-07: `llm_model` is not stripped before the gpt-oss check and the API call

**File:** `apps/coordinator/src/coordinator/llm/groq_adapter.py:136`, `:145`, `:153`
**Issue:** The gate uses `.strip()`, but `startswith("openai/gpt-oss")` and `model=` use the raw value. With `LLM_MODEL=" openai/gpt-oss-20b"` the reasoning parameters are dropped and Groq rejects the model id, which ends in a fallback.
**Fix:** `model = settings.llm_model.strip()` once, and use it everywhere. Or strip the value in `load_settings`.

### IN-08: Exit-node selection uses `contains`, but origin selection uses `covers`

**File:** `apps/coordinator/src/coordinator/graph.py:64`
**Issue:** A node exactly on the union perimeter boundary can be chosen as an exit, but every edge into it `intersects` the perimeter and is blocked, so routes to it fall back to `blocked`. Exits inside P50 also remain possible (original MD-02).
**Fix:** Use `covers` (or `intersects`) here as well, and also exclude exits inside the union P50/P90.

### IN-09: The test locks in the unconditional 1 s sleep

**File:** `apps/coordinator/tests/test_groq_adapter.py:84-90`
**Issue:** `assert sleep_calls == [1]` makes original LO-09 (fixed sleep, and SDK `max_retries` multiplying the timeout) harder to fix. `Groq(...)` is still built with the default `max_retries=2`, so the worst-case latency is still about 3 × `llm_request_timeout_s`.
**Fix:** Pass `max_retries` explicitly, replace the sleep with real rate limiting, and assert on behaviour instead of the sleep call.

---

_Reviewed: 2026-10-17T06:05:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_

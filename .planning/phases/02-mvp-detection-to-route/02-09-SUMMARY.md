---
phase: 02-mvp-detection-to-route
plan: 09
subsystem: weather-coordinator
tags: [weather, coordinator, gap-closure, hi-03, hi-04, lo-10, plan-01]
requires: [02-07]
provides:
  - "build_snapshot_query and get_weather_snapshot(..., origin, provider, max_distance_km, now): bbox, provider, origin and valid_time <= now filters, nearest then newest ordering"
  - "No NULL-to-zero coercion; incomplete rows skipped; LookupError when no complete row matches"
  - "run_weather queries at the hotspot mean location, for the incident origin and settings.weather_provider"
  - "Weather unavailable leaves weather_snapshot None; no fabricated observation, no plan persisted, all 8 audit rows flushed"
affects: [02-VERIFICATION]
tech-stack:
  added: []
  patterns: ["query builder separated from execution for SQL-text assertions", "fail-safe: no plan rather than a plan on invented inputs"]
key-files:
  created:
    - apps/agents/weather/tests/test_weather_agent.py
  modified:
    - apps/agents/weather/src/agent_weather/agent.py
    - apps/coordinator/src/coordinator/graph.py
    - apps/coordinator/tests/test_pipeline_offline.py
key-decisions:
  - "DEFAULT_MAX_DISTANCE_KM = 50.0 stays a module constant (configurable radius is LO-01, deferred)"
  - "Origin is read with the same SQL text assemble_plan uses, so no new fake routing was needed"
  - "Downstream nodes unchanged: existing None-weather guards produce the no-plan outcome"
requirements-completed: []
status: complete
duration: 25min
completed: 2026-10-17
actuals:
  tokens: 9000
  tasks: 2
  commits: 4
---

# Phase 2 Plan 09: Scoped weather lookup, no fabricated weather Summary

The weather lookup now returns only complete, non-future observations near the incident, from the configured provider and the incident's own origin, and the Coordinator plans nothing rather than inventing an observation stamped now when none exists.

## Tasks

| # | Task | Commits |
|---|------|---------|
| 1 | Tracer: location/provider/origin/time-scoped lookup, no NULL coercion, offline plus live Postgres proof (HI-04, HI-03) | 9dffb23 (RED), 9e100c2 |
| 2 | run_weather: incident-scoped lookup, no fabricated observation (HI-03, HI-04 wiring) | f510d69 (RED), 9a135cf |

Tracer gate (auto mode active): the tracer's verify was re-run after the commit, including the live-gated test against real Postgres (6 passed), so expansion proceeded.

## What changed

- agent.py: `build_snapshot_query` (lat/lon BETWEEN bounds with cos(lat)-scaled longitude, provider and origin equality when given, `valid_time <= now`, four `IS NOT NULL` filters, ordered by planar distance then recency, limit 1). `get_weather_snapshot` takes keyword-only `origin`, `provider`, `max_distance_km`, `now`; raises `LookupError` naming origin and provider; plain `float()` conversions; stale when age > 90 min.
- graph.py `run_weather`: location is the mean of hotspot lat/lon (AOI centre only when none); origin from `SELECT origin::text FROM incidents`; on any exception `weather_snapshot` is None, the warning "... No weather observation was fabricated." is appended and the audit output is `{"weather_snapshot": null, "error": <ExceptionName>}`. Audit inputs now include `origin` and `provider`. Synthetic `WeatherSnapshot` and the datetime/UTC import are removed.
- Tests: 6 new tests in test_weather_agent.py (5 offline, 1 live-gated); 2 new coordinator tests; existing patches accept `**kwargs`; settings carry `weather_provider`.

## Verification

- Offline full suite: 104 passed, 8 skipped (baseline 97/7; the 8th skip is the new live-gated test). Coordinator tests 24 passed.
- Live (`COMPOSE_SMOKE=1`, Compose up): weather tests 6 passed (origin and location preference proven against real Postgres); `tests/integration/test_coordinator_pipeline.py` and `tests/smoke` together 9 passed (Groq answered, no fallback; the seeded replay weather row at (11.72, 76.64), origin replay, provider open-meteo is still found by the scoped query).
- `scripts/replay_demo.py` (LLM_ENABLED=true LLM_PROVIDER=groq): draft plan, 1 cluster, 1 route (blocked), `LLM Model : groq/openai/gpt-oss-20b`, `LLM Fallback : No`, 8 audit entries.
- ruff clean on apps/coordinator and apps/agents/weather; mypy on routing, coordinator and weather src: 0 non-import-untyped errors. Acceptance greps: `or 0.0` 0, `build_snapshot_query` 1, `valid_time=datetime.now` 0, `provider=settings.weather_provider` 1.

## Deviations from Plan

**1. [Rule 3 - Blocking] Lint/format fixes** while editing: `Select[Any]` return annotation for mypy (`type-arg`), import ordering, an over-long monkeypatch line in the test file, and ruff format also corrected one mis-indented dict entry in graph.py `assemble_plan` (whitespace only). Otherwise the plan executed as written.

## Known Stubs

None.

## Threat Flags

None. T-02-09-01 (origin/location/provider/time filters, live test), T-02-09-02 (no fabrication, no plan, no valid_time in audit) and T-02-09-03 (IS NOT NULL, no zero coercion) are covered by tests.

## Deferred (per plan)

LO-01 (configurable weather radius). LO-10 (future-dated rows) is closed as a side effect of the `valid_time <= now` filter.

## Self-Check: PASSED

Files exist: test_weather_agent.py, agent.py, graph.py, test_pipeline_offline.py. Commits 9dffb23, 9e100c2, f510d69, 9a135cf are in git log.

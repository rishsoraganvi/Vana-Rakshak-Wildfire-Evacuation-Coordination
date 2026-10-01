# Research Summary: Vana-Rakshak

**Date:** 2026-10-01  
**Source:** Supplied `generatedPlan` folder  
**Mode:** Inline fallback; GSD research subagents are not installed in this runtime.

## Findings

- The domain is a safety-sensitive geospatial decision-support workflow, so the architecture must separate deterministic computation from LLM orchestration and require human approval before dissemination.
- The supplied plan selects a practical stack for the domain: FastAPI/Pydantic, LangGraph, NumPy/Numba, GeoPandas/Shapely/Rasterio, OSMnx/NetworkX, PostgreSQL/PostGIS/pgvector, Redis, React/MapLibre, and Docker Compose.
- The primary evaluation risks are stale/false-positive satellite data, uncalibrated fire spread, shelter-capacity uncertainty, LLM hallucination, provider outages, and accidental operational overclaiming.
- The highest-value first slice is a replayable hotspot-to-route path with seeded fire forecasts, weather, audit logging, and deterministic fallback. Shelter matching, review, dissemination, and dashboard work should build on that contract.

## Planning Implications

1. Establish schemas, configuration, clocks, AOI decisions, and fixtures before geospatial or agent work.
2. Keep fire spread, routing, capacity, and dispatch behind typed deterministic tool contracts.
3. Treat freshness, uncertainty, simulation origin, provenance, and approval state as first-class data.
4. Use archived/replay data for development so external API latency and keys do not block the MVP.
5. Test safety invariants with property-based tests and the complete review-to-dissemination path with integration/e2e tests.

## Source Gaps to Resolve During Execution

- Verify current NASA FIRMS source names, API limits, and attribution requirements against official documentation before implementation.
- Select the pilot settlement cluster and final AOI geometry.
- Confirm permitted map tile provider and data licenses.
- Choose the LLM provider/model only after cost, latency, and structured-output behavior are evaluated.
# Phase 2: MVP Detection to Route — Context

**Gathered:** 2026-10-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver an end-to-end auditable path from a hotspot observation (real or replayed) to a basic evacuation route suggestion for the Bandipur pilot cluster. Phase 2 proves the trigger-to-route loop exists and is fully auditable. It does NOT implement shelter capacity matching (Phase 3), human review/approval APIs (Phase 4), the dashboard (Phase 5), or vehicle/drone simulation (Phase 6).

</domain>

<decisions>
## Implementation Decisions

### OSM Road Graph

- **D-01:** Download and cache the Bandipur AOI OSM road graph at service startup using OSMnx. Store as serialized GraphML at `data/osm/bandipur_road_graph.graphml`. If the file exists, load from disk (no re-download). Enables offline replay without network dependency at run time.
- **D-02:** Cache path and AOI query parameters are config-driven. CI does not download OSM; a pre-baked fixture GraphML is committed to `tests/fixtures/osm/`.

### Fire Spread CA Model

- **D-03:** NumPy-based 2D grid CA on a rasterized AOI. Wind direction/speed from Weather agent adjusts the spread kernel. Run 3 seeded ensemble members (seeds 42, 43, 44) for P50/P90 perimeters at 1h, 3h, 6h horizons.
- **D-04:** Numba JIT deferred to Phase 6. Phase 2 NumPy CA targets the pilot AOI (~50x50 km at 250m resolution).
- **D-05:** Output: `FireSpreadResult` with current_perimeter, p50_perimeter, p90_perimeter, affected_area_km2, spread_direction_deg, spread_rate_m_per_h, confidence, settlements_at_risk with ETA.

### Route Utility

- **D-06:** NetworkX Dijkstra weighted by `(fire_penalty x distance_m)`. Fire penalty per edge: 1.0 safe, 5.0 near-perimeter, inf blocked (inside current perimeter).
- **D-07:** Output: ordered OSM node IDs, total distance (m), travel time (s), safety classification (safe/caution/blocked), flagged fire-penalty edges.

### LLM / Coordinator v0

- **D-08:** LLM provider: **Groq**, model: `llama3-8b-8192` (configurable via `settings.llm_model`). Groq is always called in all test modes; `GROQ_API_KEY` required in CI.
- **D-09:** LLM responsibility strictly bounded: receives structured FireSpreadResult + WeatherSnapshot + RouteResult, returns only a grounded rationale string (<=400 tokens). All numeric outputs are deterministic.
- **D-10:** Coordinator is a LangGraph state machine: ingest_trigger -> run_weather -> run_fire_ca -> cluster_hotspots -> compute_route -> generate_rationale (LLM) -> assemble_plan -> write_audit.
- **D-11:** LLM fallback template: "[DETERMINISTIC FALLBACK] Fire spread CA: {perimeter summary}. Recommended route: {route summary}. Human review required."

### Audit

- **D-12:** Every Coordinator node writes an append-only `audit_entry` row: incident_id, run_id (UUID), node_name, inputs_json, outputs_json, latency_ms, model_metadata, created_at. Satisfies PLAT-02.

### Trigger Lifecycle

- **D-13:** Incident row transitions: detected -> processing -> draft_plan (Phase 2). pending_review transition belongs to Phase 4.

### Read-Only API

- **D-14:** Phase 2 exposes under /api/v1:
  - GET /api/v1/incidents
  - GET /api/v1/incidents/{id}/plan
  - GET /api/v1/audit/{incident_id}

### Replay / Demo Script

- **D-15:** Standalone script at `scripts/replay_demo.py`. Seeds FIRMS fixture -> triggers Coordinator -> polls until draft_plan -> prints ASCII summary table -> exits 0 on success.

### Testing (PLAT-06)

- **D-16:** Pytest: unit (CA model, clustering, routing, models), integration (real Groq + DB, marked @pytest.mark.integration), Compose smoke (migrations + health + replay_demo.py exit 0, marked @pytest.mark.smoke). Both integration and smoke run in CI with GROQ_API_KEY.

### Hotspot Clustering

- **D-17:** DBSCAN (eps=0.01 deg, min_samples=3) to cluster FIRMS hotspots within AOI. Each cluster: centroid, point count, mean FRP, bounding bbox.

</decisions>

<specifics>
## Specific Notes

- New Pydantic models: FireSpreadResult, RouteResult, HotspotCluster, CoordinatorState, AuditEntry.
- OSM fixture for tests: minimal 2-node/3-edge GraphML covering stub Bandipur route.
- Groq rate limit mitigation: 1-second sleep before LLM call in replay script.
- GROQ_API_KEY must be added to .env.example and EnvSetup.md as required for Phase 2+.
- Package layout: fire_agent in packages/fire_agent/, routing in packages/routing/, Coordinator in packages/coordinator/.

</specifics>

<deferred>
## Deferred Ideas

- Shelter capacity matching and k-paths routing — Phase 3
- Human review/approval/dissemination APIs — Phase 4
- Dashboard and replay UI — Phase 5
- Numba JIT, vehicle/drone simulation, calibration — Phase 6
- Kannada translation — open decision, deferred
- Final AOI polygon replacement — Bandipur bbox remains for Phase 2
- Literature baselines (EVAL-01) — Phase 6

</deferred>

<canonical_refs>
## Canonical References

- .planning/ROADMAP.md — Phase 2 goal, PLAN-01, PLAN-02, PLAT-02, PLAT-06
- .planning/REQUIREMENTS.md — acceptance criteria
- generatedPlan/TechSpec.md — Coordinator state machine, LangGraph graph, fire CA spec, routing agent
- generatedPlan/Schema.md — incidents, audit_entries, plan_versions tables
- generatedPlan/API.md — /api/v1 conventions
- generatedPlan/Rules.md — deterministic-vs-LLM rules, safety S1-S9
- generatedPlan/FolderStructure.md — package layout
- .planning/phases/01-foundations-and-data-contracts/01-CONTEXT.md — locked Phase 1 decisions
- .planning/phases/01-foundations-and-data-contracts/01-VERIFICATION.md — Phase 1 guarantees

</canonical_refs>

---

*Phase: 02-mvp-detection-to-route*
*Context gathered: 2026-10-06*

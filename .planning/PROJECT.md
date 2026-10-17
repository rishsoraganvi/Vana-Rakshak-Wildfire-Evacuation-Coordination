# Vana-Rakshak: Wildfire Evacuation Coordination

## What This Is

Vana-Rakshak is a decision-support prototype for the Bandipur, Nagarahole, and BRT Tiger Reserve corridor in Karnataka. It connects satellite fire detections and weather data to deterministic fire-risk, routing, shelter, and dispatch computations coordinated by specialist agents. Incident commanders review, edit, and explicitly approve an integrated evacuation plan before simulated dissemination.

The system is for Forest Department, district administration, emergency dispatch, police/traffic, community liaison, and project operators. It is not an operational emergency system and does not replace official authority.

## Core Value

A human reviewer can quickly understand and safely approve or correct a traceable evacuation plan built from current hazard, route, shelter, and resource data.

## Requirements

### Validated

- ✓ Basic auditable evacuation route from a hotspot or replay event for the pilot cluster (fire CA ensemble with P50/P90, fire-aware routing, LangGraph Coordinator, 8-node audit trail, deterministic LLM fallback) — Phase 2

### Active

- [ ] Monitor FIRMS hotspots and weather for a configurable area of interest with freshness and degraded-mode signals.
- [ ] Detect incidents, forecast fire spread with seeded uncertainty bands, and identify settlements at risk.
- [ ] Coordinate deterministic specialist tools into capacity-aware evacuation routes and an integrated plan.
- [ ] Enforce validators and a structural human approval gate before any dissemination.
- [ ] Continuously re-plan when material conditions change while preserving plan versions and audit history.
- [ ] Provide a map-centric command dashboard, agent trace, replay mode, and measurable evaluation evidence.

### Out of Scope

- Real emergency CAD, SMS/IVR, siren, or vehicle telemetry integration - v1 is a local decision-support prototype.
- Real drone control or unverified live vehicle operations - those layers are simulated in the planned scope.
- Fire suppression tactics, wildlife evacuation, and replacement of official decision authority - outside the evacuation coordination goal.

## Context

- The supplied `generatedPlan` folder is the source input for this initialization: PRD, TechSpec, API, Schema, AppFlow, Design, Rules, FolderStructure, EnvSetup, ImplementationPlan, and Tracker.
- Planned stack: Python 3.11+, FastAPI, Pydantic v2, LangGraph, NumPy/Numba, GeoPandas/Shapely/Rasterio, OSMnx/NetworkX, PostgreSQL/PostGIS/pgvector, Redis, React/TypeScript/Vite, MapLibre, Docker Compose, and uv.
- MVP scope is one settlement cluster with FIRMS, Open-Meteo, Fire and Weather agents, a basic route suggestion, deterministic fallback, and complete audit logging. Later phases add shelter/routing depth, review/dissemination/dashboard, then vehicles, drone simulation, calibration, replay, scale, and benchmarks.
- Open decisions remain for the final AOI geometry, MVP settlement cluster, Kannada translation scope, LLM provider/model, calibration data, and literature baselines.

## Constraints

- **Safety**: No dissemination without a persisted approved human review; validators V1-V8 must pass before pending review.
- **Correctness**: LLMs may orchestrate and write grounded rationale, but deterministic code owns fire spread, routing, capacities, and dispatch.
- **Timeline**: Student team target is 12+ weeks with gates at foundations, MVP, Phase 1, and Phase 2.
- **Reproducibility**: Domain computations use an injected real/simulated clock and explicit seeds.
- **Security**: JWT roles, environment-managed secrets, settlement-level data only, append-only audit records.
- **Performance**: Trigger-to-draft target P95 <= 5 minutes and material-change re-plan target <= 2 minutes.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use LangGraph for Coordinator orchestration | Explicit state machine, tool hand-offs, checkpointing, and review interrupts match the workflow | ✓ Good — 8-node Coordinator shipped in Phase 2 |
| Keep numeric decisions deterministic | Safety, reproducibility, validation, and explainability require bounded computation | ✓ Good — LLM receives compact metrics only, writes rationale (Phase 2) |
| Use PostgreSQL/PostGIS plus Redis | Durable spatial audit/state with hot shared state and pub/sub | ✓ Good — loopback-only, required password (Phase 2) |
| Simulate drone and vehicle layers | Enables Phase 2 evaluation without claiming operational integrations | - Pending |
| Treat this as decision support with mandatory human review | Prevents accidental authority or dissemination bypass | - Pending |
| Wind direction is meteorological FROM; fire spreads downwind | Matches Open-Meteo convention (review CR-01) | ✓ Phase 2 |
| Default LLM openai/gpt-oss-20b on Groq, LLM off by default | Earlier Llama models retired; 8k TPM limit needs compact payloads | ✓ Phase 2 |
| Never fabricate weather; no plan without a matching observation | Fabricated "fresh" weather misled reviewers (review HI-03) | ✓ Phase 2 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition**:
1. Move invalidated requirements to Out of Scope with a reason.
2. Move validated requirements to Validated with a phase reference.
3. Add newly emerged requirements to Active.
4. Record important decisions in Key Decisions.
5. Re-check that What This Is and Core Value still describe the product.

**After each milestone**:
1. Review every section and the Core Value.
2. Audit Out of Scope reasons.
3. Update Context with evidence, feedback, and metrics.

---
*Last updated: 2026-10-17 after Phase 2*

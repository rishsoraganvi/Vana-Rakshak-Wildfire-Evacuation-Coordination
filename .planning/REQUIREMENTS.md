# Requirements: Vana-Rakshak

**Defined:** 2026-10-01  
**Core Value:** A human reviewer can quickly understand and safely approve or correct a traceable evacuation plan built from current hazard, route, shelter, and resource data.

## v1 Requirements

### Monitoring and Detection

- [ ] **MON-01**: System polls FIRMS active-fire data for the configured AOI on a configurable interval and de-duplicates observations.
- [ ] **MON-02**: System polls current and forecast weather, detects material wind shifts, and records provider/freshness metadata.
- [ ] **MON-03**: System writes monitoring data to shared versioned state and opens or updates incidents when configured trigger thresholds are crossed.
- [ ] **MON-04**: System surfaces stale or unavailable upstream data and does not silently act below trigger thresholds.
- [ ] **FIRE-01**: Fire Agent clusters candidate hotspots and runs a seeded cellular-automata spread model for 1h, 3h, and 6h horizons.
- [ ] **FIRE-02**: Fire Agent returns current/P50/P90 perimeters, affected area, spread direction/rate, confidence, and settlements at risk with ETA.

### Coordination and Planning

- [x] **PLAN-01**: Coordinator invokes Weather before Fire, then dispatches eligible specialists in parallel through typed tool contracts.
- [x] **PLAN-02**: MVP produces a basic evacuation route suggestion from Coordinator, Fire, Weather, and a pilot road graph.
- [ ] **PLAN-03**: Phase 1 computes routes that account for blocked/unsafe edges, fire forecast penalties, and changing road conditions.
- [ ] **PLAN-04**: Phase 1 matches evacuee groups to shelters without exceeding conservative usable capacity.
- [ ] **PLAN-05**: Phase 2 proposes vehicle assignments without double-booking and marks all simulated entities.
- [ ] **PLAN-06**: Phase 2 provides simulated drone observations when satellite data is stale or verification is requested.
- [ ] **PLAN-07**: Coordinator resolves conflicts with bounded retries and falls back to a deterministic planner when the LLM is unavailable.
- [ ] **PLAN-08**: Integrated plans are immutable, versioned, provenance-linked, freshness-aware, and include grounded rationale and warnings.

### Safety, Review, and Dissemination

- [ ] **SAFE-01**: Validators V1-V8 block invalid routes, unsafe perimeter crossings, capacity violations, incomplete assignments, duplicate vehicles, unknown entities, and ungrounded rationale.
- [ ] **SAFE-02**: No plan can be disseminated without a persisted explicit human approval from a reviewer/admin role.
- [ ] **SAFE-03**: Reviewer can inspect, edit, approve, reject with a reason, or request re-plan; edits trigger validation and remain auditable.
- [ ] **SAFE-04**: Approved plans generate simulated community alerts, field instructions, and map exports with plan version, approval timestamp, and decision-support disclaimer.
- [ ] **SAFE-05**: Material changes create a new plan version requiring review again; incidents close only after a human resolution action.

### Platform and Experience

- [ ] **PLAT-01**: API exposes authenticated role-based monitoring, incident, plan, review, resource, audit, health, and replay operations under `/api/v1`.
- [x] **PLAT-02**: Agent runs, tool calls, inputs, outputs, latency, model metadata, and user actions are stored in append-only audit records.
- [ ] **PLAT-03**: Dashboard provides a map-first overview, incident detail, plan review, validator strip, agent activity, freshness warnings, and simulation badges.
- [ ] **PLAT-04**: System operates in degraded mode with cached data and deterministic planning when external providers or the LLM fail.
- [ ] **PLAT-05**: Replay mode runs historical/scenario inputs through the same pipeline with a simulated clock.
- [x] **PLAT-06**: Fire, routing, matching, validators, contracts, review flow, and replay behavior have unit, property, integration, and end-to-end coverage appropriate to each phase.
- [ ] **PLAT-07**: System meets initial targets: plan P95 <= 5 minutes, re-plan <= 2 minutes, valid routes and capacities, zero approved capacity violations, and 100% approval records for dissemination.

## v2 Requirements

- **EVAL-01**: Benchmark plan quality against MARL/GreyGNN-MARL literature baselines where reproducible.
- **EVAL-02**: Full multi-incident merging and optimization across all three reserves beyond the Phase 2 scale-up target.
- **OPS-01**: Production integrations with emergency CAD, SMS/IVR, sirens, real vehicle telemetry, or live drone control.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Automatic dissemination or auto-approval | Human authority is a structural safety requirement |
| LLM-generated fire geometry, routes, capacities, dispatches, or invented entities | Numeric and safety-critical outputs must be deterministic and validated |
| Wildlife evacuation and firefighting optimization | Not part of the evacuation coordination prototype |
| Individual-level personal data | Settlement-level data is sufficient and reduces privacy risk |

## User Stories

- As an incident commander, I can review a current plan, its uncertainty, freshness, rationale, and validator results before approving it.
- As a dispatcher or traffic controller, I can see assignments and route hazards derived from a shared incident plan.
- As an administrator, I can replay a scenario, inspect agent traces, tune thresholds, and compare metrics without live operational dependencies.

## Acceptance Criteria

- A replayed hotspot can produce a traceable draft plan with forecast perimeters, a route, warnings, and audit entries.
- A plan with a capacity, route, entity, vehicle, or rationale-grounding violation cannot enter `pending_review`.
- Dissemination requests fail unless an approving review is present for that exact plan version.
- A material change produces a new plan version and never silently replaces the current approved plan.
- Simulated data, stale inputs, and decision-support status are visible in API and dashboard outputs.

## Definition of Done

- Requirements are covered by executable tests or a recorded replay scenario.
- Safety rules S1-S9 remain enforced and documented.
- `docker compose up` and the documented local setup work for the implemented phase.
- Lint, type checks, relevant tests, and integration checks pass; docs and Tracker are updated with the change.

## Traceability

| Requirement group | Phase | Status |
|---|---:|---|
| MON-01..04, FIRE-01..02 | 1 | Pending |
| PLAN-02, PLAT-02 (Phase 2 slice) | 2 | Complete (human UAT pending) |
| PLAN-01 (parallel dispatch) | 3 | Pending |
| PLAT-06 (Phase 2 slice) | 2 | Covered; requirement spans phases, closes in 5 |
| PLAN-03..04, PLAN-07..08 | 3 | Pending |
| SAFE-01..05, PLAT-01, PLAT-04 | 4 | Pending |
| PLAT-03, PLAT-05, PLAT-06 | 5 | Pending |
| PLAN-05..06, PLAT-07, EVAL-01..02 | 6 | Pending |

**Coverage:** v1 requirements: 29; mapped to phases: 29; unmapped: 0.

---
*Requirements defined: 2026-10-01*  
*Last updated: 2026-10-01 after initialization from generatedPlan*

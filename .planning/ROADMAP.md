# Roadmap: Vana-Rakshak

## Overview

Six phases turn the supplied 12+ week implementation plan into vertical, verifiable slices. The first phase establishes a runnable foundation; the second proves the MVP trigger-to-route loop; the third adds coordinated planning; the fourth enforces review and dissemination; the fifth makes the command workflow usable; and the sixth completes simulation, calibration, scale, and evaluation.

## Phase 1: Foundations and Data Contracts

**Goal:** A reproducible monorepo foundation can start infrastructure, migrate the core schema, load configuration, and represent shared state, clocks, geometry, and typed agent contracts.

**Requirements:** MON-01, MON-02, MON-03, MON-04, FIRE-01, FIRE-02

**Deliverables:** uv workspace scaffold, Compose PostGIS/pgvector/Redis, Alembic baseline, CI, config/secrets conventions, AOI decision record, shared Pydantic models, Clock abstraction, initial FIRMS/weather clients and fixtures.

**Exit criteria:** migrations run; services have health probes; mocked ingest persists deduplicated observations; schema and contracts are tested; a seeded simulated clock produces repeatable inputs.

**Plans:** 3/3 plans complete

Plans:

- [x] 01-01-PLAN.md — Compose, migrations, shared config, and FastAPI health tracer
- [x] 01-02-PLAN.md — Typed monitoring/fire contracts, clocks, parsers, and fixtures
- [x] 01-03-PLAN.md — Durable offline ingest, freshness, dedupe, and trigger state

## Phase 2: MVP Detection to Route

**Goal:** A hotspot or replay event produces a basic, auditable evacuation route suggestion for one pilot settlement cluster.

**Requirements:** PLAN-01, PLAN-02, PLAT-02, PLAT-06

**Deliverables:** hotspot clustering, weather agent, fire CA ensemble and risk assessment, pilot OSM graph, route utility, Coordinator v0, audit rows, deterministic fallback, trigger lifecycle, read-only API, replay/demo script, initial fire baseline.

**Exit criteria:** end-to-end replay passes with mocked LLM; output contains P50/P90 forecast data and route; audit entries cover every node/tool call; fallback works with LLM disabled; core tests pass.

**Plans:** 9/9 plans complete

Plans:

- [x] 02-01-PLAN.md — Contracts, Fire CA Model, Weather Agent, Hotspot Clustering
- [x] 02-02-PLAN.md — OSM Graph, Route Utility, Coordinator v0 (LangGraph + Groq)
- [x] 02-03-PLAN.md — Read-Only API, Audit Persistence, Replay Script, Full Test Suite
- [x] 02-04-PLAN.md — (gap) Fire CA downwind convention and real spread metrics (CR-01, HI-02)
- [x] 02-05-PLAN.md — (gap) Full-edge fire exposure and rankable blocked routes (CR-02, HI-01)
- [x] 02-06-PLAN.md — (gap) Audit model_metadata, LLM gating, configurable model (PLAT-02, HI-05, MD-11)
- [x] 02-07-PLAN.md — (gap) Every cluster simulated, routes start outside fire (CR-03, HI-01)
- [x] 02-08-PLAN.md — (gap) Loopback-only Postgres/Redis, required password (HI-06)
- [x] 02-09-PLAN.md — (gap) Scoped weather lookup, no fabricated weather (HI-03, HI-04)

## Phase 3: Capacity-Aware Coordinated Planning

**Goal:** A Coordinator assembles a validated, versioned integrated plan using dynamic routing and shelter capacity constraints.

**Requirements:** PLAN-03, PLAN-04, PLAN-07, PLAN-08

**Deliverables:** shelter registry and matching, routing agent with dynamic costs/k-paths/congestion pass, shared-state versioning, parallel specialist dispatch, bounded conflict resolution, plan assembly/version diffs, validators V1-V8, re-plan trigger/debounce logic, fallback behavior.

**Exit criteria:** property tests prove capacity and double-booking invariants; invalid plans are blocked; a material route/shelter change creates a new version; provenance and freshness are present on every plan.

**Plans:** 12 plans

Plans:

- [ ] 03-01-PLAN.md — Workspace, synthetic graph fixture, CI target, capacity-safe min-cost-flow matching with properties
- [ ] 03-02-PLAN.md — Phase 3 contracts (IntegratedPlan, ValidationResult, ToolResult), shared horizon/footprint helpers, config block
- [ ] 03-03-PLAN.md — WR-03: live weather observations match the scoped query; incidents carry real origin
- [ ] 03-04-PLAN.md — Migration 0006, labelled synthetic seed + loaders, shelter registry and atomic occupancy
- [ ] 03-05-PLAN.md — Routing: ETA-aware horizon costs, edge status, cost matrix, k=3 paths, BPR congestion, load-only graph + build script
- [ ] 03-06-PLAN.md — Risk assessment (groups, rescue alerts, P90 warnings) and validators V1-V7 with properties
- [ ] 03-07-PLAN.md — Finalize (S5 gate), strict V8 grounding + template, enum-only LLM fix menu, plan rationale
- [ ] 03-08-PLAN.md — Versioned persistence: repository, advisory-locked versions, diff, state_version, ADR-002
- [ ] 03-09-PLAN.md — Planning core: capacity-aware assignment with BPR passes, bounded resolver, fallback planner, invariants
- [ ] 03-10-PLAN.md — Coordinator rewiring: parallel dispatch, per-cluster weather (WR-01), persistence, audit on failure
- [ ] 03-11-PLAN.md — Re-plan triggers, debounce, on-demand entry, API failed-plan visibility, demo/live test updates
- [ ] 03-12-PLAN.md — Real-data handoff: readiness probe, OSM build and curated seed checkpoints

## Phase 4: Human Review and Dissemination Safety

**Goal:** Only an authenticated human reviewer can approve a validated plan, and dissemination is structurally impossible without that approval.

**Requirements:** SAFE-01..05, PLAT-01, PLAT-04

**Deliverables:** JWT roles, review/checkpoint interrupt and resume, review/edit/reject/re-plan APIs, append-only user audit log, dissemination generators, approval guard, freshness/degraded-mode endpoints, WebSocket event contract.

**Exit criteria:** reviewer integration test covers edit, validate, approve, reject, and re-plan; dissemination without an exact approval returns an error; all artifacts include disclaimer, version, timestamp, and simulation labels.

## Phase 5: Command Dashboard and Replay Workflow

**Goal:** Reviewers can operate the system through a map-first dashboard and administrators can inspect traces and replay scenarios.

**Requirements:** PLAT-03, PLAT-05, PLAT-06

**Deliverables:** React/Vite shell, MapLibre layers, overview and incident detail, plan review with validator strip/diff/Why drawer/two-step approval, agent ticker and trace, resources views, replay UI, i18n/accessibility checks, Playwright approval flow.

**Exit criteria:** dashboard shows hazards, forecast uncertainty, freshness, routes, shelters, and simulated badges; keyboard-accessible approval flow passes; full trigger-to-dissemination replay is demonstrable.

## Phase 6: Simulation, Calibration, Scale, and Evaluation

**Goal:** The prototype produces evidence about model behavior and remains useful under simulated data gaps, larger geography, and long-running scenarios.

**Requirements:** PLAN-05, PLAN-06, PLAT-07, plus v2 EVAL-01..02 where feasible.

**Deliverables:** simulated vehicle and drone agents, stale-data observation fallback, historical FIRMS/weather calibration pipeline, three-reserve data preparation, multi-incident handling, benchmark/stress/LLM evaluation harness, security pass, final demo/report.

**Exit criteria:** all simulated entities are labeled; replay and stress reports record latency, validity, uncertainty, and failure behavior; calibration results include IoU/F1 baselines; final scope cuts are documented.

## Dependencies and Ordering

1. Phase 1 enables all later implementation through contracts, schema, and local infrastructure.
2. Phase 2 must establish the deterministic fire, weather, trigger, route, and audit loop before Phase 3 adds more agents.
3. Phase 3 must produce validators and immutable plan versions before Phase 4 exposes approval or dissemination.
4. Phase 5 consumes Phase 4 APIs/events; Phase 6 can proceed in parallel on isolated simulation/evaluation work after Phase 2 fixtures exist.

## Risk Strategy

- If FIRMS access is delayed, use archived fixtures and replay while keeping the live client thin.
- If CA calibration lags, ship wide confidence bands and label the model as uncalibrated.
- If LLM calls fail or exceed budget, use the deterministic fallback and template rationale.
- If dashboard work slips, prioritize Plan Review, validator visibility, and agent ticker over replay polish.
- If the timeline compresses, defer literature baselines, multi-incident merge, and full scale-up before cutting calibration, human review, or safety validation.

---
*Roadmap created: 2026-10-01 from generatedPlan*

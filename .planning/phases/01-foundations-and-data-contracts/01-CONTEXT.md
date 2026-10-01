# Phase 1: Foundations and Data Contracts - Context

**Gathered:** 2026-10-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Establish a reproducible monorepo foundation that starts local infrastructure, migrates the Phase 1 schema, loads typed configuration, and represents shared state, clocks, geometry, and agent contracts. This phase prepares monitoring and fire-model inputs/outputs; it does not implement the full MVP coordinator, routing workflow, shelter matching, human review, or dashboard.

</domain>

<decisions>
## Implementation Decisions

### Local stack baseline
- **D-01:** `docker compose up` must start healthy PostGIS/pgvector and Redis plus a minimal FastAPI API skeleton.
- **D-02:** The API skeleton should expose health/readiness and safe non-secret configuration/AOI introspection; full monitoring endpoints belong to later phases.
- **D-03:** Use hybrid testing: pure unit tests for domain/config/schema logic and a small Compose-backed smoke suite for service connectivity and migrations.
- **D-04:** Configuration uses YAML defaults with environment-variable overrides, matching the supplied EnvSetup and Rules documents.

### AOI and fixtures
- **D-05:** Use the supplied bbox as the default AOI input: west 76.0, south 11.5, east 77.3, north 12.4.
- **D-06:** Represent the AOI as configurable geometry with a replaceable placeholder polygon; authoritative park polygons remain a pending decision.
- **D-07:** Seed Bandipur as the provisional pilot settlement cluster, with a configurable cluster identifier so the Phase 2 pilot decision can replace it without a contract rewrite.
- **D-08:** Include both small deterministic domain fixtures and provider-shaped FIRMS/Open-Meteo samples with raw payloads for parser and contract tests.
- **D-09:** No live external API calls are required for Phase 1 or CI. Live FIRMS/weather verification may be added later as an explicit opt-in command.

### Claude's Discretion
- Exact package/module boundaries within the supplied FolderStructure.
- Exact migration split within the Phase 1 monitoring/shared-state tables, provided later schema compatibility is preserved.
- Exact health endpoint response field names, provided secrets are excluded and dependency status is observable.

</decisions>

<specifics>
## Specific Ideas

- The foundation should be runnable on a fresh machine through Docker Compose and remain useful offline.
- The Bandipur seed is explicitly provisional, not a final operational AOI or settlement decision.
- Fixtures should preserve realistic provider field shapes while keeping domain tests deterministic and network-free.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Product and phase scope
- `.planning/ROADMAP.md` — Phase 1 goal, requirements, deliverables, and exit criteria.
- `.planning/REQUIREMENTS.md` — MON-01..04 and FIRE-01..02 requirements plus acceptance criteria.
- `.planning/PROJECT.md` — safety, reproducibility, security, and performance constraints.

### Source product specifications
- `generatedPlan/TechSpec.md` — architecture, shared state, service boundaries, data freshness, and deterministic-versus-LLM rules.
- `generatedPlan/Schema.md` — PostgreSQL/PostGIS/pgvector entities, enums, geometry, and timestamp conventions.
- `generatedPlan/FolderStructure.md` — monorepo/package layout and naming conventions.
- `generatedPlan/EnvSetup.md` — local prerequisites, environment variables, Compose expectations, and offline fallback guidance.
- `generatedPlan/Rules.md` — safety, typing, configuration, testing, data, secrets, and assistant rules.
- `generatedPlan/API.md` — health, freshness, monitoring response conventions, roles, and simulated-data fields.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- No application source exists yet. The `generatedPlan` documents are the only reusable project assets.

### Established Patterns
- No code patterns exist yet. The supplied FolderStructure and Rules documents establish the intended package, config, testing, and migration conventions.

### Integration Points
- Phase 1 creates the foundation consumed by the ingest worker, API gateway, coordinator, agent packages, and dashboard in later phases.

</code_context>

<deferred>
## Deferred Ideas

- Final park-boundary AOI and final pilot settlement selection — resolve during Phase 2/G0 decision work.
- Live FIRMS/Open-Meteo validation in CI — keep opt-in and outside the offline foundation gate.
- Full monitoring endpoints, coordinator behavior, route planning, shelter matching, review/dissemination, and dashboard — covered by later roadmap phases.

</deferred>

---

*Phase: 01-foundations-and-data-contracts*
*Context gathered: 2026-10-01*

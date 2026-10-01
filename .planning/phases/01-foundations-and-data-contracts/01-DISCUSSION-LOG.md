# Phase 1: Foundations and Data Contracts - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-01
**Phase:** 1-Foundations and Data Contracts
**Areas discussed:** Local stack baseline, AOI and fixtures

---

## Local stack baseline

| Option | Description | Selected |
|--------|-------------|----------|
| Infrastructure only | PostGIS/pgvector and Redis are healthy; application services remain for later phases | |
| Infrastructure plus API skeleton | Also start a minimal FastAPI health service using the shared package | ✓ |
| Full foundation services | Start ingest/coordinator shells too, even before their MVP behavior | |

**User's choice:** Infrastructure plus API skeleton
**Notes:** The API skeleton includes health/readiness and safe config/AOI introspection. Testing uses a hybrid of pure unit tests and a small Compose-backed smoke suite.

### Additional decisions

| Question | Selected option |
|----------|-----------------|
| How should tests handle PostGIS/Redis? | Hybrid fixtures |
| Configuration contract | YAML defaults plus env overrides |
| API skeleton scope | Health plus config introspection |

---

## AOI and fixtures

| Option | Description | Selected |
|--------|-------------|----------|
| Initial bounding box | Use the supplied bbox; refine polygons later | |
| Park polygons now | Require authoritative reserve boundaries immediately | |
| Configurable bbox with placeholder polygon | Keep the supplied bbox as default and make AOI geometry replaceable | ✓ |

**User's choice:** Configurable bbox with placeholder polygon
**Notes:** Bandipur is the provisional pilot cluster. Fixtures include both deterministic domain records and provider-shaped raw samples. Phase 1 and CI require no live API calls.

### Additional decisions

| Question | Selected option |
|----------|-----------------|
| Pilot settlement representation | Use Bandipur placeholder with configurable cluster ID |
| Fixture shape | Both deterministic domain fixtures and provider-shaped samples |
| External API requirement | No live calls required |

---

## Claude's Discretion

- Exact package/module boundaries within the supplied FolderStructure.
- Exact migration split within the Phase 1 monitoring/shared-state tables.
- Exact non-secret health/config response fields.

## Deferred Ideas

- Final park-boundary AOI and final pilot settlement selection.
- Live external API validation in CI.
- Full monitoring, coordination, routing, review/dissemination, and dashboard behavior.

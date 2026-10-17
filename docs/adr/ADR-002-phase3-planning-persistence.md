# ADR-002: Phase 3 Planning Persistence and Shared State

- **Status:** Accepted for Phase 3
- **Date:** 2026-10-17
- **Scope:** How coordinated plans are versioned, stored, locked and shared. Covers the repository, migration 0006 and the coordinator graph; does not cover review or approval APIs (Phase 4).

## Decision

1. **Postgres-only shared state, advisory locks instead of Redis.** Shared state is `incidents.state_version` plus append-only `shared_state_snapshots` rows (TechSpec section 5 sections, by reference). Concurrent planners for one incident are serialised with `pg_advisory_xact_lock(hashtext(incident_id))` inside the persist transaction, and an optimistic `state_version` check under `SELECT ... FOR UPDATE` aborts a plan built on stale state with `StateVersionConflict`. This deviates from TechSpec section 5 (hot state in Redis) and section 9 (Redis lock). Redis is still deployed for later use, but Phase 3 has one writer path and one source of truth, so there is no cache invalidation or lock-expiry failure mode. Redis pub/sub for live fan-out is deferred to Phase 5.
2. **In-process parallel dispatch.** Specialist work (fire, weather, routing, shelter) is dispatched with `asyncio.gather` inside a single LangGraph node, not by graph-level fan-out. Every specialist returns a typed `ToolResult`; a failure degrades to an alert instead of losing the run. Graph-level fan-out adds checkpointing and reducer complexity with no benefit while all specialists are in-process and deterministic.
3. **Plan immutability by database trigger.** `trg_plan_versions_immutable` (migration 0006) rejects any update that changes a column other than `status`. The application only ever issues status updates (supersede, later approve or reject). The trigger is proven against a live database in `tests/integration/test_plan_versions_db.py`.
4. **Forward-only `failed` plan status.** `failed` is added to the `plan_status` enum (D-11). PostgreSQL cannot drop an enum value, so a downgrade of 0006 leaves it in place. A failed plan carries no routes or assignments and needs at least one named reason. The incident returns to `planning`, never to `awaiting_review`.
5. **`plan_schema_version` "3.0" in `plan_data`.** Phase 3 plans are `IntegratedPlan` documents tagged `"3.0"`; Phase 2 `CoordinatorPlan` rows default to `"2.0"`. Readers branch on the tag, and a Phase 2 predecessor always counts as a material change (D-16).
6. **Validated plans are stored as `pending_review`.** A plan reaches `pending_review` only when validators V1 to V8 ran in order and none failed (S5, enforced by the schema and the finalize gate). Approval is a human action in Phase 4 (D-21); Phase 3 never sets `approved` and never changes shelter occupancy.
7. **Labelled synthetic seed.** Shelters and settlements are seeded from `config/seed/*.csv` with `capacity_source` / `pop_source` = `synthetic` and `is_simulated = true` (D-18), and plans built on them are marked simulated and carry a warning. Replacing the seed with curated data is a human step.
8. **Re-plan versions only on material change.** A new version is written only when the material signature differs: sorted assignments, per-group route node paths and validator statuses. ETA noise, rationale text, warnings, ids and timestamps are ignored (D-16). Each new version stores `parent_plan_id` and a `diff`, and earlier non-terminal versions become `superseded`.

## Persist protocol

`PlanningRepository.persist_plan` runs in one transaction:

1. `pg_advisory_xact_lock(hashtext(incident_id))`
2. `SELECT state_version ... FOR UPDATE`; mismatch raises `StateVersionConflict` before any write
3. `SELECT ... FROM shelters ... FOR SHARE` and re-check that assignments still fit usable capacity minus occupancy; failure raises `CapacityRecheckFailed` (Rules 6)
4. `MAX(version) + 1`, safe under the lock; `UNIQUE (incident_id, version)` is the backstop
5. insert the immutable row with parent, trigger, state version, validation, freshness, provenance, diff and `valid_until`
6. status-only update of earlier `draft`, `pending_review` and `failed` versions to `superseded`
7. bump `incidents.state_version` and incident status
8. write the `shared_state_snapshots` row for the new version

All coordinator SQL lives in `SqlPlanningRepository`. `InMemoryPlanningRepository` implements identical semantics so offline tests and replays fake functions, not SQL strings.

## Consequences

- Version numbers cannot collide and stale or overbooked plans never persist; the caller persists a `failed` plan instead (plan 03-10).
- Occupancy is not changed at plan time. Between planning and approval, capacity can still change; the persist-time re-check narrows that window and approval must repeat it atomically in Phase 4.
- Postgres carries the lock and state load. This is acceptable for one pilot AOI; revisit together with Redis pub/sub in Phase 5 if multiple incidents plan concurrently at scale.
- The `failed` enum value and the `plan_data` tag are permanent schema facts; later phases must read them rather than assume Phase 2 shapes.

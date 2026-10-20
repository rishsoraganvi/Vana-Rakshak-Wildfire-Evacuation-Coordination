---
phase: 03
slug: capacity-aware-coordinated-planning
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-10-20
---

# Phase 03 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Register source: `<threat_model>` blocks of plans 03-01..03-12 (64 threats, authored at plan time) plus the SUMMARY threat flags (none unregistered).
> Verified by gsd-security-auditor at ASVS L1 (high-severity items traced to the enforcing boundary), block_on: high, after the code-review fixes in 03-REVIEW-FIX.md.
> Per-threat file:line evidence is in the audit transcript summarised below; each mitigation names its control.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Open-Meteo payload → weather_observations | External provider data is parsed and persisted | Weather observations/forecasts |
| Overpass/OSM → data/osm | External map data enters only through the human-run build script | Road graph (ODbL) |
| GraphML file → loader | Local operator-controlled file is parsed; runtime never downloads | Road graph |
| seed CSV (operator/user supplied) → DB | File contents become shelters and settlements | Locations, capacities, populations |
| config/env → Settings | Operator coefficients drive routing and capacity decisions | Safety-relevant parameters |
| repository (DB) → coordinator nodes | Persisted hotspots, weather, settlements, shelters, edge statuses drive the plan | Incident inputs |
| worker threads → coordinator | Specialist results return from concurrent threads | ToolResult envelopes |
| fire forecast → edge costs | Forecast geometry decides blocked/penalised roads | Perimeters |
| algorithm output → validators → reviewer | V1-V8 independently check routing/matching before pending_review | Draft plans |
| coordinator → Groq API / LLM output → control flow | Compact summaries leave the process; model text and enum choices re-enter | Counts, rationale text, fix strategy |
| concurrent coordinator runs / writers → plan_versions, shelters.occupancy | Re-plans, replays and operators may race | Plan versions, occupancy |
| app role → plan_versions | Code could try to rewrite a stored plan (DB trigger blocks it) | Stored plans |
| observation callers → replan entry / ingest → incidents | External evidence decides re-planning and data origin labelling | Triggers |
| API client → /api/v1 plan endpoint | Read-only, loopback-bound, unauthenticated until Phase 4 (AR-06) | Settlement-level plan data |
| repository → CI runner | Workflow file and lockfile decide what CI installs and tests | Dependencies |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-03-01-01 | Tampering | `match_groups_to_shelters` (capacity overbooking from a flow bug) | high | mitigate | Integer weights, a diagnostic sink, and Hypothesis capacity and conservation properties (Task 2) that CI enforces (Task 3) | closed |
| T-03-01-02 | Tampering | `uv.lock` / workspace wiring (supply chain) | medium | mitigate | No registry packages added. `uv lock --check` and an unchanged lock header are acceptance criteria. Only a local workspace member is introduced. | closed |
| T-03-01-03 | Information disclosure | Cached OSM graph or caches committed to git | low | mitigate | `data/` and `cache/` git-ignored, checked with `git check-ignore` | closed |
| T-03-01-04 | Repudiation | Non-deterministic matching results | low | mitigate | Sorted edge insertion and a determinism property test | closed |
| T-03-01-SC | Tampering | npm/pip/cargo installs | low | accept | No external package installs in this plan (RESEARCH Package Legitimacy Audit: none new) | closed |
| T-03-02-01 | Tampering | IntegratedPlan (a failing plan reaching pending_review) | high | mitigate | Model validator requires V1-V8 present with no "fail" for pending_review. failed carries no routes or assignments (Task 2 tests). | closed |
| T-03-02-02 | Tampering | Settings (an unsafe coefficient such as P90 above P50, a usable factor above 1, an extra fix strategy) | medium | mitigate | Settings model_validator bounds and the exact three-strategy check (Task 3 tests) | closed |
| T-03-02-03 | Repudiation | Plans lacking provenance or freshness | medium | mitigate | `freshness` and `provenance` are required fields with no defaults | closed |
| T-03-02-04 | Tampering | Untyped data crossing boundaries | low | mitigate | `extra="forbid"` on every model, tuples for collections, frozen plan models | closed |
| T-03-02-05 | Information disclosure | Personal data in plan contracts | low | accept | Settlement-level data only. No individual fields exist in any model (Rules 6). | closed |
| T-03-03-01 | Tampering | Forecast rows used as current observations (fabricated "current" weather) | high | mitigate | `is_forecast = valid_time > issued_at`. The scoped query keeps `is_forecast IS false` and `valid_time <= now`, and the unit tests assert both. | closed |
| T-03-03-02 | Spoofing | Incident labelled replay while built from live data, or the reverse (S3) | medium | mitigate | Origin is required and validated against the enum, and bound via a CAST parameter | closed |
| T-03-03-03 | Tampering | SQL injection through origin | low | mitigate | Parameterised `text()` bind with an enum cast. Allow-list validation before SQL runs. | closed |
| T-03-03-04 | Denial of service | Live test leaves rows that skew other runs | low | mitigate | Cleanup in `finally`, scoped by exact keys | closed |
| T-03-04-01 | Tampering | `update_occupancy` (double-booking race) | high | mitigate | Single-statement CAS with the capacity bound in the WHERE clause, a DB CHECK that occupancy ≤ capacity, and a history row only on success (Task 3 unit and live tests) | closed |
| T-03-04-02 | Tampering | plan_versions (silent mutation of a stored plan) | high | mitigate | `trg_plan_versions_immutable` raises on any non-status column change (Task 2, live-verified in plan 03-08) | closed |
| T-03-04-03 | Tampering | Seed CSV injection (control chars, script text, out-of-area coordinates) | medium | mitigate | Pydantic row validation: regex refs, no control characters, bounded numbers, pilot-area distance test. Text is treated as data only. | closed |
| T-03-04-04 | Repudiation | Synthetic capacities presented as real (S9) | medium | mitigate | `capacity_source`/`pop_source` NOT NULL, `is_simulated` required for synthetic rows, a script warning, docs/datasets.md | closed |
| T-03-04-05 | Tampering | SQL injection through seed values or ids | low | mitigate | Parameterised `text()` binds only; no string-built SQL | closed |
| T-03-04-06 | Denial of service | Enum value cannot be rolled back | low | accept | Documented forward-only downgrade. The decision is human-locked (D-11). | closed |
| T-03-05-01 | Denial of service / Tampering | Implicit OSM download at plan time (SSRF, supply chain, minutes-long stalls) | high | mitigate | Load-only `load_graph` raises GraphNotBuiltError. Tests monkeypatch every download function to fail. The build is an explicit script. | closed |
| T-03-05-02 | Tampering | Route through an active fire or a blocked road | high | mitigate | Blocked edges are infinite and hidden from Dijkstra and k-paths. Edge status blocked/unsafe blocks. Exposure is evaluated per edge with the shared horizon rule (Task 1 tests). | closed |
| T-03-05-03 | Elevation of privilege | `eval` on GraphML tag strings | medium | mitigate | `ast.literal_eval` only, guarded with try/except, checked by grep acceptance | closed |
| T-03-05-04 | Denial of service | Yen over large graphs | medium | mitigate | k-paths only on demand, a collapsed DiGraph, and a `k_paths_max_leg_s` budget with a truncated flag | closed |
| T-03-05-05 | Repudiation | Missing OSM attribution | low | mitigate | The build script prints ODbL attribution, and docs/datasets.md (plan 03-04) records it | closed |
| T-03-06-01 | Tampering | A route through the fire passes validation | high | mitigate | V2 uses the edge geometry directly (independent of routing zone attributes) plus edge status. V3 checks P50 per edge with the shared horizon rule. Unit tests cover fail cases. | closed |
| T-03-06-02 | Tampering | Capacity violation or double-booking passes | high | mitigate | V4/V5/V6 are pure checks with Hypothesis iff-properties (Task 3) | closed |
| T-03-06-03 | Spoofing | Hallucinated or unknown ids in a plan | medium | mitigate | V7 checks every id against registry, settlement, graph and cluster sets | closed |
| T-03-06-04 | Tampering | Under-evacuation through a missing population | medium | mitigate | Unknown population is reported and the plan fails closed (plan 03-09 preflight). Nothing is guessed. | closed |
| T-03-06-05 | Information disclosure | Ids leaking into LLM payloads | low | mitigate | `violation_summary` emits code counts only (unit test asserts no uuid or name) | closed |
| T-03-07-01 | Tampering | LLM invents a shelter, number or id in a rationale (S4) | high | mitigate | Strict V8 grounding of numbers, uuids and registry names, with template replacement and the reason recorded (D-13). Property: template always grounded. | closed |
| T-03-07-02 | Tampering | LLM steers control flow outside the menu or names targets | high | mitigate | Strict json_schema enum, Pydantic validation, membership check, one repair retry then deterministic fallback. Targets are chosen deterministically. | closed |
| T-03-07-03 | Elevation of privilege | An invalid plan reaches pending_review | high | mitigate | finalize forces failed on any fail status. The IntegratedPlan validator rejects pending_review with failures (plan 03-02). | closed |
| T-03-07-04 | Information disclosure | Data egress to Groq | medium | mitigate | Settlement-level data only. Compact summary with no coordinates or paths. The fix-menu payload is code counts only, with id/name keys rejected. Gated by llm_enabled and key. | closed |
| T-03-07-05 | Tampering | Prompt injection through shelter or settlement names in data | medium | mitigate | Names are only data inside JSON. The model's output is constrained to an enum for control flow, and free text is V8-checked. Rules 12.10. | closed |
| T-03-07-06 | Denial of service | LLM latency or quota | low | mitigate | Gate before any client, request timeout, token caps, and deterministic fallback on any error | closed |
| T-03-08-01 | Tampering | Concurrent persists racing on the version number | high | mitigate | `pg_advisory_xact_lock(hashtext(incident))` plus the unique (incident_id, version) constraint, in one transaction | closed |
| T-03-08-02 | Tampering | Plan built on stale shared state overwriting newer state | medium | mitigate | `state_version` FOR UPDATE check raises StateVersionConflict before writes | closed |
| T-03-08-03 | Tampering | Capacity changed between planning and persist (overbooking) | high | mitigate | FOR SHARE re-check of occupancy and usable capacity in the persist transaction raises CapacityRecheckFailed. The caller persists a failed plan (plan 03-10). | closed |
| T-03-08-04 | Tampering | Silent mutation of a stored plan | high | mitigate | DB trigger (plan 03-04) proven live here. Frozen app models. Only status updates are issued. | closed |
| T-03-08-05 | Repudiation | A re-plan silently replacing the current plan | medium | mitigate | parent_plan_id, diff jsonb and superseded status keep the full chain (D-16) | closed |
| T-03-08-06 | Tampering | SQL injection through ids | low | mitigate | Parameterised binds, uuid typing, and expanding bindparam for IN lists | closed |
| T-03-09-01 | Tampering | Overbooked shelter or partially assigned group reaching a valid draft | high | mitigate | Every producer is gated by V1-V7, with Hypothesis properties over the whole core and the spy invariant (Task 3) | closed |
| T-03-09-02 | Tampering | Unsafe route selected while a safe alternative exists | high | mitigate | Safe-first k-path selection with per-edge evaluation, then V2/V3 and the next_path/rematch strategies | closed |
| T-03-09-03 | Elevation of privilege | LLM-chosen strategy names its own targets or bypasses validators | high | mitigate | The LLM returns an enum only. Targets come from sorted violations, and every loop re-validates identically (D-10). | closed |
| T-03-09-04 | Denial of service | Unbounded conflict loops or congestion passes | medium | mitigate | `range(conflict_max_loops)` and `range(congestion_passes)` with config caps of 3 (validated in plan 03-02), plus the k-path time budget | closed |
| T-03-09-05 | Repudiation | Silent fallback | low | mitigate | `used_fallback` and resolver_steps (chosen_by) are recorded in the plan | closed |
| T-03-10-01 | Tampering | Fabricated or wrong-location weather driving fire forecasts | high | mitigate | Per-cluster scoped lookup. A missing reading fails the plan closed and names the cluster. No substitute snapshot (Task 3 tests). | closed |
| T-03-10-02 | Tampering | A partial or invalid plan reaching pending_review after a specialist failure | high | mitigate | Specialist failure becomes a preflight failure, then a failed plan (TechSpec 12). finalize and the schema enforce S5. | closed |
| T-03-10-03 | Repudiation | Lost audit rows when a run crashes | medium | mitigate | Stream-based last-state tracking, a run_failed entry and an idempotent flush in finally (Task 2) | closed |
| T-03-10-04 | Tampering | Shared mutable lists across threads | medium | mitigate | Specialists return values only. Audit and warnings are appended on the coordinator thread after gather (RESEARCH anti-pattern). | closed |
| T-03-10-05 | Denial of service | A hung specialist | medium | mitigate | `asyncio.wait_for` timeout from config, error envelope, critical failure becomes failed plan | closed |
| T-03-10-06 | Tampering | Version churn from repeated identical runs | low | mitigate | Material-change gate (D-16) records replan_no_change | closed |
| T-03-11-01 | Denial of service | Trigger storm causing plan churn | medium | mitigate | 300 s coalescing per (incident, type) under an advisory lock, plus the material-change gate (D-16) | closed |
| T-03-11-02 | Tampering | A re-plan silently replacing the current plan | medium | mitigate | A new immutable version with parent_plan_id and diff. The prior version is only status-superseded. | closed |
| T-03-11-03 | Repudiation | Re-plans without an audit trail | medium | mitigate | Trigger rows with handled_run_id linked to the audit entry, plus a replan_no_change audit node | closed |
| T-03-11-04 | Information disclosure | Failed plan details exposed by an unauthenticated API | low | accept | API is read-only and bound to 127.0.0.1 (AR-06, Phase 2 SECURITY). Settlement-level data only. Auth arrives in Phase 4. | closed |
| T-03-11-05 | Tampering | Out-of-scope trigger types (wind_shift, manual) used to force re-plans | low | mitigate | Allow-list validation in record_trigger and replan_incident raises ValueError | closed |
| T-03-11-06 | Tampering | SQL injection through details, type or ids | low | mitigate | Parameterised binds, an enum CAST and a jsonb CAST | closed |
| T-03-12-01 | Tampering | Malformed or malicious curated CSV (control chars, out-of-area points, absurd capacities) | medium | mitigate | `ShelterSeedRow` and `SettlementSeedRow` validation, `--dry-run` before load, the pilot-area distance test in test_seed_rows.py | closed |
| T-03-12-02 | Repudiation | Unverified capacities presented as fact (S9) | medium | mitigate | capacity_source and pop_source required and shown on plans. docs/datasets.md records the sources. | closed |
| T-03-12-03 | Information disclosure | Committing the large OSM cache | low | mitigate | data/ and cache/ are git-ignored (plan 03-01), and the instructions say not to commit data/ | closed |
| T-03-12-04 | Denial of service | Overpass rate limits during the build | low | accept | One-time human-run build with retry guidance. The runtime never downloads. | closed |
| T-03-12-05 | Information disclosure | Personal data in curated settlements | low | mitigate | Settlement-level columns only. The loader rejects unknown columns (extra="forbid"). | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-03-01 | T-03-01-SC | Phase 3 installs no external packages; the uv.lock diff adds only the editable workspace member `agent-shelter` | plan 03-01 threat model, confirmed by audit | 2026-10-20 |
| AR-03-02 | T-03-02-05 | Plan contracts carry settlement-level aggregates only, no individual-level fields (Rules 6) | plan 03-02 threat model, confirmed by audit | 2026-10-20 |
| AR-03-03 | T-03-04-06 | PostgreSQL cannot drop an enum value, so the `failed` plan_status is forward-only on downgrade (documented in migration 0006, human-locked D-11) | plan 03-04 threat model, D-11 | 2026-10-20 |
| AR-03-04 | T-03-11-04 | Unauthenticated incident/plan API is GET-only and published on 127.0.0.1 only (carries AR-06 from Phase 2); JWT auth arrives in Phase 4 | plan 03-11 threat model, AR-06 | 2026-10-20 |
| AR-03-05 | T-03-12-04 | Overpass rate limits affect only the one-time human-run OSM build; runtime planning loads the cached graph and never downloads | plan 03-12 threat model, confirmed by audit | 2026-10-20 |

*Accepted risks do not resurface in future audit runs.*

---

## Follow-ups (non-blocking, recorded by the audit)

1. `settlements.pop_source` is nullable at the DB level (migration 0002); NOT NULL is enforced only by `SettlementSeedRow`. Plans label a missing source "unknown". Consider a DB constraint.
2. V8 strictness (T-03-07-01): after WR-04, horizon numbers 1/3/6/60/180/360 always pass and small integers can be grounded by unrelated plan counts. Maintainer decision on unit-anchored numbers.
3. WR-03 occupancy compare-and-set: `tests/integration/test_shelters_db.py` passed in the 2026-10-20 live run, but has no release-from-inactive-shelter case. Add one.
4. WR-01 (skipped): a failed re-plan supersedes the last pending_review plan; audit chain intact. "Current plan" contract to settle in Phase 4.
5. T-03-10-03: crashed-run audit flush sits in `except` + re-raise rather than `finally`; equivalent for crashes.
6. IN-05: the immutability trigger is BEFORE UPDATE only (no DELETE guard) and allows any status transition. No app code does either; add guards in Phase 4.
7. IN-01: legacy Phase 2 `compute_route` least-blocked fallback can route through blocked edges; no non-test caller. Remove before reuse.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-10-20 | 64 | 64 | 0 | gsd-security-auditor (ASVS L1, block_on high) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-10-20

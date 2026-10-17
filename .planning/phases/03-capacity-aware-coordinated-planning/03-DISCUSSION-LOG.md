# Phase 3: Capacity-Aware Coordinated Planning - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-17
**Phase:** 03-capacity-aware-coordinated-planning
**Areas discussed:** Shelter & population data, Road graph for routing, Conflict resolution & LLM, Re-plan triggers in scope

---

## Shelter & population data

| Question | Options | Selected |
|---|---|---|
| Shelter source | Curated seed set / data.gov.in importer now / Synthetic generator | Curated seed set |
| Evacuee groups | Settlements table / Split by household size / You decide | Settlements table |
| Capacity | Seeded capacity × 0.6 / Estimate from building area | Seeded capacity × 0.6 |
| pgvector NL lookup | Defer / Build now | Defer |

---

## Road graph for routing

| Question | Options | Selected |
|---|---|---|
| Graph | Real OSM cached / Bigger synthetic / Both | Real OSM, cached |
| Coverage | Pilot cluster + buffer / Whole AOI bbox | Pilot cluster + buffer |
| Fire horizons | ETA-aware / Worst case (union) | ETA-aware |
| Congestion | Spec BPR 2–3 passes / You decide | Spec BPR, 2–3 passes |

---

## Conflict resolution & LLM

| Question | Options | Selected |
|---|---|---|
| Fix menu (multi) | Re-route next path / Re-match shelter / Split group / Mark unassigned + reason | Re-route, Re-match, Split (not "mark unassigned") |
| Resolver | Deterministic first / LLM chooses, fallback otherwise | Deterministic first |
| Hard fail | Failed plan record / Partial plan flagged | Failed plan record |
| V8 strictness | Strict, fall back on fail / Strict, block plan | Strict, fall back on fail |
| Unplaceable group (follow-up) | Whole plan fails / Allow unassigned, flagged | Whole plan fails |

---

## Re-plan triggers in scope

| Question | Options | Selected |
|---|---|---|
| Triggers (multi) | perimeter_change / road_blocked / shelter_capacity_change / scheduled_refresh + manual | perimeter_change, road_blocked, shelter_capacity_change |
| Runner | On-demand + test harness / Background worker now | On-demand + test harness |
| New version rule | Material diff only / Every re-plan | Material diff only |
| Phase 2 WR-01/WR-03 | Fold both in / Defer | Fold both in |

---

## Claude's Discretion
- CI fixture strategy for k-paths/congestion/capacity, BPR coefficients, penalty magnitudes, fix-menu order, shared-state versioning mechanics, in-process parallel dispatch.

## Deferred Ideas
- pgvector NL shelter lookup; data.gov.in importer; wind_shift / scheduled_refresh / manual triggers; background worker; remaining Phase 2 warnings; "mark unassigned" strategy (rejected).

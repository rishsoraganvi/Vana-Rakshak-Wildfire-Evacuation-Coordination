# Project State

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-10-01)

**Core value:** A human reviewer can quickly understand and safely approve or correct a traceable evacuation plan built from current hazard, route, shelter, and resource data.
**Current focus:** Phase 1 - Foundations and Data Contracts

## Current Position

- Phase: 1 of 6
- Status: Ready to plan
- Progress: 0%
- Last activity: Project initialized from `generatedPlan`

## Decisions and Constraints

- The supplied `generatedPlan` documents are the current product source of truth.
- This is a decision-support prototype, not an operational emergency authority.
- Human approval is mandatory before dissemination.
- Numeric/safety-critical outputs are deterministic and validated; LLM output is bounded to orchestration and grounded text.
- GSD workflow: YOLO mode, standard granularity, parallel execution, research enabled, verifier enabled, plan-check disabled, source grounding enabled.

## Pending Decisions

- Final AOI polygon versus initial bounding box.
- MVP pilot settlement cluster.
- English/Kannada translation scope.
- LLM provider/model and budget.
- Calibration data beyond FIRMS and exact benchmark baselines.

## Next Action

Run `/skill:gsd-plan-phase 1` to create the first executable phase plan.

---
*State initialized: 2026-10-01*
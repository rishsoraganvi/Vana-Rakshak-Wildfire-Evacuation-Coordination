---
phase: 03-capacity-aware-coordinated-planning
plan: 07
subsystem: plan-assembly
tags: [finalize, v8-grounding, rationale-template, provenance, freshness, groq, strict-json-schema, plan-07, plan-08]
requires: [03-02]
provides:
  - "coordinator.planning.finalize: finalize_plan, as_failed, build_freshness, build_provenance, freshness_warnings, SYNTHETIC_WARNING"
  - "coordinator.planning.grounding: GroundingFacts, grounding_facts, check_grounding (V8), number_grounded"
  - "coordinator.planning.rationale_template: template_rationale, template_failure_rationale, compact_plan_summary"
  - "coordinator.llm.groq_adapter: generate_plan_rationale, choose_fix_strategy, FixStrategyChoice, FixStrategyReply, _load_prompt"
  - "apps/coordinator/prompts: plan_rationale_v1.md, fix_strategy_v1.md (versioned control-flow prompts)"
affects: [03-08, 03-09, 03-10, 03-11]
tech-stack:
  added: []
  patterns: ["fail-closed finalization gate", "deterministic template as grounded-by-construction fallback", "enum-only LLM control flow via strict json_schema"]
key-files:
  created:
    - apps/coordinator/src/coordinator/planning/__init__.py
    - apps/coordinator/src/coordinator/planning/finalize.py
    - apps/coordinator/src/coordinator/planning/grounding.py
    - apps/coordinator/src/coordinator/planning/rationale_template.py
    - apps/coordinator/prompts/plan_rationale_v1.md
    - apps/coordinator/prompts/fix_strategy_v1.md
    - apps/coordinator/tests/plan_factory.py
    - apps/coordinator/tests/test_plan_assembly.py
    - apps/coordinator/tests/test_grounding.py
    - apps/coordinator/tests/test_plan_provenance.py
    - apps/coordinator/tests/test_llm_menu.py
  modified:
    - apps/coordinator/src/coordinator/llm/groq_adapter.py
key-decisions:
  - "finalize_plan fails closed: a failed outcome or any failing validator gives status failed with no routes, assignments or dispatches and named reasons; the deterministic template is also re-checked against V8 and a (theoretically impossible) failure produces a failed plan rather than ungrounded review text"
  - "V8 strips plan names from the scanned text before checking registry names and numbers, so a registry name that is a word inside a longer plan name (Bandipur vs Bandipur Shelter) is not a false positive"
  - "Out-of-menu replies from choose_fix_strategy fall back immediately with no repair call; the single repair retry is only for invalid JSON or the wrong shape"
  - "Fix-menu violation keys must match ^V[1-8]:[a-z_]+$ and raise ValueError otherwise, so ids and names cannot reach the payload"
requirements-completed: []
status: complete
duration: 40min
completed: 2026-10-17
actuals:
  tokens: 16800
  tasks: 3
  commits: 5
---

# Phase 3 Plan 07: Plan assembly, V8 grounding, bounded LLM entry points Summary

A `PlanDraft` now becomes an immutable `IntegratedPlan` through a fail-closed S5 gate, with strict V8 rationale grounding and deterministic template replacement, populated freshness and provenance on every plan, and two bounded Groq entry points (an enum-only fix-menu chooser using strict json_schema, and a compact plan-rationale call).

## Tasks

| # | Task | Commit |
|---|------|--------|
| 1 | Tracer: draft to template rationale to V8 to finalize (pending_review and failed plans) | 6f7803d |
| 2 (RED) | Failing tests for V8 names/markdown, freshness, provenance, plan rationale | bb40db0 |
| 2 (GREEN) | Strict V8, build_freshness/build_provenance, generate_plan_rationale | bf717ca |
| 3 (RED) | Failing tests for enum-only fix-menu chooser | e9f1161 |
| 3 (GREEN) | choose_fix_strategy with strict json_schema, one repair retry, deterministic fallback | 045e79c |

Tracer gate (auto mode active): the tracer verify (`test_plan_assembly.py`) passed after commit and again in the final suite, so expansion proceeded.

## What changed

- `planning/finalize.py`: `finalize_plan` takes the failed path for `outcome == "failed"` or any failing validator (reasons are the draft's plus one per violation, for example `V5 group_unassigned: Mudumalai (g0) residual 120 persons - insufficient_capacity`), clearing routes, assignments and dispatches (D-11, D-12). The valid path runs V8 on the LLM text when one exists and is not an adapter fallback; ungrounded text is swapped for the template and V8 is recorded as `replaced` with `ungrounded tokens: ...` (D-13) without blocking. Validation is ordered V1..V7 then V8 so `IntegratedPlan` accepts it. Stale FIRMS/weather and synthetic capacity/population warnings (S9) are appended. `as_failed` rebuilds a plan as failed (keeps plan_id) for the 03-08 in-transaction re-check. `provenance.llm_metadata` is filled from the rationale when the caller left it empty.
- `planning/grounding.py`: facts come from a JSON dump walk that skips geometry, node paths, coordinates, node ids and edge keys. String leaves contribute their digits (timestamps) and uuids. Derived facts are group/route/assignment/etc. counts, total persons, total assigned, unique shelters, horizons 1/3/6 and 60/180/360, and validator ordinals 1-8. Numbers use half-unit tolerance at the displayed precision. Markdown list markers, numbered headings and thousands separators are normalised before scanning.
- `planning/rationale_template.py`: `template_rationale` and `template_failure_rationale` read only plan fields. `compact_plan_summary` carries groups, assignments, routes, alert messages, cluster risk and validator statuses (plus optional freshness) with no node paths, coordinates or WKT.
- `llm/groq_adapter.py`: `generate_rationale` is unchanged. New helpers `_load_prompt`, `_gate`, `_reasoning_kwargs`, `_usage`; `generate_plan_rationale` (compact JSON, `prompt_version` in metadata) and `choose_fix_strategy` (strict json_schema enum, `temperature=llm_control_temperature`, `max_completion_tokens=llm_control_max_tokens`, no streaming or tools, one repair retry, `out_of_menu` / `invalid_output` / `empty_menu` / `error:<Name>` fallbacks).

## Verification

- `pytest apps packages tests/unit -q`: 337 passed, 1 skipped (baseline 291 passed, 1 skipped; 46 new tests including a Hypothesis property that the template always passes V8).
- `ruff check apps/coordinator` clean; new files formatted.
- `mypy` on `coordinator/planning` and `coordinator/llm`: no issues. The local environment also reports `agent_routing` / `networkx` stub import errors in `graph.py` (pre-existing, not touched).
- No network calls: every Groq client is mocked (`FakeGroq` / forbidden-client fixtures).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Shared test builders as a helper module**
- **Found during:** Task 1
- **Issue:** Four test files need identical draft/freshness/provenance builders and a Hypothesis strategy cannot use fixtures.
- **Fix:** Added `apps/coordinator/tests/plan_factory.py` (not in the plan's `files_modified`); imported by sibling tests through pytest's rootdir path handling.
- **Commit:** 6f7803d

**2. [Sequencing note] `freshness_warnings` landed in Task 1**
- Task 1's `finalize_plan` needs it, so it shipped with the tracer; `build_freshness` and `build_provenance` followed in Task 2 as planned.

**3. [Tooling] Accidental formatter run on unrelated tests**
- `ruff format apps/coordinator/tests` reformatted three pre-existing files (`test_audit.py`, `test_graph_structure.py`, `test_groq_adapter.py`) and `ruff format apps/coordinator/src` touched `audit.py` and `runner.py`; all five were restored with `git checkout -- <file>` before committing, so no unrelated change is in any commit.

## Deferred Issues

- `ruff format --check` still flags pre-existing coordinator files (`audit.py`, `runner.py`, three older tests). Out of scope.
- `generate_plan_rationale` and `choose_fix_strategy` are not yet called by the graph; plan 03-09 (resolver) and 03-10 (rewiring) consume them. A live Groq check was not run (the plan has none and the LLM stays off by default).

## Known Stubs

None.

## Threat Flags

None. No new endpoints, auth paths or file access. T-03-07-01..06 are mitigated in code and tests: strict V8 with template replacement and the always-grounded property (01), strict enum menu with membership check and no repair for out-of-menu (02), `IntegratedPlan` S5 plus the finalize gate (03), compact payloads with id/name keys rejected (04, 05), gate before any client with timeout, token caps and deterministic fallback (06).

## Self-Check: PASSED

- Files exist: planning/finalize.py, grounding.py, rationale_template.py, prompts/plan_rationale_v1.md, prompts/fix_strategy_v1.md, tests plan_factory.py, test_plan_assembly.py, test_grounding.py, test_plan_provenance.py, test_llm_menu.py.
- Commits exist: 6f7803d, bb40db0, bf717ca, e9f1161, 045e79c.

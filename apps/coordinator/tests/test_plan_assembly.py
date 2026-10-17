from __future__ import annotations

from coordinator.llm.groq_adapter import RationaleResult
from coordinator.planning.finalize import as_failed, finalize_plan
from plan_factory import (
    NOW,
    failed_draft,
    failing,
    freshness,
    provenance,
    valid_draft,
    valid_until,
)
from wildfire_core.schemas.plan import IntegratedPlan, PlanDraft


def _finalize(draft: PlanDraft, rationale: RationaleResult | None = None) -> IntegratedPlan:
    return finalize_plan(
        draft,
        rationale=rationale,
        registry_names=["Mudumalai", "Kargudi", "Gudalur School", "Masinagudi Hall", "Other Hall"],
        freshness=freshness(),
        provenance=provenance(),
        created_at=NOW,
        valid_until=valid_until(),
        is_simulated=True,
    )


def test_valid_draft_becomes_pending_review_with_v1_to_v8_and_template() -> None:
    plan = _finalize(valid_draft())

    assert plan.status == "pending_review"
    assert [item.validator_id for item in plan.validation] == [f"V{i}" for i in range(1, 9)]
    assert plan.validation[-1].status == "pass"
    assert plan.rationale_source == "template"
    assert plan.rationale_md.startswith("[DETERMINISTIC TEMPLATE] 2 group(s), 200 persons")
    assert "Mudumalai: 120 persons -> Gudalur School, ETA 38.4 min" in plan.rationale_md
    assert plan.routes and plan.shelter_assignments
    assert plan.freshness.computed_at == NOW and plan.provenance.run_id == "run-1"
    assert plan.is_simulated is True


def test_failed_v4_validator_becomes_failed_plan_naming_the_shelter() -> None:
    result = failing(
        "V4",
        "shelter_over_capacity",
        "Gudalur School over capacity by 30 persons",
        shelter_id="s0",
    )
    draft = failed_draft(
        reasons=("V4 failed",),
        results=(result,),
    )

    plan = _finalize(draft)

    assert plan.status == "failed"
    assert plan.routes == () and plan.shelter_assignments == () and plan.dispatches == ()
    assert any("Gudalur School" in reason for reason in plan.failure_reasons)
    assert plan.rationale_md.startswith("[PLAN FAILED]")
    assert plan.validation[-1].validator_id == "V8"


def test_failed_outcome_names_the_unassigned_group() -> None:
    result = failing(
        "V5",
        "group_unassigned",
        "residual 120 persons - insufficient_capacity",
        group_id="g0",
    )
    plan = _finalize(failed_draft(reasons=("no feasible shelter",), results=(result,)))

    assert plan.status == "failed"
    assert (
        "V5 group_unassigned: Mudumalai (g0) residual 120 persons - insufficient_capacity"
        in plan.failure_reasons
    )
    assert plan.freshness is not None and plan.provenance is not None


def test_as_failed_converts_pending_review_plan() -> None:
    plan = _finalize(valid_draft())

    failed = as_failed(plan, ["capacity re-check failed: Gudalur School has 5 beds"])

    assert failed.status == "failed"
    assert failed.plan_id == plan.plan_id
    assert failed.routes == () and failed.shelter_assignments == ()
    assert failed.failure_reasons == ("capacity re-check failed: Gudalur School has 5 beds",)
    assert failed.rationale_source == "template"
    assert failed.rationale_md.startswith("[PLAN FAILED]")

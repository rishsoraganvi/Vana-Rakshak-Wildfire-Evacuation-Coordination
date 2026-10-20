from __future__ import annotations

from typing import Any

from coordinator.llm.groq_adapter import RationaleResult
from coordinator.planning.finalize import finalize_plan
from coordinator.planning.grounding import check_grounding, grounding_facts
from coordinator.planning.rationale_template import (
    template_failure_rationale,
    template_rationale,
)
from hypothesis import given
from hypothesis import strategies as st
from plan_factory import (
    NOW,
    Spec,
    failed_draft,
    failing,
    freshness,
    provenance,
    valid_draft,
    valid_until,
)
from wildfire_core.schemas.plan import PlanAlert

UNKNOWN_UUID = "123e4567-e89b-42d3-a456-426614174000"
KNOWN_UUID = "9b2f3c1e-1a2b-4c3d-8e4f-5a6b7c8d9e0f"
REGISTRY = ["Mudumalai", "Kargudi", "Gudalur School", "Masinagudi Hall", "Other Hall", "Bandipur"]


def _facts(payload: dict[str, Any], registry: list[str] | None = None):
    return grounding_facts(payload, REGISTRY if registry is None else registry)


def _draft_payload() -> dict[str, Any]:
    return valid_draft().model_dump(mode="json")


def test_number_grounded_within_displayed_rounding() -> None:
    facts = _facts(_draft_payload())

    assert check_grounding("120 persons evacuate", facts).status == "pass"
    assert check_grounding("ETA 38.4 min", facts).status == "pass"
    bad = check_grounding("ETA 38.6 min", facts)
    assert bad.status == "fail"
    assert any("38.6" in reason for reason in bad.reasons)


def test_number_absent_from_plan_fails_with_token_listed() -> None:
    result = check_grounding("About 999 people", _facts(_draft_payload()))

    assert result.status == "fail"
    assert result.reasons == ("ungrounded number: 999",)


def test_uuid_must_be_a_plan_id() -> None:
    payload = _draft_payload()
    payload["provenance_ids"] = [KNOWN_UUID]
    facts = _facts(payload)

    assert check_grounding(f"Cluster {KNOWN_UUID}", facts).status == "pass"
    result = check_grounding(f"Cluster {UNKNOWN_UUID}", facts)
    assert result.status == "fail"
    assert result.reasons == (f"unknown id: {UNKNOWN_UUID}",)


def test_registry_name_outside_plan_fails_but_plan_name_passes() -> None:
    facts = _facts(_draft_payload())

    assert check_grounding("Move Mudumalai to Gudalur School", facts).status == "pass"
    result = check_grounding("Move Mudumalai to other hall instead", facts)
    assert result.status == "fail"
    assert result.reasons == ("unknown name: other hall",)


def test_registry_name_inside_longer_plan_name_is_not_a_false_positive() -> None:
    payload = _draft_payload()
    payload["shelter_assignments"][0]["shelter_name"] = "Bandipur Shelter"
    facts = _facts(payload)

    assert check_grounding("Go to Bandipur Shelter", facts).status == "pass"
    assert check_grounding("Go to Bandipur", facts).status == "fail"


def test_name_match_is_whole_word_only() -> None:
    facts = _facts(_draft_payload(), ["Mudumalai", "Gudalur School", "Hall"])

    assert check_grounding("Hallway access is clear", facts).status == "pass"
    assert check_grounding("Use the hall", facts).status == "fail"


def test_markdown_list_markers_and_headings_are_stripped() -> None:
    facts = _facts(_draft_payload())
    text = "## 9) Summary\n9. 120 persons from Mudumalai\n- 80 persons from Kargudi\n* 22.0 min"

    assert check_grounding(text, facts).status == "pass"


def test_thousands_separator_and_timestamps_are_handled() -> None:
    payload = _draft_payload()
    payload["groups"][0]["persons"] = 1200
    payload["shelter_assignments"][0]["persons"] = 1200
    payload["generated"] = "2026-10-17T12:00:00Z"
    facts = _facts(payload)

    assert check_grounding("1,200 persons at 2026-10-17 12:00", facts).status == "pass"


def test_geometry_nodes_and_coordinates_do_not_ground_numbers() -> None:
    facts = _facts(_draft_payload())

    assert check_grounding("Route passes 76.6", facts).status == "fail"
    assert check_grounding("Via node 33", facts).status == "fail"
    assert check_grounding("Distance 4321.5 m", facts).status == "pass"


def test_derived_counts_and_horizons_are_grounded() -> None:
    facts = _facts(_draft_payload())

    text = "2 groups, 2 routes, 200 persons assigned over horizons 1, 3 and 6 h (60/180/360 min)"
    assert check_grounding(text, facts).status == "pass"


def test_small_integers_that_are_not_horizons_or_plan_facts_are_ungrounded() -> None:
    # WR-04: small integers must not pass just because they are small. The draft has 2 groups, 2
    # routes and 7 validators; "V5"/"V8" ordinals in validator ids no longer ground a stray 5/8.
    facts = _facts(_draft_payload())

    for text in ("5 routes were blocked", "4 groups", "8 vehicles", "9 shelters are available"):
        result = check_grounding(text, facts)
        assert result.status == "fail", text
    assert check_grounding("2 shelters, 2 routes, V5 and V8 checked", facts).status == "pass"


@given(
    names=st.lists(
        st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij", min_size=3, max_size=8),
        min_size=10,
        max_size=10,
        unique_by=str.lower,
    ),
    persons=st.lists(st.integers(1, 500), min_size=5, max_size=5),
    etas=st.lists(st.floats(0, 5000, allow_nan=False), min_size=5, max_size=5),
    horizons=st.lists(st.sampled_from([1, 3, 6]), min_size=5, max_size=5),
    count=st.integers(1, 5),
    with_alert=st.booleans(),
)
def test_template_rationale_is_always_grounded(
    names: list[str],
    persons: list[int],
    etas: list[float],
    horizons: list[int],
    count: int,
    with_alert: bool,
) -> None:
    specs = [Spec(names[i], persons[i], names[5 + i], etas[i], horizons[i]) for i in range(count)]
    alerts = (
        (PlanAlert(kind="needs_rescue_response", message="Needs 2 rescue teams"),)
        if with_alert
        else ()
    )
    draft = valid_draft(specs, alerts=alerts)
    facts = grounding_facts(draft.model_dump(mode="json"), [*names, "Zulu Camp"])

    result = check_grounding(template_rationale(draft), facts)

    assert result.status == "pass", result.reasons


def _finalize_with_alert(alert: PlanAlert):
    return finalize_plan(
        valid_draft(alerts=(alert,)),
        rationale=None,
        registry_names=[*REGISTRY, "Beta Village"],
        freshness=freshness(),
        provenance=provenance(),
        created_at=NOW,
        valid_until=valid_until(),
        is_simulated=False,
    )


def test_rescue_alert_naming_a_group_less_settlement_does_not_fail_the_plan() -> None:
    # CR-01 / D-20: a settlement inside the current perimeter has no group, only an alert.
    alert = PlanAlert(
        kind="needs_rescue_response",
        message=(
            "Beta Village is inside the active fire perimeter: needs rescue response "
            "(exempt from evacuation matching)"
        ),
        settlement_id="b",
        settlement_name="Beta Village",
    )

    plan = _finalize_with_alert(alert)

    assert plan.status == "pending_review", plan.failure_reasons
    assert "Beta Village" in plan.rationale_md
    assert plan.validation[-1].validator_id == "V8" and plan.validation[-1].status == "pass"


def test_p90_only_alert_naming_a_group_less_settlement_does_not_fail_the_plan() -> None:
    # CR-01 / D-21: the P90-only warning names a settlement that has no evacuation group.
    alert = PlanAlert(
        kind="p90_only_exposure",
        message=(
            "Other Hall is reached only by the P90 forecast (first at 6h): "
            "monitor, no evacuation group"
        ),
        settlement_id="st-x",
        settlement_name="Other Hall",
    )

    plan = _finalize_with_alert(alert)

    assert plan.status == "pending_review", plan.failure_reasons
    assert "Other Hall" in plan.rationale_md


def test_unnamed_alert_mentioning_a_registry_name_still_fails_closed() -> None:
    # V8 stays strict: a name that is not a plan fact is rejected, so the settlement_name
    # field (not a loosened gate) is what grounds alert text.
    alert = PlanAlert(
        kind="p90_only_exposure",
        message="Beta Village is reached only by the P90 forecast (first at 6h)",
        settlement_id="st-x",
    )

    plan = _finalize_with_alert(alert)

    assert plan.status == "failed"
    assert plan.failure_reasons == ("V8 deterministic rationale failed grounding",)


def test_llm_text_naming_an_unplanned_settlement_is_still_rejected() -> None:
    # The alert's settlement_name grounds that one name only; other registry names stay ungrounded.
    alert = PlanAlert(
        kind="needs_rescue_response",
        message="Beta Village is inside the active fire perimeter: needs rescue response",
        settlement_id="b",
        settlement_name="Beta Village",
    )
    plan = finalize_plan(
        valid_draft(alerts=(alert,)),
        rationale=_llm("Beta Village needs rescue; also move Mudumalai to Bandipur."),
        registry_names=[*REGISTRY, "Beta Village"],
        freshness=freshness(),
        provenance=provenance(),
        created_at=NOW,
        valid_until=valid_until(),
        is_simulated=False,
    )

    assert plan.status == "pending_review"
    assert plan.rationale_source == "template"
    assert plan.validation[-1].status == "replaced"
    assert "unknown name: bandipur" in plan.validation[-1].reasons[0]


def test_failure_template_is_grounded() -> None:
    result = failing("V5", "group_unassigned", "residual 120 persons", group_id="g0")
    draft = failed_draft(
        reasons=("V5 group_unassigned: Mudumalai (g0) residual 120",), results=(result,)
    )
    facts = grounding_facts(draft.model_dump(mode="json"), REGISTRY)

    assert check_grounding(template_failure_rationale(draft), facts).status == "pass"


def _llm(text: str) -> RationaleResult:
    return RationaleResult(text=text, is_fallback=False, model_metadata={"llm_called": True})


def _finalize(rationale: RationaleResult | None):
    return finalize_plan(
        valid_draft(),
        rationale=rationale,
        registry_names=REGISTRY,
        freshness=freshness(),
        provenance=provenance(),
        created_at=NOW,
        valid_until=valid_until(),
        is_simulated=False,
    )


def test_grounded_llm_rationale_is_kept() -> None:
    plan = _finalize(_llm("Mudumalai: 120 persons to Gudalur School. Human review required."))

    assert plan.rationale_source == "llm"
    assert plan.validation[-1].status == "pass"
    assert plan.is_llm_fallback is False
    assert plan.provenance.llm_metadata == {"llm_called": True}


def test_ungrounded_llm_rationale_is_replaced_and_plan_not_blocked() -> None:
    plan = _finalize(_llm("Send 77 persons from Mudumalai to other hall."))

    assert plan.status == "pending_review"
    assert plan.rationale_source == "template"
    assert plan.rationale_md.startswith("[DETERMINISTIC TEMPLATE]")
    v8 = plan.validation[-1]
    assert v8.validator_id == "V8" and v8.status == "replaced"
    assert "ungrounded tokens" in v8.reasons[0] and "77" in v8.reasons[0]
    assert plan.is_llm_fallback is True


def test_fallback_rationale_from_adapter_uses_template_without_replacement_status() -> None:
    fallback = RationaleResult(
        text="[DETERMINISTIC FALLBACK] x", is_fallback=True, model_metadata={}
    )

    plan = _finalize(fallback)

    assert plan.rationale_source == "template"
    assert plan.validation[-1].status == "pass"
    assert plan.is_llm_fallback is True

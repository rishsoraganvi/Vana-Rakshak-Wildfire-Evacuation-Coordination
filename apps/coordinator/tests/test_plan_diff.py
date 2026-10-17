"""Material-change signature and plan diff (D-16): volatile fields never trigger a new version."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from coordinator.planning.diff import is_material_change, material_signature, plan_diff
from coordinator.planning.finalize import finalize_plan
from plan_factory import (
    NOW,
    failed_draft,
    failing,
    freshness,
    provenance,
    valid_draft,
    valid_until,
)
from wildfire_core.schemas.plan import IntegratedPlan, PlanDraft, ValidationResult

NAMES = ["Mudumalai", "Kargudi", "Gudalur School", "Masinagudi Hall"]


def build(draft: PlanDraft | None = None) -> IntegratedPlan:
    return finalize_plan(
        draft or valid_draft(),
        rationale=None,
        registry_names=NAMES,
        freshness=freshness(),
        provenance=provenance(),
        created_at=NOW,
        valid_until=valid_until(),
        is_simulated=True,
    )


def test_volatile_fields_are_not_material() -> None:
    old = build()
    rebuilt = old.model_copy(
        update={
            "plan_id": "11111111-1111-1111-1111-111111111111",
            "created_at": NOW + timedelta(hours=1),
            "rationale_md": "completely different words",
            "warnings": ("a new warning",),
            "routes": tuple(
                route.model_copy(
                    update={
                        "route_id": f"new-{index}",
                        "eta_min": route.eta_min + 7.5,
                        "congested_time_s": route.congested_time_s + 300.0,
                    }
                )
                for index, route in enumerate(old.routes)
            ),
        }
    )

    assert is_material_change(old.model_dump(mode="json"), rebuilt) is False
    diff = plan_diff(old.model_dump(mode="json"), rebuilt)
    assert diff.is_material is False
    assert not (diff.assignments_added or diff.assignments_removed or diff.routes_changed)
    assert diff.validators_changed == {} and diff.status_changed is None


def test_different_shelter_for_a_group_is_material() -> None:
    old = build()
    assignments = list(old.shelter_assignments)
    assignments[0] = assignments[0].model_copy(update={"shelter_id": "s9"})
    routes = list(old.routes)
    routes[0] = routes[0].model_copy(update={"shelter_id": "s9"})
    new = old.model_copy(
        update={"shelter_assignments": tuple(assignments), "routes": tuple(routes)}
    )

    assert is_material_change(old.model_dump(mode="json"), new) is True
    diff = plan_diff(old.model_dump(mode="json"), new)
    assert diff.is_material is True
    assert diff.assignments_added == ("g0->s9",)
    assert diff.assignments_removed == ("g0->s0",)


def test_same_assignments_different_node_path_is_material() -> None:
    old = build()
    routes = list(old.routes)
    routes[1] = routes[1].model_copy(update={"osm_node_path": (11, 44, 22)})
    new = old.model_copy(update={"routes": tuple(routes)})

    assert is_material_change(old.model_dump(mode="json"), new) is True
    diff = plan_diff(old.model_dump(mode="json"), new)
    assert diff.routes_changed == ("g1->s1",)
    assert diff.assignments_added == () and diff.assignments_removed == ()


def test_persons_change_for_same_pair_is_material_and_listed_as_changed() -> None:
    old = build()
    assignments = list(old.shelter_assignments)
    assignments[0] = assignments[0].model_copy(update={"persons": 100})
    new = old.model_copy(update={"shelter_assignments": tuple(assignments)})

    assert is_material_change(old.model_dump(mode="json"), new) is True
    assert plan_diff(old.model_dump(mode="json"), new).assignments_changed == ("g0->s0",)


def test_validator_status_change_is_material() -> None:
    old = build()
    validation = [
        ValidationResult(validator_id="V3", status="flag") if item.validator_id == "V3" else item
        for item in old.validation
    ]
    new = old.model_copy(update={"validation": tuple(validation)})

    assert is_material_change(old.model_dump(mode="json"), new) is True
    assert plan_diff(old.model_dump(mode="json"), new).validators_changed == {
        "V3": ("pass", "flag")
    }


def test_status_change_is_material() -> None:
    old = build()
    failed = build(failed_draft(reasons=["V5 group_unassigned"], results=[failing("V5", "x", "y")]))

    assert is_material_change(old.model_dump(mode="json"), failed) is True
    diff = plan_diff(old.model_dump(mode="json"), failed)
    assert diff.status_changed == ("pending_review", "failed")
    assert diff.is_material is True


def test_phase2_predecessor_and_missing_previous_are_always_material() -> None:
    new = build()
    phase2: dict[str, Any] = {
        "incident_id": new.incident_id,
        "routes": [],
        "rationale_md": "legacy",
    }

    assert is_material_change(phase2, new) is True
    assert plan_diff(phase2, new).is_material is True
    assert is_material_change(None, new) is True
    diff = plan_diff(None, new)
    assert diff.is_material is True
    assert diff.assignments_added == ("g0->s0", "g1->s1")


def test_signature_is_order_independent_sorted_and_deterministic() -> None:
    plan = build()
    shuffled = plan.model_copy(
        update={
            "shelter_assignments": tuple(reversed(plan.shelter_assignments)),
            "routes": tuple(reversed(plan.routes)),
            "validation": tuple(reversed(plan.validation)),
        }
    )

    signature = material_signature(plan)
    assert signature == material_signature(shuffled)
    assert signature == material_signature(plan.model_dump(mode="json"))
    assert list(signature["assignments"]) == sorted(signature["assignments"])
    assert list(signature["routes"]) == sorted(signature["routes"])
    assert list(signature["validators"]) == [f"V{i}" for i in range(1, 9)]
    assert signature["status"] == "pending_review"
    assert material_signature(plan) == material_signature(plan)

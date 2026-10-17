"""Turn a ``PlanDraft`` into an immutable ``IntegratedPlan`` (S5, D-11, D-12, D-13, D-21).

Any failed validator or a failed outcome yields a ``failed`` plan with named reasons and no
approvable content. A valid draft becomes ``pending_review`` only with V1..V8 present. Ungrounded
rationale text is replaced by the deterministic template without blocking the plan.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from wildfire_core.schemas.plan import (
    IntegratedPlan,
    PlanDraft,
    PlanFreshness,
    PlanProvenance,
    ValidationResult,
)

from coordinator.planning.grounding import check_grounding, grounding_facts
from coordinator.planning.rationale_template import (
    PlanLike,
    template_failure_rationale,
    template_rationale,
)

if TYPE_CHECKING:
    from coordinator.llm.groq_adapter import RationaleResult

SYNTHETIC_WARNING = "Shelter capacities/populations are estimates (synthetic); verify before use"
_SHARED_FIELDS = (
    "incident_id",
    "run_id",
    "risk",
    "clusters",
    "fire_results",
    "weather_by_cluster",
    "footprint",
    "groups",
    "alerts",
    "used_fallback",
    "resolver_steps",
    "congestion_passes_used",
    "max_vc_ratio",
)
_APPROVABLE_FIELDS = ("routes", "shelter_assignments", "dispatches")


def freshness_warnings(freshness: PlanFreshness) -> tuple[str, ...]:
    warnings: list[str] = []
    if "firms" in freshness.stale_inputs and freshness.firms_age_min is not None:
        warnings.append(f"FIRMS data {freshness.firms_age_min} min old")
    for item in freshness.stale_inputs:
        if not item.startswith("weather:"):
            continue
        cluster_id = item.removeprefix("weather:")
        age = freshness.weather_age_min_by_cluster.get(cluster_id)
        suffix = f"is {age} min old (stale)" if age is not None else "is stale"
        warnings.append(f"Weather for cluster {cluster_id} {suffix}")
    return tuple(warnings)


def _payload(source: PlanLike, freshness: PlanFreshness) -> dict[str, Any]:
    payload: dict[str, Any] = source.model_dump(mode="json", exclude={"rationale_md"})
    payload["freshness"] = freshness.model_dump(mode="json")
    return payload


def _violation_reasons(plan: PlanLike) -> list[str]:
    names = {group.group_id: group.settlement_name for group in plan.groups}
    reasons: list[str] = []
    for result in plan.validation:
        if result.status != "fail":
            continue
        if not result.violations:
            reasons.extend(f"{result.validator_id} {reason}" for reason in result.reasons)
            continue
        for violation in result.violations:
            if violation.group_id:
                name = names.get(violation.group_id, violation.group_id)
                subject = f"{name} ({violation.group_id}) "
            elif violation.shelter_id:
                subject = f"shelter {violation.shelter_id} "
            else:
                subject = ""
            reasons.append(f"{result.validator_id} {violation.code}: {subject}{violation.detail}")
    return reasons


def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def _with_v8(
    validation: Iterable[ValidationResult], v8: ValidationResult
) -> tuple[ValidationResult, ...]:
    by_id = {item.validator_id: item for item in validation if item.validator_id != "V8"}
    return (*(by_id[key] for key in sorted(by_id)), v8)


def _warnings(
    draft: PlanLike, freshness: PlanFreshness, provenance: PlanProvenance
) -> tuple[str, ...]:
    assigned = {item.shelter_id for item in draft.shelter_assignments}
    synthetic = any(
        snap.capacity_source == "synthetic"
        for snap in provenance.shelter_snapshot
        if snap.shelter_id in assigned
    ) or any(group.pop_source == "synthetic" for group in draft.groups)
    extra = (SYNTHETIC_WARNING,) if synthetic else ()
    return _dedupe((*draft.warnings, *freshness_warnings(freshness), *extra))


def _base(plan: PlanLike) -> dict[str, Any]:
    return {name: getattr(plan, name) for name in _SHARED_FIELDS}


def _failed_plan(
    source: PlanLike,
    *,
    reasons: Sequence[str],
    registry: Iterable[str],
    freshness: PlanFreshness,
    provenance: PlanProvenance,
    base: dict[str, Any],
) -> IntegratedPlan:
    cleared: dict[str, Any] = {
        **base,
        **{name: () for name in _APPROVABLE_FIELDS},
        "status": "failed",
        "failure_reasons": tuple(reasons),
        "freshness": freshness,
        "provenance": provenance,
        "validation": source.validation,
    }
    interim = IntegratedPlan.model_validate(cleared)
    text = template_failure_rationale(interim)
    facts = grounding_facts(_payload(interim, freshness), registry)
    v8 = check_grounding(text, facts)
    return IntegratedPlan.model_validate(
        {
            **cleared,
            "validation": _with_v8(interim.validation, v8),
            "rationale_md": text,
            "rationale_source": "template",
        }
    )


def finalize_plan(
    draft: PlanDraft,
    *,
    rationale: RationaleResult | None,
    registry_names: Iterable[str],
    freshness: PlanFreshness,
    provenance: PlanProvenance,
    created_at: datetime,
    valid_until: datetime,
    is_simulated: bool,
) -> IntegratedPlan:
    registry = tuple(registry_names)
    if rationale is not None and provenance.llm_metadata is None:
        provenance = provenance.model_copy(update={"llm_metadata": rationale.model_metadata})
    base = {
        **_base(draft),
        "warnings": _warnings(draft, freshness, provenance),
        "created_at": created_at,
        "valid_until": valid_until,
        "is_simulated": is_simulated,
        "is_llm_fallback": rationale is not None,
    }

    def failed(reasons: Sequence[str]) -> IntegratedPlan:
        return _failed_plan(
            draft,
            reasons=reasons,
            registry=registry,
            freshness=freshness,
            provenance=provenance,
            base=base,
        )

    if draft.outcome == "failed" or any(item.status == "fail" for item in draft.validation):
        return failed(_dedupe((*draft.failure_reasons, *_violation_reasons(draft))))

    facts = grounding_facts(_payload(draft, freshness), registry)
    template = template_rationale(draft)
    if check_grounding(template, facts).status == "fail":
        # Cannot happen by construction; fail closed rather than send ungrounded text to review.
        return failed(("V8 deterministic rationale failed grounding",))

    candidate = rationale.text.strip() if rationale and not rationale.is_fallback else ""
    text = template
    source: Literal["llm", "template"] = "template"
    v8 = ValidationResult(validator_id="V8", status="pass")
    if candidate:
        verdict = check_grounding(candidate, facts)
        if verdict.status == "pass":
            text, source = candidate, "llm"
        else:
            reason = "ungrounded tokens: " + "; ".join(verdict.reasons)
            v8 = ValidationResult(validator_id="V8", status="replaced", reasons=(reason,))
    base["is_llm_fallback"] = rationale is not None and source == "template"

    return IntegratedPlan(
        **base,
        status="pending_review",
        freshness=freshness,
        provenance=provenance,
        routes=draft.routes,
        shelter_assignments=draft.shelter_assignments,
        dispatches=draft.dispatches,
        failure_reasons=(),
        validation=_with_v8(draft.validation, v8),
        rationale_md=text,
        rationale_source=source,
    )


def as_failed(plan: IntegratedPlan, reasons: Sequence[str]) -> IntegratedPlan:
    """Rebuild ``plan`` as failed (for example when the in-transaction capacity re-check fails)."""
    base = {
        **_base(plan),
        "plan_id": plan.plan_id,
        "version": plan.version,
        "parent_plan_id": plan.parent_plan_id,
        "created_at": plan.created_at,
        "valid_until": plan.valid_until,
        "warnings": plan.warnings,
        "is_simulated": plan.is_simulated,
        "is_llm_fallback": plan.is_llm_fallback,
    }
    return _failed_plan(
        plan,
        reasons=_dedupe((*plan.failure_reasons, *reasons)),
        registry=[group.settlement_name for group in plan.groups],
        freshness=plan.freshness,
        provenance=plan.provenance,
        base=base,
    )

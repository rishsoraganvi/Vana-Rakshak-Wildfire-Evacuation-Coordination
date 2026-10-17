"""Shared result builder for the structural validators."""

from __future__ import annotations

from typing import Literal

from wildfire_core.schemas.plan import ValidationResult, ViolationRecord

ValidatorId = Literal["V1", "V2", "V3", "V4", "V5", "V6", "V7"]


def build_result(
    validator_id: ValidatorId,
    violations: list[ViolationRecord],
    *,
    flag_only: bool = False,
) -> ValidationResult:
    """pass with no violations, else fail (or flag for V3 P90 hits) with one reason each."""
    if not violations:
        return ValidationResult(validator_id=validator_id, status="pass")
    return ValidationResult(
        validator_id=validator_id,
        status="flag" if flag_only else "fail",
        reasons=tuple(item.detail for item in violations),
        violations=tuple(violations),
    )

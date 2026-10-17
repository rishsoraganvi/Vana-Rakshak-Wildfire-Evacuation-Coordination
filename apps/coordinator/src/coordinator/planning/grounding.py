"""V8: strict grounding of rationale text against plan data (D-13, S4).

Numbers must match a plan fact within displayed rounding; uuids must be plan ids. Geometry,
node paths and coordinates never count as facts, so they cannot ground arbitrary numbers.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from wildfire_core.schemas.plan import ValidationResult

NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
FACT_NUM = re.compile(r"\d+(?:\.\d+)?")
_LIST_MARKER = re.compile(
    r"^[ 	]*(?:#{1,6}[ 	]+)?(?:(?:[-*+]|\d+[.)])[ 	]+)?", re.MULTILINE
)
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)

NAME_KEYS = frozenset({"settlement_name", "shelter_name", "name"})
EXCLUDED_KEYS = frozenset(
    {
        "osm_node_path",
        "osm_edge_keys",
        "path_lonlat",
        "footprint",
        "edge_status_snapshot",
        "edge",
        "p90_flag_edge_indices",
        "origin_node",
        "destination_node",
        "node",
        "u",
        "v",
        "key",
        "lat",
        "lon",
        "centroid_lat",
        "centroid_lon",
        "bbox_west",
        "bbox_south",
        "bbox_east",
        "bbox_north",
        "hotspot_ids",
        "rationale_md",
    }
)
_COUNTED_KEYS = (
    "groups",
    "routes",
    "shelter_assignments",
    "clusters",
    "alerts",
    "fire_results",
    "risk",
    "dispatches",
    "warnings",
    "resolver_steps",
    "validation",
    "failure_reasons",
)
# Forecast horizons in hours and minutes, plus validator ordinals V1..V8.
_FIXED_FACTS = frozenset({1.0, 3.0, 6.0, 60.0, 180.0, 360.0, 2.0, 4.0, 5.0, 7.0, 8.0})


@dataclass(frozen=True)
class GroundingFacts:
    numbers: frozenset[float]
    ids: frozenset[str]
    plan_names: frozenset[str]
    registry_names: frozenset[str]


def _excluded(key: str) -> bool:
    return key in EXCLUDED_KEYS or key.endswith("_wkt")


def _walk(node: Any, key: str, numbers: set[float], ids: set[str], names: set[str]) -> None:
    if _excluded(key) or isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        if math.isfinite(node):
            numbers.add(float(node))
    elif isinstance(node, str):
        ids.update(match.lower() for match in UUID.findall(node))
        if key in NAME_KEYS:
            names.add(node.strip().lower())
        numbers.update(float(token) for token in FACT_NUM.findall(UUID.sub(" ", node)))
    elif isinstance(node, Mapping):
        for child_key, child in node.items():
            child_name = str(child_key)
            if UUID.fullmatch(child_name):
                ids.add(child_name.lower())
            _walk(child, child_name, numbers, ids, names)
    elif isinstance(node, (list, tuple)):
        for child in node:
            _walk(child, key, numbers, ids, names)


def _derived_numbers(payload: Mapping[str, Any]) -> set[float]:
    derived = {float(len(payload[name])) for name in _COUNTED_KEYS if name in payload}
    groups = payload.get("groups") or ()
    assignments = payload.get("shelter_assignments") or ()
    derived.add(float(sum(int(group.get("persons", 0)) for group in groups)))
    derived.add(float(sum(int(item.get("persons", 0)) for item in assignments)))
    derived.add(float(len({item.get("shelter_id") for item in assignments})))
    return derived


def grounding_facts(payload: Mapping[str, Any], registry_names: Iterable[str]) -> GroundingFacts:
    """Collect facts from a JSON-mode dump of a draft or plan (rationale text excluded)."""
    numbers: set[float] = set(_FIXED_FACTS)
    ids: set[str] = set()
    names: set[str] = set()
    _walk(dict(payload), "", numbers, ids, names)
    numbers |= _derived_numbers(payload)
    return GroundingFacts(
        numbers=frozenset(numbers),
        ids=frozenset(ids),
        plan_names=frozenset(names),
        registry_names=frozenset(name.strip().lower() for name in registry_names if name.strip()),
    )


def number_grounded(token: str, facts: frozenset[float]) -> bool:
    decimals = len(token.split(".")[1]) if "." in token else 0
    value = float(token)
    tolerance = 0.5 * 10 ** (-decimals) + 1e-9
    return any(abs(fact - value) <= tolerance for fact in facts)


def _word(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE)


def check_grounding(text: str, facts: GroundingFacts) -> ValidationResult:
    reasons: list[str] = []
    for found in UUID.findall(text):
        if found.lower() not in facts.ids:
            reasons.append(f"unknown id: {found}")
    # Strip list markers / heading numbers and thousands separators, then plan names (their own
    # digits are plan facts and a registry name may be a word inside a longer plan name).
    scan = _THOUSANDS.sub("", _LIST_MARKER.sub("", UUID.sub(" ", text)))
    for name in sorted(facts.plan_names, key=len, reverse=True):
        if name:
            scan = _word(name).sub(" ", scan)
    for name in sorted(facts.registry_names - facts.plan_names):
        if _word(name).search(scan):
            reasons.append(f"unknown name: {name}")
    for token in NUM.findall(scan):
        if not number_grounded(token, facts.numbers):
            reasons.append(f"ungrounded number: {token}")
    unique = tuple(dict.fromkeys(reasons))
    return ValidationResult(validator_id="V8", status="fail" if unique else "pass", reasons=unique)

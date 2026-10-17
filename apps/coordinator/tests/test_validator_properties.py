"""Hypothesis invariants for capacity and double-booking validators (Rules section 8)."""

from __future__ import annotations

from collections import defaultdict

from coordinator.validators.capacity_checks import (
    check_v4_capacity,
    check_v5_complete,
    check_v6_dispatches,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from validator_factory import (
    SAFE_PATH,
    footprint,
    make_assignment,
    make_candidate,
    make_ctx,
    make_group,
    make_route,
)
from wildfire_core.schemas.plan import Dispatch

SHELTER_IDS = ("s1", "s2", "s3")
GROUP_IDS = ("g1", "g2", "g3", "g4")


@settings(max_examples=200, deadline=None)
@given(
    available=st.fixed_dictionaries({sid: st.integers(0, 60) for sid in SHELTER_IDS}),
    pairs=st.lists(
        st.tuples(st.sampled_from(GROUP_IDS), st.sampled_from(SHELTER_IDS)),
        max_size=8,
        unique=True,
    ),
    sizes=st.lists(st.integers(0, 40), min_size=8, max_size=8),
)
def test_v4_passes_iff_every_shelter_is_within_capacity(
    available: dict[str, int], pairs: list[tuple[str, str]], sizes: list[int]
) -> None:
    candidates = [make_candidate(sid, available=cap) for sid, cap in available.items()]
    ctx = make_ctx(footprint(), candidates=candidates)
    placed = list(zip(pairs, sizes, strict=False))
    assignments = [make_assignment(g, s, n, available=available[s]) for (g, s), n in placed]
    routes = [make_route(SAFE_PATH, group_id=g, shelter_id=s, persons=n) for (g, s), n in placed]
    used: dict[str, int] = defaultdict(int)
    for (_group, shelter), count in placed:
        used[shelter] += count
    within = all(used[sid] <= available[sid] for sid in SHELTER_IDS)
    result = check_v4_capacity(assignments, routes, ctx)
    assert (result.status == "pass") == within


@settings(max_examples=200, deadline=None)
@given(
    sizes=st.lists(st.integers(1, 50), min_size=1, max_size=5),
    deltas=st.lists(st.integers(-3, 3), min_size=5, max_size=5),
    splits=st.lists(st.integers(1, 3), min_size=5, max_size=5),
)
def test_v5_passes_iff_every_group_sum_equals_its_persons(
    sizes: list[int], deltas: list[int], splits: list[int]
) -> None:
    groups = [make_group(f"g{i}", size) for i, size in enumerate(sizes)]
    assignments = []
    expected_ok = True
    for i, size in enumerate(sizes):
        assigned = max(0, size + deltas[i])
        expected_ok &= assigned == size
        base, rest = divmod(assigned, splits[i])
        for part in range(splits[i]):
            persons = base + (rest if part == 0 else 0)
            assignments.append(make_assignment(f"g{i}", f"s{part + 1}", persons))
    result = check_v5_complete(groups, assignments, {})
    assert (result.status == "pass") == expected_ok


@settings(max_examples=200, deadline=None)
@given(vehicle_ids=st.lists(st.sampled_from(("v1", "v2", "v3", "v4", "v5", "v6")), max_size=8))
def test_v6_fails_iff_a_vehicle_appears_twice(vehicle_ids: list[str]) -> None:
    dispatches = [Dispatch(vehicle_id=vid, task="evacuate", eta_min=1.0) for vid in vehicle_ids]
    result = check_v6_dispatches(dispatches)
    has_duplicate = len(set(vehicle_ids)) != len(vehicle_ids)
    assert (result.status == "fail") == has_duplicate

from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from coordinator.llm import groq_adapter
from coordinator.planning.finalize import (
    SYNTHETIC_WARNING,
    as_failed,
    build_freshness,
    build_provenance,
    finalize_plan,
    freshness_warnings,
)
from coordinator.planning.rationale_template import compact_plan_summary
from plan_factory import (
    NOW,
    failed_draft,
    failing,
    freshness,
    provenance,
    valid_draft,
    valid_until,
)
from pydantic import SecretStr
from wildfire_core.config import load_settings
from wildfire_core.schemas.phase2 import WeatherSnapshot
from wildfire_core.schemas.plan import ShelterSnapshot


def _weather(age_min: int | None, *, stale: bool = False, valid_time: datetime = NOW):
    return WeatherSnapshot(
        valid_time=valid_time,
        wind_speed_ms=4.0,
        wind_dir_deg=90.0,
        rh_pct=40.0,
        temperature_c=30.0,
        is_stale=stale,
        age_min=age_min,
    )


def test_build_freshness_computes_ages_and_stale_inputs() -> None:
    result = build_freshness(
        computed_at=NOW,
        latest_hotspot_at=NOW - timedelta(minutes=200),
        weather_by_cluster={"c1": _weather(30), "c2": _weather(95, stale=True)},
        graph_built_at=NOW - timedelta(days=1),
        stale_firms_min=180,
    )

    assert result.firms_age_min == 200
    assert result.weather_age_min_by_cluster == {"c1": 30, "c2": 95}
    assert result.weather_age_min_max == 95
    assert result.stale_inputs == ("firms", "weather:c2")
    assert result.graph_built_at == NOW - timedelta(days=1)


def test_build_freshness_without_hotspot_time_or_weather() -> None:
    result = build_freshness(
        computed_at=NOW,
        latest_hotspot_at=None,
        weather_by_cluster={},
        graph_built_at=None,
        stale_firms_min=180,
    )

    assert result.firms_age_min is None
    assert result.weather_age_min_max is None
    assert result.stale_inputs == ()


def test_build_freshness_falls_back_to_valid_time_when_age_missing() -> None:
    result = build_freshness(
        computed_at=NOW,
        latest_hotspot_at=NOW - timedelta(minutes=10),
        weather_by_cluster={"c1": _weather(None, valid_time=NOW - timedelta(minutes=45))},
        graph_built_at=None,
        stale_firms_min=180,
    )

    assert result.weather_age_min_by_cluster == {"c1": 45}
    assert result.stale_inputs == ()


def test_freshness_warnings_text() -> None:
    fresh = freshness(
        firms_age_min=200,
        weather_age_min_by_cluster={"c2": 95},
        weather_age_min_max=95,
        stale_inputs=("firms", "weather:c2"),
    )

    assert freshness_warnings(fresh) == (
        "FIRMS data 200 min old",
        "Weather for cluster c2 is 95 min old (stale)",
    )
    assert freshness_warnings(freshness()) == ()


def test_build_provenance_is_fully_populated() -> None:
    result = build_provenance(
        run_id="run-9",
        trigger_id="trg-1",
        state_version=4,
        hotspot_ids=["h1", "h2"],
        cluster_ids=["c1"],
        fire_run_ids=["f1"],
        fire_seeds=[42, 43],
        weather_valid_times={"c1": NOW},
        weather_provider="open_meteo",
        graph_source="osm",
        graph_mtime=NOW,
        graph_node_count=10,
        graph_edge_count=20,
        shelter_snapshot=[
            ShelterSnapshot(
                shelter_id="s1",
                occupancy=3,
                usable_capacity=60,
                is_active=True,
                capacity_source="synthetic",
            )
        ],
        settlement_sources={"g0": "census"},
        params={"k_paths": 3, "shelter_usable_factor": 0.6},
        llm_metadata=None,
    )

    assert result.run_id == "run-9" and result.state_version == 4
    assert result.hotspot_ids == ("h1", "h2") and result.fire_seeds == (42, 43)
    assert result.shelter_snapshot[0].capacity_source == "synthetic"
    assert result.settlement_sources == {"g0": "census"}
    assert result.params["k_paths"] == 3
    assert result.graph_node_count == 10


def _finalize(draft, **kwargs: Any):
    return finalize_plan(
        draft,
        rationale=None,
        registry_names=["Mudumalai", "Kargudi"],
        freshness=kwargs.pop("fresh", freshness()),
        provenance=kwargs.pop("prov", provenance()),
        created_at=NOW,
        valid_until=valid_until(),
        is_simulated=False,
    )


def test_pending_and_failed_plans_carry_populated_freshness_and_provenance() -> None:
    pending = _finalize(valid_draft())
    result = failing("V5", "group_unassigned", "residual 5 persons", group_id="g0")
    failed = _finalize(failed_draft(reasons=("x",), results=(result,)))

    for plan in (pending, failed):
        assert plan.freshness.computed_at == NOW
        assert plan.provenance.run_id == "run-1"
        assert plan.provenance.graph_node_count == 100
    assert pending.status == "pending_review" and failed.status == "failed"


def test_stale_inputs_become_plan_warnings() -> None:
    fresh = freshness(firms_age_min=200, stale_inputs=("firms",))

    plan = _finalize(valid_draft(warnings=("existing",)), fresh=fresh)

    assert plan.warnings == ("existing", "FIRMS data 200 min old")


def test_synthetic_capacity_or_population_adds_estimate_warning() -> None:
    snapshot = ShelterSnapshot(
        shelter_id="s0",
        occupancy=0,
        usable_capacity=200,
        is_active=True,
        capacity_source="synthetic",
    )
    by_capacity = _finalize(valid_draft(), prov=provenance(shelter_snapshot=(snapshot,)))
    by_population = _finalize(valid_draft(pop_source="synthetic"))
    neither = _finalize(valid_draft())

    assert SYNTHETIC_WARNING in by_capacity.warnings
    assert SYNTHETIC_WARNING in by_population.warnings
    assert SYNTHETIC_WARNING not in neither.warnings


def test_as_failed_keeps_freshness_and_provenance() -> None:
    failed = as_failed(_finalize(valid_draft()), ["recheck failed"])

    assert failed.freshness.computed_at == NOW and failed.provenance.run_id == "run-1"


def test_compact_summary_has_no_paths_coordinates_or_wkt() -> None:
    summary = compact_plan_summary(valid_draft(), freshness())
    text = json.dumps(summary)

    assert "osm_node_path" not in text and "path_lonlat" not in text
    assert "POLYGON" not in text and '"lat"' not in text
    assert summary["validators"]["V1"] == "pass"
    assert summary["routes"][0]["horizon_h"] == 3
    assert len(text) < 3000


def _llm_settings(**extra: Any):
    update: dict[str, Any] = {
        "groq_api_key": SecretStr("test-key"),
        "llm_enabled": True,
        "llm_provider": "groq",
        "llm_model": "test-model",
    }
    update.update(extra)
    return load_settings().model_copy(update=update)


def test_generate_plan_rationale_disabled_never_constructs_a_client(monkeypatch) -> None:
    class Forbidden:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            raise AssertionError("client must not be constructed")

    monkeypatch.setattr(groq_adapter, "Groq", Forbidden)
    monkeypatch.setattr(groq_adapter.time, "sleep", lambda _s: pytest.fail("no sleep"))

    result = groq_adapter.generate_plan_rationale({"groups": []}, _llm_settings(llm_enabled=False))

    assert result.is_fallback is True
    assert result.model_metadata["fallback_reason"] == "llm_disabled"
    assert result.model_metadata["llm_called"] is False


def test_generate_plan_rationale_sends_compact_payload_and_records_prompt_version(
    monkeypatch,
) -> None:
    requests: list[dict[str, Any]] = []

    class FakeGroq:
        def __init__(self, api_key: str) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: (
                        requests.append(kwargs)
                        or SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    finish_reason="stop", message=SimpleNamespace(content=" Text. ")
                                )
                            ]
                        )
                    )
                )
            )

    monkeypatch.setattr(groq_adapter, "Groq", FakeGroq)
    monkeypatch.setattr(groq_adapter.time, "sleep", lambda _s: None)
    settings = _llm_settings(llm_model="openai/gpt-oss-20b")
    summary = compact_plan_summary(valid_draft(), freshness())

    result = groq_adapter.generate_plan_rationale(summary, settings)

    assert result.text == "Text." and result.is_fallback is False
    assert result.model_metadata["prompt_version"] == "plan_rationale_v1"
    request = requests[0]
    assert request["max_completion_tokens"] == settings.llm_rationale_max_tokens
    assert request["timeout"] == settings.llm_request_timeout_s
    assert request["reasoning_effort"] == "low"
    user = request["messages"][1]["content"]
    assert "osm_node_path" not in user and "POLYGON" not in user and "path_lonlat" not in user
    assert json.loads(user)["groups"][0]["settlement_name"] == "Mudumalai"
    assert "Human review required" in request["messages"][0]["content"]


def test_generate_plan_rationale_error_falls_back(monkeypatch) -> None:
    class Failing:
        def __init__(self, api_key: str) -> None:
            raise RuntimeError("down")

    monkeypatch.setattr(groq_adapter, "Groq", Failing)
    monkeypatch.setattr(groq_adapter.time, "sleep", lambda _s: None)

    result = groq_adapter.generate_plan_rationale({"groups": []}, _llm_settings())

    assert result.is_fallback is True
    assert result.model_metadata["fallback_reason"] == "error:RuntimeError"
    assert "test-key" not in json.dumps(result.model_metadata)

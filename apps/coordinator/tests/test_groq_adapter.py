import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from coordinator.llm import groq_adapter
from pydantic import SecretStr
from wildfire_core.config import load_settings
from wildfire_core.schemas.phase2 import FireSpreadResult, RouteResult, WeatherSnapshot


def make_inputs() -> tuple[FireSpreadResult, WeatherSnapshot, list[RouteResult]]:
    fire_result = FireSpreadResult(
        cluster_id="cluster-1",
        current_perimeter_wkt="POLYGON EMPTY",
        p50_1h_wkt="POLYGON EMPTY",
        p50_3h_wkt="POLYGON EMPTY",
        p50_6h_wkt="POLYGON EMPTY",
        p90_1h_wkt="POLYGON EMPTY",
        p90_3h_wkt="POLYGON EMPTY",
        p90_6h_wkt="POLYGON EMPTY",
        affected_area_km2=12.5,
        spread_direction_deg=90.0,
        spread_rate_m_per_h=250.0,
        confidence="medium",
    )
    weather = WeatherSnapshot(
        valid_time=datetime(2026, 10, 14, tzinfo=UTC),
        wind_speed_ms=4.0,
        wind_dir_deg=90.0,
        rh_pct=40.0,
        temperature_c=32.0,
    )
    route = RouteResult(
        group_id="group-1",
        origin_cluster_id="cluster-1",
        osm_node_path=(1, 2),
        total_distance_m=1000.0,
        estimated_travel_time_s=120.0,
        safety_classification="safe",
    )
    return fire_result, weather, [route]


def llm_settings(**extra):
    update = {
        "groq_api_key": SecretStr("test-key"),
        "llm_enabled": True,
        "llm_provider": "groq",
        "llm_model": "test-model",
    }
    update.update(extra)
    return load_settings().model_copy(update=update)


def test_generate_rationale_uses_grounded_payload_and_trims_response(monkeypatch) -> None:
    fire_result, weather, routes = make_inputs()
    settings = llm_settings()
    requests: list[dict[str, object]] = []
    sleep_calls: list[int] = []

    class FakeGroq:
        def __init__(self, api_key: str) -> None:
            assert api_key == "test-key"
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: requests.append(kwargs)
                    or SimpleNamespace(
                        model="served-model",
                        usage=SimpleNamespace(
                            prompt_tokens=11, completion_tokens=22, total_tokens=33
                        ),
                        choices=[
                            SimpleNamespace(
                                finish_reason="stop",
                                message=SimpleNamespace(content="  Grounded rationale.  "),
                            )
                        ],
                    )
                )
            )

    monkeypatch.setattr(groq_adapter, "Groq", FakeGroq)
    monkeypatch.setattr(groq_adapter.time, "sleep", sleep_calls.append)

    result = groq_adapter.generate_rationale([fire_result], weather, routes, settings)

    assert result.text == "Grounded rationale."
    assert result.is_fallback is False
    assert sleep_calls == [1]
    assert requests[0]["model"] == "test-model"
    assert requests[0]["timeout"] == settings.llm_request_timeout_s
    assert "12.5" in requests[0]["messages"][1]["content"]
    assert "cluster-1" in requests[0]["messages"][1]["content"]
    assert "fire_results" in requests[0]["messages"][1]["content"]
    metadata = result.model_metadata
    assert metadata["provider"] == "groq"
    assert metadata["model"] == "test-model"
    assert metadata["llm_called"] is True
    assert metadata["is_fallback"] is False
    assert metadata["fallback_reason"] is None
    assert metadata["finish_reason"] == "stop"
    assert metadata["usage"] == {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33}
    assert metadata["response_model"] == "served-model"


def test_generate_rationale_falls_back_on_groq_error(monkeypatch) -> None:
    fire_result, weather, routes = make_inputs()
    settings = llm_settings()

    class FailingGroq:
        def __init__(self, api_key: str) -> None:
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(groq_adapter, "Groq", FailingGroq)
    monkeypatch.setattr(groq_adapter.time, "sleep", lambda _seconds: None)

    result = groq_adapter.generate_rationale([fire_result], weather, routes, settings)

    assert result.is_fallback is True
    assert result.text.startswith("[DETERMINISTIC FALLBACK]")
    assert "12.5 km2" in result.text
    assert "Routes: 1" in result.text
    assert "LLM error: RuntimeError" in result.text
    assert result.model_metadata["fallback_reason"] == "error:RuntimeError"
    assert result.model_metadata["is_fallback"] is True
    assert "test-key" not in json.dumps(result.model_metadata)


def test_generate_rationale_falls_back_on_empty_response(monkeypatch) -> None:
    fire_result, weather, routes = make_inputs()
    settings = llm_settings()

    class EmptyGroq:
        def __init__(self, api_key: str) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_kwargs: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="  "))]
                    )
                )
            )

    monkeypatch.setattr(groq_adapter, "Groq", EmptyGroq)
    monkeypatch.setattr(groq_adapter.time, "sleep", lambda _seconds: None)

    result = groq_adapter.generate_rationale([fire_result], weather, routes, settings)

    assert result.is_fallback is True
    assert "LLM error: ValueError" in result.text


def _forbid_groq(monkeypatch) -> list[int]:
    sleep_calls: list[int] = []

    class ForbiddenGroq:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("Groq client must not be constructed")

    monkeypatch.setattr(groq_adapter, "Groq", ForbiddenGroq)
    monkeypatch.setattr(groq_adapter.time, "sleep", sleep_calls.append)
    return sleep_calls


def test_generate_rationale_skips_provider_when_disabled(monkeypatch) -> None:
    fire_result, weather, routes = make_inputs()
    sleep_calls = _forbid_groq(monkeypatch)

    result = groq_adapter.generate_rationale(
        [fire_result], weather, routes, llm_settings(llm_enabled=False)
    )

    assert result.is_fallback is True
    assert result.model_metadata["fallback_reason"] == "llm_disabled"
    assert result.model_metadata["llm_called"] is False
    assert "LLM unavailable: llm_disabled" in result.text
    assert sleep_calls == []


def test_generate_rationale_requires_groq_provider(monkeypatch) -> None:
    fire_result, weather, routes = make_inputs()
    sleep_calls = _forbid_groq(monkeypatch)

    result = groq_adapter.generate_rationale(
        [fire_result], weather, routes, llm_settings(llm_provider="anthropic")
    )

    assert result.model_metadata["fallback_reason"] == "provider_not_groq"
    assert result.model_metadata["llm_called"] is False
    assert sleep_calls == []


def test_generate_rationale_requires_model(monkeypatch) -> None:
    fire_result, weather, routes = make_inputs()
    sleep_calls = _forbid_groq(monkeypatch)

    result = groq_adapter.generate_rationale(
        [fire_result], weather, routes, llm_settings(llm_model="")
    )

    assert result.model_metadata["fallback_reason"] == "model_not_configured"
    assert sleep_calls == []


def test_generate_rationale_requires_api_key(monkeypatch) -> None:
    fire_result, weather, routes = make_inputs()
    sleep_calls = _forbid_groq(monkeypatch)

    result = groq_adapter.generate_rationale(
        [fire_result], weather, routes, llm_settings(groq_api_key=SecretStr(""))
    )

    assert result.model_metadata["fallback_reason"] == "api_key_missing"
    assert result.is_fallback is True
    assert sleep_calls == []


def _capturing_groq(monkeypatch) -> list[dict[str, object]]:
    requests: list[dict[str, object]] = []

    class CapturingGroq:
        def __init__(self, api_key: str) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: requests.append(kwargs)
                    or SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
                    )
                )
            )

    monkeypatch.setattr(groq_adapter, "Groq", CapturingGroq)
    monkeypatch.setattr(groq_adapter.time, "sleep", lambda _seconds: None)
    return requests


def test_generate_rationale_gpt_oss_reasoning_params(monkeypatch) -> None:
    fire_result, weather, routes = make_inputs()
    requests = _capturing_groq(monkeypatch)
    settings = llm_settings(llm_model="openai/gpt-oss-20b")

    result = groq_adapter.generate_rationale([fire_result], weather, routes, settings)

    assert requests[0]["reasoning_effort"] == "low"
    assert requests[0]["include_reasoning"] is False
    assert requests[0]["max_completion_tokens"] == settings.llm_rationale_max_tokens
    assert "max_tokens" not in requests[0]
    assert result.model_metadata["reasoning_effort"] == "low"


def test_generate_rationale_plain_model_has_no_reasoning_params(monkeypatch) -> None:
    fire_result, weather, routes = make_inputs()
    requests = _capturing_groq(monkeypatch)

    result = groq_adapter.generate_rationale([fire_result], weather, routes, llm_settings())

    assert "reasoning_effort" not in requests[0]
    assert "include_reasoning" not in requests[0]
    assert result.model_metadata["reasoning_effort"] is None


def test_default_llm_config_from_defaults_yaml(monkeypatch) -> None:
    for name in ("LLM_ENABLED", "LLM_PROVIDER", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings(Path("config/defaults.yaml"))

    assert settings.llm_provider == "groq"
    assert settings.llm_model == "openai/gpt-oss-20b"
    assert settings.llm_enabled is False


def test_blank_env_value_does_not_shadow_config_default(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "")

    settings = load_settings(Path("config/defaults.yaml"))

    assert settings.llm_model == "openai/gpt-oss-20b"


def test_generate_rationale_payload_omits_bulky_geometry(monkeypatch) -> None:
    fire_result, weather, routes = make_inputs()
    requests = _capturing_groq(monkeypatch)

    groq_adapter.generate_rationale([fire_result], weather, routes, llm_settings())

    payload = json.loads(requests[0]["messages"][1]["content"])
    assert "p50_1h_wkt" not in payload["fire_results"][0]
    assert "current_perimeter_wkt" not in payload["fire_results"][0]
    assert payload["fire_results"][0]["affected_area_km2"] == 12.5
    assert "osm_node_path" not in payload["routes"][0]
    assert payload["routes"][0]["path_node_count"] == 2

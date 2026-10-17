from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from coordinator.llm import groq_adapter
from pydantic import SecretStr
from wildfire_core.config import load_settings

ALLOWED = ("next_path", "rematch", "split")
COUNTS = {"V4:shelter_over_capacity": 2, "V5:group_unassigned": 1}
UUID = "123e4567-e89b-42d3-a456-426614174000"


def _settings(**extra: Any):
    update: dict[str, Any] = {
        "groq_api_key": SecretStr("test-key"),
        "llm_enabled": True,
        "llm_provider": "groq",
        "llm_model": "openai/gpt-oss-20b",
    }
    update.update(extra)
    return load_settings().model_copy(update=update)


def _install(monkeypatch, replies: list[Any]) -> list[dict[str, Any]]:
    """Scripted Groq: each reply is message content (str) or an Exception to raise."""
    requests: list[dict[str, Any]] = []
    queue = list(replies)

    def create(**kwargs: Any) -> Any:
        requests.append(kwargs)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(
            model="served",
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2, total_tokens=7),
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=reply))],
        )

    class FakeGroq:
        def __init__(self, api_key: str) -> None:
            assert api_key == "test-key"
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    monkeypatch.setattr(groq_adapter, "Groq", FakeGroq)
    monkeypatch.setattr(groq_adapter.time, "sleep", lambda _s: None)
    return requests


def _choose(settings=None, *, allowed=ALLOWED, counts=COUNTS, loop: int = 1):
    return groq_adapter.choose_fix_strategy(
        loop=loop,
        allowed=allowed,
        violation_counts=counts,
        settings=settings or _settings(),
    )


@pytest.mark.parametrize(
    ("extra", "reason"),
    [
        ({"llm_enabled": False}, "llm_disabled"),
        ({"llm_provider": "anthropic"}, "provider_not_groq"),
        ({"llm_model": ""}, "model_not_configured"),
        ({"groq_api_key": SecretStr("")}, "api_key_missing"),
    ],
)
def test_gate_returns_fallback_without_a_client(monkeypatch, extra, reason) -> None:
    class Forbidden:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            raise AssertionError("client must not be constructed")

    monkeypatch.setattr(groq_adapter, "Groq", Forbidden)
    monkeypatch.setattr(groq_adapter.time, "sleep", lambda _s: pytest.fail("no sleep"))

    result = _choose(_settings(**extra))

    assert result.strategy is None and result.is_fallback is True
    assert result.model_metadata["fallback_reason"] == reason
    assert result.model_metadata["llm_called"] is False


def test_valid_reply_returns_strategy(monkeypatch) -> None:
    requests = _install(monkeypatch, ['{"strategy": "rematch"}'])

    result = _choose()

    assert result.strategy == "rematch" and result.is_fallback is False
    assert result.model_metadata["llm_called"] is True
    assert result.model_metadata["repair_attempted"] is False
    assert result.model_metadata["prompt_version"] == "fix_strategy_v1"
    assert len(requests) == 1


def test_request_uses_strict_json_schema_enum_and_control_caps(monkeypatch) -> None:
    requests = _install(monkeypatch, ['{"strategy": "split"}'])
    settings = _settings()

    _choose(settings, allowed=("rematch", "split"))

    request = requests[0]
    schema = request["response_format"]
    assert schema["type"] == "json_schema"
    assert schema["json_schema"]["strict"] is True
    body = schema["json_schema"]["schema"]
    assert body["properties"]["strategy"]["enum"] == ["rematch", "split"]
    assert body["required"] == ["strategy"] and body["additionalProperties"] is False
    assert request["temperature"] == settings.llm_control_temperature <= 0.2
    assert request["max_completion_tokens"] == settings.llm_control_max_tokens
    assert request["timeout"] == settings.llm_request_timeout_s
    assert "stream" not in request and "tools" not in request
    assert request["reasoning_effort"] == "low" and request["include_reasoning"] is False


def test_payload_is_loop_allowed_and_code_counts_only(monkeypatch) -> None:
    requests = _install(monkeypatch, ['{"strategy": "next_path"}'])

    _choose(loop=2)

    payload = json.loads(requests[0]["messages"][1]["content"])
    assert payload == {"loop": 2, "allowed": list(ALLOWED), "violations": COUNTS}
    assert "strategy" in requests[0]["messages"][0]["content"]


def test_invalid_json_then_valid_makes_exactly_one_repair_call(monkeypatch) -> None:
    requests = _install(monkeypatch, ["not json", '{"strategy": "split"}'])

    result = _choose()

    assert result.strategy == "split" and result.is_fallback is False
    assert len(requests) == 2
    assert result.model_metadata["repair_attempted"] is True
    repair_messages = requests[1]["messages"]
    assert repair_messages[-2] == {"role": "assistant", "content": "not json"}
    assert repair_messages[-1]["role"] == "user"


def test_two_invalid_replies_fall_back_as_invalid_output(monkeypatch) -> None:
    requests = _install(monkeypatch, ["nope", '{"strategy": 5}'])

    result = _choose()

    assert result.strategy is None and result.is_fallback is True
    assert result.model_metadata["fallback_reason"] == "invalid_output"
    assert result.model_metadata["repair_attempted"] is True
    assert len(requests) == 2


def test_out_of_menu_value_is_rejected_without_repair(monkeypatch) -> None:
    requests = _install(monkeypatch, ['{"strategy": "mark_unassigned"}'])

    result = _choose()

    assert result.strategy is None
    assert result.model_metadata["fallback_reason"] == "out_of_menu"
    assert len(requests) == 1


def test_known_strategy_outside_the_allowed_subset_is_out_of_menu(monkeypatch) -> None:
    _install(monkeypatch, ['{"strategy": "next_path"}'])

    result = _choose(allowed=("rematch", "split"))

    assert result.strategy is None
    assert result.model_metadata["fallback_reason"] == "out_of_menu"


def test_client_exception_falls_back_with_error_name(monkeypatch) -> None:
    _install(monkeypatch, [TimeoutError("slow")])

    result = _choose()

    assert result.strategy is None and result.is_fallback is True
    assert result.model_metadata["fallback_reason"] == "error:TimeoutError"
    assert "test-key" not in json.dumps(result.model_metadata)


def test_ids_or_names_in_violation_keys_are_rejected_before_any_call(monkeypatch) -> None:
    requests = _install(monkeypatch, ['{"strategy": "split"}'])

    for bad in (f"V4:{UUID}", "V5:Gudalur School", "shelter-1", "V9:group_unassigned"):
        with pytest.raises(ValueError, match="violation"):
            _choose(counts={bad: 1})
    assert requests == []


def test_strategy_outside_global_menu_is_rejected_as_input(monkeypatch) -> None:
    _install(monkeypatch, [])

    with pytest.raises(ValueError, match="allowed"):
        _choose(allowed=("next_path", "mark_unassigned"))
    assert _choose(allowed=()).model_metadata["fallback_reason"] == "empty_menu"

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from groq import Groq
from groq.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam
from wildfire_core.config import Settings
from wildfire_core.schemas.phase2 import FireSpreadResult, RouteResult, WeatherSnapshot


@dataclass(frozen=True)
class RationaleResult:
    text: str
    is_fallback: bool
    model_metadata: dict[str, Any]


def base_model_metadata(settings: Settings) -> dict[str, Any]:
    """Non-secret model configuration recorded on the generate_rationale audit row."""
    return {
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "llm_enabled": settings.llm_enabled,
        "max_completion_tokens": settings.llm_rationale_max_tokens,
        "timeout_s": settings.llm_request_timeout_s,
    }


def _metadata(
    settings: Settings,
    *,
    llm_called: bool,
    is_fallback: bool,
    fallback_reason: str | None,
    finish_reason: str | None = None,
    usage: dict[str, int | None] | None = None,
    response_model: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    return {
        **base_model_metadata(settings),
        "llm_called": llm_called,
        "is_fallback": is_fallback,
        "fallback_reason": fallback_reason,
        "finish_reason": finish_reason,
        "usage": usage,
        "response_model": response_model,
        "reasoning_effort": reasoning_effort,
    }


def generate_rationale(
    fire_results: Sequence[FireSpreadResult],
    weather: WeatherSnapshot,
    routes: Sequence[RouteResult],
    settings: Settings,
) -> RationaleResult:
    user_payload = json.dumps(
        {
            "fire_results": [result.model_dump(mode="json") for result in fire_results],
            "weather": weather.model_dump(mode="json"),
            "routes": [route.model_dump(mode="json") for route in routes],
        },
        indent=2,
        sort_keys=True,
    )
    messages: list[ChatCompletionSystemMessageParam | ChatCompletionUserMessageParam] = [
        {
            "role": "system",
            "content": (
                "Write a concise rationale grounded only in the supplied fire, weather, and route "
                "data. Do not invent entities, locations, measurements, or recommendations. "
                "Numeric and safety decisions are deterministic; state uncertainty and require "
                "human review."
            ),
        },
        {"role": "user", "content": user_payload},
    ]

    def fallback(
        reason: str, detail: str, *, llm_called: bool, effort: str | None = None
    ) -> RationaleResult:
        total_area = sum(result.affected_area_km2 for result in fire_results)
        text = (
            f"[DETERMINISTIC FALLBACK] Fire spread CA: {total_area:g} km2 across "
            f"{len(fire_results)} cluster(s). Routes: {len(routes)}. Human review required. "
            f"({detail})"
        )
        return RationaleResult(
            text=text,
            is_fallback=True,
            model_metadata=_metadata(
                settings,
                llm_called=llm_called,
                is_fallback=True,
                fallback_reason=reason,
                reasoning_effort=effort,
            ),
        )

    # HI-05: never construct a client or sleep unless the operator enabled Groq.
    api_key = settings.groq_api_key.get_secret_value().strip()
    gate: str | None = None
    if not settings.llm_enabled:
        gate = "llm_disabled"
    elif settings.llm_provider != "groq":
        gate = "provider_not_groq"
    elif not settings.llm_model.strip():
        gate = "model_not_configured"
    elif not api_key:
        gate = "api_key_missing"
    if gate is not None:
        return fallback(gate, f"LLM unavailable: {gate}", llm_called=False)

    request_kwargs: dict[str, Any] = {}
    reasoning_effort: str | None = None
    if settings.llm_model.startswith("openai/gpt-oss"):
        # Keep reasoning tokens out of message.content and inside the D-09 cap.
        reasoning_effort = "low"
        request_kwargs = {"reasoning_effort": reasoning_effort, "include_reasoning": False}

    try:
        time.sleep(1)
        response = Groq(api_key=api_key).chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            max_completion_tokens=settings.llm_rationale_max_tokens,
            timeout=settings.llm_request_timeout_s,
            **request_kwargs,
        )
        choice = response.choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        raw_usage = getattr(response, "usage", None)
        usage: dict[str, int | None] | None = (
            {
                "prompt_tokens": getattr(raw_usage, "prompt_tokens", None),
                "completion_tokens": getattr(raw_usage, "completion_tokens", None),
                "total_tokens": getattr(raw_usage, "total_tokens", None),
            }
            if raw_usage is not None
            else None
        )
        content = choice.message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Groq returned an empty rationale")
        return RationaleResult(
            text=content.strip(),
            is_fallback=False,
            model_metadata=_metadata(
                settings,
                llm_called=True,
                is_fallback=False,
                fallback_reason=None,
                finish_reason=finish_reason,
                usage=usage,
                response_model=getattr(response, "model", None),
                reasoning_effort=reasoning_effort,
            ),
        )
    except Exception as error:
        name = type(error).__name__
        return fallback(
            f"error:{name}", f"LLM error: {name}", llm_called=True, effort=reasoning_effort
        )

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
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


# Polygon WKT and per-node route paths are large geometry, not rationale grounding: sending them
# made the prompt ~16k tokens and exceeded Groq's on-demand TPM limit (413). The deterministic
# metrics below are what the rationale may cite.
_FIRE_GEOMETRY_FIELDS = {
    "current_perimeter_wkt",
    "p50_1h_wkt",
    "p50_3h_wkt",
    "p50_6h_wkt",
    "p90_1h_wkt",
    "p90_3h_wkt",
    "p90_6h_wkt",
}


def _route_summary(route: RouteResult) -> dict[str, Any]:
    summary = route.model_dump(mode="json", exclude={"osm_node_path", "fire_penalty_edges"})
    summary["path_node_count"] = len(route.osm_node_path)
    summary["fire_penalty_edge_count"] = len(route.fire_penalty_edges)
    return summary


def generate_rationale(
    fire_results: Sequence[FireSpreadResult],
    weather: WeatherSnapshot,
    routes: Sequence[RouteResult],
    settings: Settings,
) -> RationaleResult:
    user_payload = json.dumps(
        {
            "fire_results": [
                result.model_dump(mode="json", exclude=_FIRE_GEOMETRY_FIELDS)
                for result in fire_results
            ],
            "weather": weather.model_dump(mode="json"),
            "routes": [_route_summary(route) for route in routes],
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


def _load_prompt(name: str) -> tuple[str, str]:
    """Read a versioned prompt from ``apps/coordinator/prompts``; the version is the file stem."""
    path = Path(__file__).resolve().parents[3] / "prompts" / f"{name}.md"
    return path.read_text(encoding="utf-8").strip(), name


def _gate(settings: Settings) -> str | None:
    """HI-05: no client is constructed unless the operator enabled Groq."""
    if not settings.llm_enabled:
        return "llm_disabled"
    if settings.llm_provider != "groq":
        return "provider_not_groq"
    if not settings.llm_model.strip():
        return "model_not_configured"
    if not settings.groq_api_key.get_secret_value().strip():
        return "api_key_missing"
    return None


def _reasoning_kwargs(settings: Settings) -> tuple[dict[str, Any], str | None]:
    if settings.llm_model.startswith("openai/gpt-oss"):
        # Keep reasoning tokens out of message.content and inside the token cap.
        return {"reasoning_effort": "low", "include_reasoning": False}, "low"
    return {}, None


def _usage(response: Any) -> dict[str, int | None] | None:
    raw = getattr(response, "usage", None)
    if raw is None:
        return None
    return {
        "prompt_tokens": getattr(raw, "prompt_tokens", None),
        "completion_tokens": getattr(raw, "completion_tokens", None),
        "total_tokens": getattr(raw, "total_tokens", None),
    }


def generate_plan_rationale(plan_summary: Mapping[str, Any], settings: Settings) -> RationaleResult:
    """Rationale for an ``IntegratedPlan`` from a compact settlement-level summary (no geometry)."""
    prompt_version = "plan_rationale_v1"
    effort: str | None = None

    def meta(
        *, llm_called: bool, is_fallback: bool, reason: str | None, **extra: Any
    ) -> dict[str, Any]:
        return {
            **_metadata(
                settings,
                llm_called=llm_called,
                is_fallback=is_fallback,
                fallback_reason=reason,
                reasoning_effort=effort,
                **extra,
            ),
            "prompt_version": prompt_version,
        }

    def fallback(reason: str, *, llm_called: bool) -> RationaleResult:
        text = (
            f"[DETERMINISTIC FALLBACK] LLM rationale unavailable ({reason}). Human review required."
        )
        return RationaleResult(
            text=text,
            is_fallback=True,
            model_metadata=meta(llm_called=llm_called, is_fallback=True, reason=reason),
        )

    gate = _gate(settings)
    if gate is not None:
        return fallback(gate, llm_called=False)

    request_kwargs, effort = _reasoning_kwargs(settings)
    try:
        system_prompt, prompt_version = _load_prompt("plan_rationale_v1")
        messages: list[ChatCompletionSystemMessageParam | ChatCompletionUserMessageParam] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(plan_summary, sort_keys=True, separators=(",", ":")),
            },
        ]
        time.sleep(1)
        api_key = settings.groq_api_key.get_secret_value().strip()
        response = Groq(api_key=api_key).chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            max_completion_tokens=settings.llm_rationale_max_tokens,
            timeout=settings.llm_request_timeout_s,
            **request_kwargs,
        )
        choice = response.choices[0]
        content = choice.message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Groq returned an empty rationale")
        return RationaleResult(
            text=content.strip(),
            is_fallback=False,
            model_metadata=meta(
                llm_called=True,
                is_fallback=False,
                reason=None,
                finish_reason=getattr(choice, "finish_reason", None),
                usage=_usage(response),
                response_model=getattr(response, "model", None),
            ),
        )
    except Exception as error:
        return fallback(f"error:{type(error).__name__}", llm_called=True)

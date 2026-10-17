from __future__ import annotations

import json
import time
from collections.abc import Sequence

from groq import Groq
from groq.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam
from wildfire_core.config import Settings
from wildfire_core.schemas.phase2 import FireSpreadResult, RouteResult, WeatherSnapshot


def generate_rationale(
    fire_result: FireSpreadResult,
    weather: WeatherSnapshot,
    routes: Sequence[RouteResult],
    settings: Settings,
) -> tuple[str, bool]:
    user_payload = json.dumps(
        {
            "fire_result": fire_result.model_dump(mode="json"),
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

    try:
        time.sleep(1)
        response = Groq(api_key=settings.groq_api_key.get_secret_value()).chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            max_tokens=settings.llm_rationale_max_tokens,
            timeout=settings.llm_request_timeout_s,
        )
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Groq returned an empty rationale")
        return content.strip(), False
    except Exception as error:
        fallback = (
            f"[DETERMINISTIC FALLBACK] Fire spread CA: {fire_result.affected_area_km2:g} km2. "
            f"Routes: {len(routes)}. Human review required. (LLM error: {type(error).__name__})"
        )
        return fallback, True

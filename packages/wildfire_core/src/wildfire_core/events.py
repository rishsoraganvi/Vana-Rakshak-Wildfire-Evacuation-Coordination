from __future__ import annotations

import json
from typing import Any

from redis import Redis


class RedisEvents:
    def __init__(self, client: Redis) -> None:
        self._client = client

    def ping(self) -> bool:
        return bool(self._client.ping())

    def publish(self, channel: str, event: dict[str, Any]) -> int:
        return int(self._client.publish(channel, json.dumps(event)))

from __future__ import annotations

import os
import subprocess
import sys

import httpx
import pytest
from dotenv import load_dotenv

load_dotenv()

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(os.getenv("COMPOSE_SMOKE") != "1", reason="requires running Compose stack"),
]


@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="requires GROQ_API_KEY")
def test_replay_demo_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/replay_demo.py"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"


def test_api_incidents_endpoint_is_available_on_local_host() -> None:
    port = os.getenv("API_GATEWAY_PORT", "8000")
    response = httpx.get(f"http://127.0.0.1:{port}/api/v1/incidents", timeout=5)

    assert response.status_code == 200
    assert isinstance(response.json(), list)
"""Parallel specialist dispatch: concurrency, timeouts and the ToolResult error envelope."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from coordinator.dispatch import run_specialists


def _sleeper(seconds: float, value: Any = "ok"):
    def call() -> Any:
        time.sleep(seconds)
        return value

    return call


def test_three_specialists_run_concurrently() -> None:
    calls = {name: _sleeper(0.2, name) for name in ("c", "a", "b")}

    started = time.monotonic()
    results = run_specialists(calls, timeout_s=5.0)
    elapsed = time.monotonic() - started

    assert elapsed < 0.5  # sequential execution would take 0.6 s
    assert list(results) == ["a", "b", "c"]
    assert all(result.ok for result in results.values())
    assert {name: result.data for name, result in results.items()} == {
        "a": "a",
        "b": "b",
        "c": "c",
    }
    assert all(result.latency_ms >= 0 and result.tool == name for name, result in results.items())


def test_timeout_is_an_envelope_and_does_not_hold_up_the_others() -> None:
    calls = {"slow": _sleeper(1.5), "fast": _sleeper(0.0, "done")}

    started = time.monotonic()
    results = run_specialists(calls, timeout_s=0.2)
    elapsed = time.monotonic() - started

    assert results["fast"].ok is True and results["fast"].data == "done"
    slow = results["slow"]
    assert slow.ok is False
    assert slow.error is not None
    assert slow.error.code == "timeout" and slow.error.retryable is True
    assert elapsed < 1.0  # the coordinator does not wait for the straggler thread


def test_exception_is_surfaced_not_swallowed() -> None:
    def broken() -> None:
        raise ValueError("bad shelter row")

    results = run_specialists({"shelter": broken, "ok": _sleeper(0.0)}, timeout_s=2.0)

    failed = results["shelter"]
    assert failed.ok is False and failed.error is not None
    assert failed.error.code == "exception:ValueError"
    assert failed.error.retryable is False
    assert "bad shelter row" in failed.error.message
    assert results["ok"].ok is True


def test_works_from_inside_a_running_event_loop() -> None:
    async def caller() -> dict[str, Any]:
        return run_specialists({"a": _sleeper(0.0, 1), "b": _sleeper(0.0, 2)}, timeout_s=2.0)

    results = asyncio.run(caller())

    assert {name: result.data for name, result in results.items()} == {"a": 1, "b": 2}


def test_long_error_messages_are_truncated() -> None:
    def broken() -> None:
        raise RuntimeError("x" * 1000)

    result = run_specialists({"t": broken}, timeout_s=2.0)["t"]

    assert result.error is not None and len(result.error.message) == 200

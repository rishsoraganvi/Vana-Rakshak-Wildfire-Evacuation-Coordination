"""Parallel specialist dispatch (PLAN-01, TechSpec 6.2, RESEARCH Pattern 6).

``run_specialists`` runs the specialists concurrently inside ONE coordinator node: each callable
goes through ``asyncio.to_thread`` under ``asyncio.wait_for`` and the results are gathered. Every
outcome becomes a ``ToolResult`` envelope (Rules 2.5); nothing is swallowed.

Timeouts: ``wait_for`` cancels the wait, not the worker thread, so a timed-out specialist keeps
running in the background until it returns. Specialists must therefore be side-effect-free reads
(Rules 2.8: a timeout on every call). The event loop is closed without waiting for such
stragglers, so a hung specialist cannot hold the coordinator past ``timeout_s``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

from wildfire_core.schemas.tools import ToolError, ToolResult

T = TypeVar("T")


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


async def _call(name: str, fn: Callable[[], Any], timeout_s: float) -> ToolResult:
    started = time.monotonic()
    try:
        value = await asyncio.wait_for(asyncio.to_thread(fn), timeout_s)
    except TimeoutError:
        return ToolResult(
            tool=name,
            ok=False,
            error=ToolError(
                code="timeout",
                message=f"{name} did not finish within {timeout_s:g} s",
                retryable=True,
            ),
            latency_ms=_elapsed_ms(started),
        )
    except Exception as exc:
        return ToolResult(
            tool=name,
            ok=False,
            error=ToolError(
                code=f"exception:{type(exc).__name__}",
                message=str(exc)[:200],
                retryable=False,
            ),
            latency_ms=_elapsed_ms(started),
        )
    return ToolResult(tool=name, ok=True, data=value, latency_ms=_elapsed_ms(started))


async def _gather(
    calls: Mapping[str, Callable[[], Any]], timeout_s: float
) -> dict[str, ToolResult]:
    names = sorted(calls)
    outcomes = await asyncio.gather(
        *(_call(name, calls[name], timeout_s) for name in names), return_exceptions=True
    )
    results: dict[str, ToolResult] = {}
    for name, outcome in zip(names, outcomes, strict=True):
        if isinstance(outcome, ToolResult):
            results[name] = outcome
        else:  # BaseException such as CancelledError: still an envelope, never lost
            results[name] = ToolResult(
                tool=name,
                ok=False,
                error=ToolError(
                    code=f"exception:{type(outcome).__name__}",
                    message=str(outcome)[:200],
                    retryable=False,
                ),
                latency_ms=0,
            )
    return results


def _run(coro: Coroutine[Any, Any, T]) -> T:
    """Run ``coro`` on a private loop that is closed without waiting for worker threads.

    ``asyncio.run`` would wait for a timed-out specialist's thread when it shuts the default
    executor down; closing the loop directly shuts it down with ``wait=False``.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def run_specialists(
    calls: Mapping[str, Callable[[], Any]], *, timeout_s: float
) -> dict[str, ToolResult]:
    """Run every callable concurrently; return one ``ToolResult`` per name, sorted by name.

    Safe to call from sync code and from inside a running event loop (an async caller): in that
    case the work runs on a private loop in a one-worker thread.
    """
    coro = _gather(calls, timeout_s)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_run, coro).result()

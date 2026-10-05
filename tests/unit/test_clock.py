from datetime import UTC, datetime, timedelta

import pytest
from wildfire_core.clock import SimClock


def test_sim_clock_is_injected_and_advances() -> None:
    clock = SimClock(datetime(2026, 1, 1, tzinfo=UTC))
    assert clock.now_utc().isoformat() == "2026-01-01T00:00:00+00:00"
    clock.advance(timedelta(hours=2))
    assert clock.now_utc().hour == 2


def test_sim_clock_rejects_naive_time() -> None:
    with pytest.raises(ValueError):
        SimClock(datetime(2026, 1, 1))

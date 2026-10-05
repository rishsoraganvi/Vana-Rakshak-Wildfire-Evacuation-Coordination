from datetime import UTC, datetime, timedelta

from wildfire_core.state import classify_freshness


def test_freshness_boundaries_are_explicit() -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert classify_freshness(now - timedelta(minutes=4), now, 300).status == "fresh"
    assert classify_freshness(now - timedelta(minutes=6), now, 300).status == "stale"
    assert classify_freshness(None, now, 300).status == "unavailable"

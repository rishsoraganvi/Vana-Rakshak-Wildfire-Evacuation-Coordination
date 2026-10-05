from datetime import UTC, datetime
from pathlib import Path

from ingest_worker.firms.parser import parse_firms_csv
from wildfire_core.clock import SimClock


def test_firms_fixture_normalizes_with_raw_payload() -> None:
    payload = Path("tests/fixtures/firms/hotspot_sample.csv").read_text()
    observations = parse_firms_csv(
        payload, SimClock(datetime(2026, 1, 1, 12, tzinfo=UTC)), origin="replay"
    )
    assert len(observations) == 2
    assert observations[0].meta.origin == "replay"
    assert observations[0].meta.raw_payload is not None
    assert observations[0].dedupe_key == (
        "VIIRS_SNPP_NRT",
        datetime(2026, 1, 1, 7, 42, tzinfo=UTC),
        11.71,
        76.62,
    )

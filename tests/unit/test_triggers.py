import pytest
from ingest_worker.triggers import evaluate_new_hotspot


def test_new_hotspot_threshold_crossing_is_explicit() -> None:
    assert evaluate_new_hotspot(3, 3).crossed
    assert not evaluate_new_hotspot(2, 3).crossed


def test_threshold_must_be_positive() -> None:
    with pytest.raises(ValueError):
        evaluate_new_hotspot(1, 0)

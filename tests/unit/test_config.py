from __future__ import annotations

from wildfire_core.config import BBox


def test_bbox_defaults_are_ordered() -> None:
    bbox = BBox.from_value("76.0,11.5,77.3,12.4")
    assert bbox.model_dump() == {"west": 76.0, "south": 11.5, "east": 77.3, "north": 12.4}


def test_bbox_rejects_reversed_bounds() -> None:
    try:
        BBox.from_value("77.3,11.5,76.0,12.4")
    except ValueError as error:
        assert "ordered" in str(error)
    else:
        raise AssertionError("reversed bbox was accepted")

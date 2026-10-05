import pytest
from pydantic import ValidationError
from wildfire_core.geo.bbox import BBox


def test_bbox_parses_and_contains_lon_lat() -> None:
    bbox = BBox.from_value("76.0,11.5,77.3,12.4")
    assert bbox.contains(76.5, 12.0)
    assert not bbox.contains(75.9, 12.0)


def test_bbox_rejects_reversed_bounds() -> None:
    with pytest.raises(ValidationError):
        BBox.from_value("77.3,11.5,76.0,12.4")

"""Shared nearest-horizon rule used by routing and validator V3 (D-07, D-21)."""

from __future__ import annotations

import math
from typing import Literal

HORIZONS_H: tuple[int, int, int] = (1, 3, 6)


def nearest_horizon_h(arrival_min: float) -> Literal[1, 3, 6]:
    """Map an arrival time in minutes to the nearest forecast horizon (1, 3 or 6 hours).

    Distance is measured to 60, 180 and 360 minutes. A tie goes to the later horizon, which is
    the conservative choice (the later perimeter is larger).
    """
    if math.isnan(arrival_min) or arrival_min < 0:
        raise ValueError(f"arrival_min must be a non-negative number, got {arrival_min!r}")
    if arrival_min < 120:  # midpoint of 60 and 180; exactly 120 ties and goes later
        return 1
    if arrival_min < 270:  # midpoint of 180 and 360; exactly 270 ties and goes later
        return 3
    return 6

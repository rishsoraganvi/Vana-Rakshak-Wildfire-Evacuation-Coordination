"""Root pytest configuration: Hypothesis profiles shared by every suite."""

from __future__ import annotations

import os

from hypothesis import settings

settings.register_profile(
    "ci",
    derandomize=True,
    deadline=None,
    max_examples=200,
    print_blob=True,
)
settings.register_profile("dev", max_examples=50, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))

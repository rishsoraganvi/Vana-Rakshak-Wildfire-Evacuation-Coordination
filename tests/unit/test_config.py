from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.engine import make_url
from wildfire_core.config import BBox, load_settings


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


def test_default_settings_carry_no_database_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    settings = load_settings(Path("config/defaults.yaml"))
    assert make_url(settings.database_url.get_secret_value()).password is None
    assert settings.postgres_password.get_secret_value() == ""


def test_database_url_env_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "postgresql+psycopg://u:p@localhost:5432/db"
    monkeypatch.setenv("DATABASE_URL", url)
    settings = load_settings(Path("config/defaults.yaml"))
    assert settings.database_url.get_secret_value() == url

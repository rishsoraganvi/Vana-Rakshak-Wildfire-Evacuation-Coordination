"""Regression guard for HI-06: loopback-only ports and no default DB password."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

COMPOSE_PATH = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def _services() -> dict[str, Any]:
    loaded = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services: dict[str, Any] = loaded["services"]
    return services


def test_all_published_ports_bind_loopback() -> None:
    published = [
        (name, str(port))
        for name, service in _services().items()
        for port in service.get("ports", [])
    ]
    assert published, "expected at least one published port"
    offenders = [(name, port) for name, port in published if not port.startswith("127.0.0.1:")]
    assert offenders == []


def test_postgres_password_is_required() -> None:
    services = _services()
    assert "${POSTGRES_PASSWORD:?" in services["postgres"]["environment"]["POSTGRES_PASSWORD"]
    assert "${POSTGRES_PASSWORD:?" in services["api"]["environment"]["DATABASE_URL"]


def test_compose_has_no_default_postgres_password() -> None:
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD:-" not in text
    assert "change_me" not in text

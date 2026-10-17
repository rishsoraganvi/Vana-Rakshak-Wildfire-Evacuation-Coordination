from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "infra" / "migrations" / "versions" / "0006_phase3_planning.py"

ADD_VALUE = "ALTER TYPE plan_status ADD VALUE IF NOT EXISTS 'failed'"


class _RecorderOp:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str) -> None:
        self.statements.append(str(sql))


@pytest.fixture
def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0006", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(module: ModuleType, monkeypatch: pytest.MonkeyPatch, name: str) -> list[str]:
    recorder = _RecorderOp()
    monkeypatch.setattr(module, "op", recorder)
    getattr(module, name)()
    return recorder.statements


def test_revision_chain(migration: ModuleType) -> None:
    assert migration.revision == "0006_phase3_planning"
    assert migration.down_revision == "0005_phase2_plan_versions"


def test_add_value_runs_first_and_failed_is_never_reused(
    migration: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    statements = _run(migration, monkeypatch, "upgrade")
    assert statements[0].strip() == ADD_VALUE
    for later in statements[1:]:
        assert "'failed'" not in later


def test_upgrade_creates_phase3_schema(
    migration: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    sql = "\n".join(_run(migration, monkeypatch, "upgrade"))
    for needle in (
        "CREATE TABLE shelters",
        "CREATE TABLE shelter_occupancy",
        "CREATE TABLE road_edge_status",
        "ADD COLUMN parent_plan_id",
        "uq_settlements_external_ref",
        "plan_versions_immutable",
        "BEFORE UPDATE ON plan_versions",
        "ix_plan_versions_trigger_id",
        "ix_plan_versions_parent_plan_id",
        "ix_plan_versions_incident_status",
        "USING gist (geom)",
        "ck_shelters_occupancy_le_capacity",
        "uq_shelters_external_ref",
    ):
        assert needle in sql, needle


def test_immutability_function_guards_every_plan_column(
    migration: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    sql = "\n".join(_run(migration, monkeypatch, "upgrade"))
    function = sql.split("CREATE FUNCTION plan_versions_immutable", 1)[1]
    function = function.split("CREATE TRIGGER", 1)[0]
    assert "plan_versions rows are immutable except status" in function
    for column in (
        "id", "incident_id", "version", "rationale_md", "is_llm_fallback", "is_simulated",
        "warnings", "plan_data", "created_at", "parent_plan_id", "trigger_id", "state_version",
        "plan_schema_version", "validation", "freshness", "provenance", "diff",
        "used_fallback", "valid_until",
    ):  # fmt: skip
        assert f"NEW.{column}," in function or f"NEW.{column}\n" in function, column
        assert f"OLD.{column}," in function or f"OLD.{column}\n" in function, column
    assert "NEW.status" not in function


def test_downgrade_reverses_without_dropping_enum_value(
    migration: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    sql = "\n".join(_run(migration, monkeypatch, "downgrade"))
    assert "DROP TABLE IF EXISTS shelters" in sql
    assert "DROP TRIGGER IF EXISTS trg_plan_versions_immutable" in sql
    assert "DROP TABLE IF EXISTS road_edge_status" in sql
    assert "DROP TYPE" not in sql

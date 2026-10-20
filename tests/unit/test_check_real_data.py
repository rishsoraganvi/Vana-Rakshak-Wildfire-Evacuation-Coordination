from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SHELTERS_CSV = ROOT / "config" / "seed" / "shelters_bandipur.csv"
SETTLEMENTS_CSV = ROOT / "config" / "seed" / "settlements_bandipur.csv"
STUB_GRAPH = ROOT / "tests" / "fixtures" / "osm" / "bandipur_stub.graphml"
SHELTER_HEADER = (
    "external_ref,name,kind,lat,lon,capacity,usable_factor,capacity_source,is_simulated,notes\n"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_real_data", ROOT / "scripts" / "check_real_data.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_graph_and_synthetic_seed(tmp_path: Path) -> None:
    probe = _load_script()
    report = probe.check_real_data(tmp_path / "absent.graphml", SHELTERS_CSV, SETTLEMENTS_CSV)
    assert report["graph"]["status"] == "missing"
    assert "build_osm_graph.py" in report["graph"]["build_command"]
    assert report["shelters"]["status"] == "synthetic"
    assert report["shelters"]["total"] == 20
    assert report["settlements"]["status"] == "synthetic"
    assert report["settlements"]["by_source"] == {"synthetic": 10}
    assert probe._is_ready(report) is False


def test_stub_graph_reports_built() -> None:
    probe = _load_script()
    report = probe.check_real_data(STUB_GRAPH, SHELTERS_CSV, SETTLEMENTS_CSV)
    assert report["graph"]["status"] == "built"
    assert report["graph"]["node_count"] == 3


def test_curated_shelter_csv_is_curated(tmp_path: Path) -> None:
    probe = _load_script()
    csv_path = tmp_path / "shelters.csv"
    csv_path.write_text(
        SHELTER_HEADER + "REAL-1,Govt School,school,11.72,76.64,200,,district survey 2026,false,\n",
        encoding="utf-8",
    )
    report = probe.check_real_data(STUB_GRAPH, csv_path, SETTLEMENTS_CSV)
    assert report["shelters"]["status"] == "curated"
    assert report["shelters"]["by_source"] == {"district survey 2026": 1}


def test_mixed_shelter_csv_is_mixed(tmp_path: Path) -> None:
    probe = _load_script()
    csv_path = tmp_path / "shelters.csv"
    csv_path.write_text(
        SHELTER_HEADER
        + "REAL-1,Govt School,school,11.72,76.64,200,,district survey 2026,false,\n"
        + "SYN-1,SYN Shelter,school,11.72,76.64,100,,synthetic,true,\n",
        encoding="utf-8",
    )
    report = probe.check_real_data(STUB_GRAPH, csv_path, SETTLEMENTS_CSV)
    assert report["shelters"]["status"] == "mixed"


def test_main_exit_code_is_one_while_pending(tmp_path: Path, capsys: object) -> None:
    probe = _load_script()
    code = probe.main(["--graph", str(tmp_path / "absent.graphml")])
    assert code == 1

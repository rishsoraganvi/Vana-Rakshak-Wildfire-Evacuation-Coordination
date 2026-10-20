"""Offline readiness probe for the real OSM graph and the curated seed (D-05, D-18, D-19).

Never touches the network: it only loads the saved graph file and reads the seed CSVs. Run it from
the repository root:

    uv run python scripts/check_real_data.py

Exit codes: 0 everything is ready (graph built, both seeds curated), 1 something is still pending.
Pending is not an error, so CI must never use this as a gate.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# Reuse pytest's source paths so the script runs outside pytest too.
_PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
for _src in _PYPROJECT["tool"]["pytest"]["ini_options"]["pythonpath"]:
    sys.path.insert(0, str(ROOT / _src))

from agent_routing.graph import BUILD_COMMAND, GraphNotBuiltError, load_graph  # noqa: E402
from wildfire_core.config import load_settings  # noqa: E402
from wildfire_core.seed import (  # noqa: E402
    SYNTHETIC,
    load_settlement_rows,
    load_shelter_rows,
)


def _graph_status(graph_path: Path) -> dict[str, Any]:
    try:
        graph = load_graph(graph_path)
    except GraphNotBuiltError:
        return {"status": "missing", "path": str(graph_path), "build_command": BUILD_COMMAND}
    modified = datetime.fromtimestamp(Path(graph_path).stat().st_mtime, tz=UTC).isoformat()
    return {
        "status": "built",
        "path": str(graph_path),
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "mtime": modified,
    }


def _provenance(sources: list[str]) -> dict[str, Any]:
    by_source = dict(Counter(sources))
    synthetic = by_source.get(SYNTHETIC, 0)
    if sources and synthetic == len(sources):
        status = "synthetic"
    elif synthetic == 0:
        status = "curated"
    else:
        status = "mixed"
    return {"total": len(sources), "by_source": by_source, "status": status}


def check_real_data(graph_path: Path, shelters_csv: Path, settlements_csv: Path) -> dict[str, Any]:
    """Report graph and seed readiness without network access."""
    shelters = load_shelter_rows(shelters_csv)
    settlements = load_settlement_rows(settlements_csv)
    return {
        "graph": _graph_status(graph_path),
        "shelters": _provenance([row.capacity_source for row in shelters]),
        "settlements": _provenance([row.pop_source for row in settlements]),
    }


def _is_ready(report: dict[str, Any]) -> bool:
    return bool(
        report["graph"]["status"] == "built"
        and report["shelters"]["status"] == "curated"
        and report["settlements"]["status"] == "curated"
    )


def _print_report(report: dict[str, Any]) -> None:
    graph = report["graph"]
    if graph["status"] == "built":
        print(
            f"OSM graph: built ({graph['node_count']} nodes, {graph['edge_count']} edges, "
            f"modified {graph['mtime']})"
        )
    else:
        print(
            f"OSM graph: missing at {graph['path']}. Build it once with: {graph['build_command']}"
        )
    for key, label in (("shelters", "Shelters"), ("settlements", "Settlements")):
        item = report[key]
        print(f"{label}: {item['status']} ({item['total']} rows, sources {item['by_source']})")
    print(
        "Ready." if _is_ready(report) else "Pending: real-data steps remain (see docs/datasets.md)."
    )


def main(argv: list[str] | None = None) -> int:
    settings = load_settings(ROOT / "config" / "defaults.yaml")

    def _absolute(path: Path) -> Path:
        return path if path.is_absolute() else ROOT / path

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--graph", type=Path, default=_absolute(settings.osm_cache_path))
    parser.add_argument("--shelters", type=Path, default=_absolute(settings.shelters_seed_path))
    parser.add_argument(
        "--settlements", type=Path, default=_absolute(settings.settlements_seed_path)
    )
    args = parser.parse_args(argv)

    report = check_real_data(args.graph, args.shelters, args.settlements)
    _print_report(report)
    print(json.dumps(report, indent=2, default=str))
    return 0 if _is_ready(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Build the pilot OSM drive graph once, by hand (D-05, D-06, D-19).

This is the ONLY place the road network is downloaded. Plan-time code loads the saved file and
never touches the network. Run it from the repository root:

    uv run python scripts/build_osm_graph.py            # download and save (needs network)
    uv run python scripts/build_osm_graph.py --check    # load-only: counts and file age
    uv run python scripts/build_osm_graph.py --dry-run  # print the plan, do nothing

Exit codes: 0 success, 1 graph missing (--check), 2 network or Overpass failure.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Reuse pytest's source paths so the script runs outside pytest too.
_PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
for _src in _PYPROJECT["tool"]["pytest"]["ini_options"]["pythonpath"]:
    sys.path.insert(0, str(ROOT / _src))

from agent_routing.graph import (  # noqa: E402
    GraphNotBuiltError,
    build_graph_for_area,
    load_graph,
)
from wildfire_core.config import load_settings  # noqa: E402

ATTRIBUTION = "Map data © OpenStreetMap contributors (ODbL)"
OSM_CACHE_FOLDER = ROOT / "data" / "osm" / "cache"


def _parse_args(argv: list[str] | None, defaults: dict[str, float | Path]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--center-lat", type=float, default=defaults["lat"])
    parser.add_argument("--center-lon", type=float, default=defaults["lon"])
    parser.add_argument("--buffer-m", type=float, default=defaults["buffer_m"])
    parser.add_argument("--out", type=Path, default=defaults["out"])
    parser.add_argument(
        "--check", action="store_true", help="load-only: print node and edge counts, no network"
    )
    parser.add_argument("--dry-run", action="store_true", help="print what would be built and exit")
    return parser.parse_args(argv)


def _describe(graph: object) -> str:
    return f"nodes={graph.number_of_nodes()} edges={graph.number_of_edges()}"  # type: ignore[attr-defined]


def main(argv: list[str] | None = None) -> int:
    settings = load_settings(ROOT / "config" / "defaults.yaml")
    default_out = settings.osm_cache_path
    if not default_out.is_absolute():
        default_out = ROOT / default_out
    args = _parse_args(
        argv,
        {
            "lat": settings.pilot_center_lat,
            "lon": settings.pilot_center_lon,
            "buffer_m": settings.pilot_buffer_m,
            "out": default_out,
        },
    )
    print(ATTRIBUTION)

    if args.check:
        try:
            graph = load_graph(args.out)
        except GraphNotBuiltError as error:
            print(str(error), file=sys.stderr)
            return 1
        modified = datetime.fromtimestamp(args.out.stat().st_mtime, tz=UTC).isoformat()
        print(f"{args.out}: {_describe(graph)} modified={modified}")
        return 0

    buffer_m = int(args.buffer_m) if float(args.buffer_m).is_integer() else args.buffer_m
    plan = f"center=({args.center_lat}, {args.center_lon}) buffer_m={buffer_m} out={args.out}"
    if args.dry_run:
        print(f"dry-run, nothing downloaded: {plan}")
        return 0

    print(f"Building drive graph: {plan}")
    try:
        graph = build_graph_for_area(
            args.center_lat,
            args.center_lon,
            buffer_m,
            args.out,
            cache_folder=OSM_CACHE_FOLDER,
        )
    except Exception as error:  # CLI boundary: report any network failure clearly
        print(
            f"OSM build failed ({type(error).__name__}): {error}. No graph file was written; "
            "check your network connection and retry.",
            file=sys.stderr,
        )
        return 2
    print(f"Saved {args.out}: {_describe(graph)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Load the labelled shelter seed CSV into the shelters table (idempotent upsert, D-18).

Occupancy is never touched: it changes only through agent_shelter.registry.update_occupancy.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

# Reuse pytest's source paths so the script runs outside pytest too.
_PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
for _src in _PYPROJECT["tool"]["pytest"]["ini_options"]["pythonpath"]:
    sys.path.insert(0, str(ROOT / _src))

from wildfire_core.config import Settings, load_settings  # noqa: E402
from wildfire_core.db.repositories import upsert_shelters  # noqa: E402
from wildfire_core.db.session import create_db_engine  # noqa: E402
from wildfire_core.seed import load_shelter_rows  # noqa: E402

SYNTHETIC_WARNING = "synthetic seed in use - replace via checkpoint in plan 03-12 (D-18)"
DEFAULT_CSV = Path("config/seed/shelters_bandipur.csv")


def _settings_or_none() -> Settings | None:
    try:
        return load_settings()
    except ValueError:  # e.g. DATABASE_URL missing; acceptable for --dry-run
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=None, help="shelter seed CSV path")
    parser.add_argument("--dry-run", action="store_true", help="validate only, no database")
    args = parser.parse_args()

    load_dotenv()
    settings = _settings_or_none()
    if settings is None and not args.dry_run:
        parser.error("settings could not be loaded (is DATABASE_URL set?)")
    csv_path = args.csv or (settings.shelters_seed_path if settings else DEFAULT_CSV)
    if not csv_path.is_absolute():
        csv_path = ROOT / csv_path

    rows = load_shelter_rows(csv_path)
    by_source = Counter(row.capacity_source for row in rows)
    synthetic = by_source.get("synthetic", 0)
    if args.dry_run:
        print(f"dry run: {len(rows)} shelters valid; by capacity_source: {dict(by_source)}")
    else:
        assert settings is not None
        engine = create_db_engine(settings.database_url.get_secret_value())
        count = upsert_shelters(engine, rows)
        print(f"seeded {count} shelters (synthetic: {synthetic})")
    if synthetic:
        print(f"WARNING: {SYNTHETIC_WARNING}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

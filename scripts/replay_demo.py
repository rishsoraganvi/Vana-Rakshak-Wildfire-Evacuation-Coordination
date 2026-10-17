from __future__ import annotations

import json
import os
import sys
import time
import tomllib
import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "osm" / "bandipur_stub.graphml"

# Reuse pytest's source paths so the script runs outside pytest too.
_PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
for _src in _PYPROJECT["tool"]["pytest"]["ini_options"]["pythonpath"]:
    sys.path.insert(0, str(ROOT / _src))


def _seed_demo(engine, now: datetime) -> tuple[str, str]:
    incident_id = uuid4()
    run_id = uuid4()
    jitter = [(-0.002, -0.001), (-0.001, 0.001), (0.0, 0.0), (0.001, -0.002), (0.002, 0.001)]
    hotspot_rows = []

    for offset, (lat_delta, lon_delta) in enumerate(jitter):
        hotspot_id = uuid4()
        latitude = 11.72 + lat_delta
        longitude = 76.64 + lon_delta
        hotspot_rows.append(
            {
                "id": hotspot_id,
                "source": "VIIRS_SNPP_NRT",
                "acq_datetime": now,
                "lat": latitude,
                "lon": longitude,
                "brightness": 330.0 + offset,
                "frp": 18.0 + offset,
                "confidence": "nominal",
                "daynight": "D",
                "scan": 0.4,
                "track": 0.4,
                "origin": "replay",
                "freshness_status": "fresh",
                "ingested_at": now,
            }
        )

    hotspot_ids = [str(row["id"]) for row in hotspot_rows]
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO incidents (id, code, status, origin, summary)
                VALUES (:id, :code, 'open', 'replay', 'Phase 2 replay demo')
                """
            ),
            {"id": incident_id, "code": f"REPLAY-{incident_id.hex[:10]}"},
        )
        for row in hotspot_rows:
            connection.execute(
                text(
                    """
                    INSERT INTO hotspots
                        (id, source, acq_datetime, lat, lon, geom, brightness, frp,
                         confidence, daynight, scan, track, origin, freshness_status, ingested_at)
                    VALUES
                        (:id, :source, :acq_datetime, :lat, :lon,
                         ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :brightness, :frp,
                         :confidence, :daynight, :scan, :track, :origin,
                         :freshness_status, :ingested_at)
                    """
                ),
                row,
            )
        connection.execute(
            text(
                """
                INSERT INTO triggers (incident_id, type, details, detected_at)
                VALUES (:incident_id, 'new_hotspot', CAST(:details AS jsonb), :detected_at)
                """
            ),
            {
                "incident_id": incident_id,
                "details": json.dumps(
                    {"count": len(hotspot_ids), "threshold": 3, "hotspot_ids": hotspot_ids}
                ),
                "detected_at": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO weather_observations
                    (provider, lat, lon, valid_time, issued_at, is_forecast, temperature_c,
                     rh_pct, wind_speed_ms, wind_dir_deg, origin, freshness_status)
                VALUES
                    ('open-meteo', 11.72, 76.64, :valid_time, :issued_at, false, 34.0,
                     30.0, 5.0, 45.0, 'replay', 'fresh')
                """
            ),
            {"valid_time": now, "issued_at": now},
        )
    return str(incident_id), str(run_id)


def _fetch_draft(engine, incident_id: str) -> dict[str, object] | None:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT id, status::text AS status, plan_data
                FROM plan_versions
                WHERE incident_id = :incident_id AND status = 'draft'
                ORDER BY version DESC
                LIMIT 1
                """
            ),
            {"incident_id": incident_id},
        ).mappings().first()
    return dict(row) if row is not None else None


def _print_summary(
    incident_id: str,
    run_id: str,
    plan: dict[str, object],
    audit_count: int,
    llm_metadata: dict[str, object],
) -> None:
    plan_data = plan["plan_data"]
    if isinstance(plan_data, str):
        plan_data = json.loads(plan_data)
    fire_result = plan_data["fire_result"]
    rationale = plan_data.get("rationale_md", "")
    routes = plan_data.get("routes", [])
    warnings = plan_data.get("warnings", [])

    print("=" * 65)
    print("  Vana-Rakshak Phase 2 - Replay Demo")
    print("=" * 65)
    print(f"  Incident ID   : {incident_id}")
    print(f"  Run ID        : {run_id}")
    print(f"  Plan ID       : {plan['id']}")
    print(f"  Status        : {plan['status']}")
    print(
        f"  Fire CA       : {fire_result['confidence']} confidence | "
        f"{fire_result['affected_area_km2']} km2 affected"
    )
    print(f"  Routes        : {len(routes)} computed")
    print(f"  LLM Model     : {llm_metadata.get('provider')}/{llm_metadata.get('model')}")
    if plan_data.get("is_llm_fallback"):
        print(f"  LLM Fallback  : Yes ({llm_metadata.get('fallback_reason')})")
    else:
        print("  LLM Fallback  : No")
    print(f"  Warnings      : {len(warnings)}")
    print(f"  Audit entries : {audit_count}")
    print("-" * 65)
    print("  Rationale (first 200 chars):")
    print(f"  {str(rationale)[:200]}")
    print("=" * 65)


def main() -> int:
    load_dotenv(ROOT / ".env")
    os.environ["OSM_CACHE_PATH"] = str(FIXTURE_PATH)
    # The demo is the Groq demo (D-08/D-15); an operator export of LLM_ENABLED=false wins.
    os.environ.setdefault("LLM_ENABLED", "true")
    os.environ.setdefault("LLM_PROVIDER", "groq")

    try:
        from coordinator.runner import run_coordinator
        from wildfire_core.config import load_settings
        from wildfire_core.db.session import create_db_engine

        settings = load_settings()
        if not settings.llm_model.strip():
            raise RuntimeError(
                "LLM model is not configured; set llm_model in config/defaults.yaml or LLM_MODEL"
            )
        if not settings.groq_api_key.get_secret_value().strip():
            raise RuntimeError(
                "GROQ_API_KEY is required; set it in .env or the process environment"
            )

        engine = create_db_engine(settings.database_url.get_secret_value())
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        incident_id, run_id = _seed_demo(engine, datetime.now(UTC))
        final_state = run_coordinator(incident_id, run_id)
        if final_state["error"] is not None:
            raise RuntimeError(final_state["error"])

        deadline = time.monotonic() + 60
        plan = None
        while time.monotonic() < deadline:
            plan = _fetch_draft(engine, incident_id)
            if plan is not None:
                break
            time.sleep(2)
        if plan is None:
            raise TimeoutError("Coordinator did not persist a draft plan within 60 seconds")

        with engine.connect() as connection:
            audit_count = connection.execute(
                text("SELECT count(*) FROM agent_runs WHERE run_id = :run_id"),
                {"run_id": run_id},
            ).scalar_one()
            metadata_row = connection.execute(
                text(
                    "SELECT model_metadata FROM agent_runs "
                    "WHERE run_id = :run_id AND node_name = 'generate_rationale'"
                ),
                {"run_id": run_id},
            ).scalar_one_or_none()
        llm_metadata = (
            json.loads(metadata_row) if isinstance(metadata_row, str) else metadata_row
        ) or {}
        _print_summary(incident_id, run_id, plan, int(audit_count), llm_metadata)
        if settings.llm_enabled and llm_metadata.get("is_fallback", True):
            print(
                f"WARNING: LLM fell back: {llm_metadata.get('fallback_reason')}",
                file=sys.stderr,
            )
        engine.dispose()
        return 0
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from agent_shelter.registry import CapacityExceeded, update_occupancy
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from wildfire_core.db.repositories import upsert_shelters
from wildfire_core.seed import ShelterSeedRow

load_dotenv()

DEFAULT_FACTOR = 0.6


@pytest.mark.compose
@pytest.mark.skipif(os.getenv("COMPOSE_SMOKE") != "1", reason="requires Compose services")
def test_update_occupancy_is_atomic_and_upsert_keeps_occupancy() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    external_ref = f"TEST-SH-{uuid4().hex[:12]}"
    row = ShelterSeedRow(
        external_ref=external_ref,
        name="TEST Shelter",
        kind="school",
        lat=11.72,
        lon=76.64,
        capacity=100,
        usable_factor=None,
        capacity_source="synthetic",
        is_simulated=True,
        notes="live test row",
    )
    shelter_id: str | None = None
    try:
        assert upsert_shelters(engine, [row]) == 1
        with engine.connect() as connection:
            shelter_id = str(
                connection.execute(
                    text("SELECT id FROM shelters WHERE external_ref = :ref"),
                    {"ref": external_ref},
                ).scalar_one()
            )

        def occupy(delta: int) -> int:
            assert shelter_id is not None
            return update_occupancy(
                engine,
                shelter_id=shelter_id,
                delta=delta,
                incident_id=None,
                default_factor=DEFAULT_FACTOR,
            )

        assert occupy(60) == 60  # usable = floor(100 x 0.6)
        with pytest.raises(CapacityExceeded):
            occupy(1)
        with pytest.raises(CapacityExceeded):
            occupy(-61)
        assert occupy(-10) == 50

        with engine.connect() as connection:
            history = connection.execute(
                text("SELECT count(*) FROM shelter_occupancy WHERE shelter_id = CAST(:id AS uuid)"),
                {"id": shelter_id},
            ).scalar_one()
        assert history == 2  # refused changes wrote no history

        assert upsert_shelters(engine, [row]) == 1  # re-seed must not reset occupancy
        with engine.connect() as connection:
            occupancy = connection.execute(
                text("SELECT occupancy FROM shelters WHERE external_ref = :ref"),
                {"ref": external_ref},
            ).scalar_one()
        assert occupancy == 50
    finally:
        with engine.begin() as connection:
            if shelter_id is not None:
                connection.execute(
                    text("DELETE FROM shelter_occupancy WHERE shelter_id = CAST(:id AS uuid)"),
                    {"id": shelter_id},
                )
            connection.execute(
                text("DELETE FROM shelters WHERE external_ref = :ref"), {"ref": external_ref}
            )

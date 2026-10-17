"""Planning coefficients taken from config and recorded in plan provenance (Rules 10)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from wildfire_core.config import Settings


class PlanningParams(BaseModel):
    """Every coefficient the planning core reads; frozen so a run cannot drift mid-plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    usable_factor: float = Field(gt=0, le=1)
    exclusion_buffer_m: int = Field(ge=0)
    p50_mult: float = Field(ge=1)
    p90_mult: float = Field(ge=1)
    k_paths: int = Field(ge=1, le=5)
    k_paths_max_leg_s: float = Field(ge=0)
    max_snap_distance_m: int = Field(ge=0)
    bpr_alpha: float = Field(ge=0)
    bpr_beta: float = Field(ge=0)
    persons_per_vehicle: float = Field(gt=0)
    evac_window_h: float = Field(gt=0)
    congestion_passes: int = Field(ge=1, le=3)
    lane_capacity_vph: dict[str, float]
    link_capacity_factor: float = Field(gt=0, le=1)
    conflict_max_loops: int = Field(ge=1, le=3)
    fix_menu_order: tuple[str, ...]

    @classmethod
    def from_settings(cls, settings: Settings) -> PlanningParams:
        return cls(
            usable_factor=settings.shelter_usable_factor,
            exclusion_buffer_m=settings.shelter_exclusion_buffer_m,
            p50_mult=settings.route_p50_mult,
            p90_mult=settings.route_p90_mult,
            k_paths=settings.k_paths,
            k_paths_max_leg_s=settings.k_paths_max_leg_s,
            max_snap_distance_m=settings.max_snap_distance_m,
            bpr_alpha=settings.bpr_alpha,
            bpr_beta=settings.bpr_beta,
            persons_per_vehicle=settings.persons_per_vehicle,
            evac_window_h=settings.evac_window_h,
            congestion_passes=settings.congestion_passes,
            lane_capacity_vph={k: float(v) for k, v in settings.lane_capacity_vph.items()},
            link_capacity_factor=settings.link_capacity_factor,
            conflict_max_loops=settings.conflict_max_loops,
            fix_menu_order=tuple(settings.fix_menu_order),
        )

    def snapshot(self) -> dict[str, float | int | str | list[str]]:
        """Flat, sorted-key view for ``PlanProvenance.params``."""
        flat: dict[str, float | int | str | list[str]] = {}
        for name, value in self.model_dump().items():
            if name == "lane_capacity_vph":
                for highway, capacity in value.items():
                    flat[f"lane_capacity_vph.{highway}"] = capacity
            elif isinstance(value, tuple):
                flat[name] = [str(item) for item in value]
            else:
                flat[name] = value
        return dict(sorted(flat.items()))

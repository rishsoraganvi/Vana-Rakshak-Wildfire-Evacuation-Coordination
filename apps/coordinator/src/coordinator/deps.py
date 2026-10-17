"""Injectable coordinator dependencies (PLAN-08, RESEARCH Pitfall 9).

Graph nodes touch the outside world only through ``CoordinatorDeps``: the planning repository,
the road-graph loader, the fire simulator, the clock and the two optional LLM functions. Offline
tests build their own ``CoordinatorDeps`` with an in-memory repository, so no SQL is faked.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx
from agent_fire.ensemble import compute_fire_spread
from agent_routing import load_graph
from wildfire_core.clock import Clock, RealClock
from wildfire_core.config import Settings, load_settings
from wildfire_core.db.session import create_db_engine
from wildfire_core.schemas.phase2 import FireSpreadResult

from coordinator.llm.groq_adapter import RationaleResult, generate_plan_rationale
from coordinator.planning.resolver import StrategyChooser, deterministic_chooser, llm_chooser
from coordinator.repository import PlanningRepository, SqlPlanningRepository

GraphLoader = Callable[[Path], "nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]"]
FireFn = Callable[..., FireSpreadResult]
RationaleFn = Callable[[Mapping[str, Any], Settings], RationaleResult]
ChooserFactory = Callable[[Settings, Sequence[str]], StrategyChooser]


def default_chooser_factory(settings: Settings, order: Sequence[str]) -> StrategyChooser:
    """The optional LLM picks a menu item only when enabled; otherwise the fixed order (D-10)."""
    if settings.llm_enabled:
        return llm_chooser(settings, order)
    return deterministic_chooser(order)


@dataclass
class CoordinatorDeps:
    """Everything a coordinator run needs from outside the graph."""

    settings: Settings
    repository: PlanningRepository
    graph_loader: GraphLoader = load_graph
    fire_fn: FireFn = compute_fire_spread
    clock: Clock = field(default_factory=RealClock)
    rationale_fn: RationaleFn = generate_plan_rationale
    chooser_factory: ChooserFactory = default_chooser_factory
    # Run-scoped objects that are not JSON-serializable (routed graph); popped when the run ends.
    scratch: dict[str, dict[str, Any]] = field(default_factory=dict)


def default_deps() -> CoordinatorDeps:
    """Production wiring: settings from the environment, Postgres repository, real clock."""
    settings = load_settings()
    engine = create_db_engine(settings.database_url.get_secret_value())
    return CoordinatorDeps(
        settings=settings,
        repository=SqlPlanningRepository(engine, default_factor=settings.shelter_usable_factor),
        clock=RealClock(),
    )

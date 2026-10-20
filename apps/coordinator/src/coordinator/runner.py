"""Phase 3 coordinator graph and runner (TechSpec 6.2, PLAN-01).

Weather runs before fire, then risk, then the parallel specialists, the planning core, the
rationale, versioned persistence and the audit flush. ``run_coordinator`` streams the graph so
the last state is always known; if a node raises, the audit rows gathered so far plus a
``run_failed`` row are still flushed before the error is re-raised (RESEARCH Pitfall 15).
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from langgraph.graph import END, StateGraph
from wildfire_core.schemas.phase2 import AuditEntry

from coordinator.audit import RUN_FAILED_NODE
from coordinator.deps import CoordinatorDeps, default_deps
from coordinator.graph import NODE_ORDER, make_nodes
from coordinator.state import CoordinatorState, initial_state

logger = logging.getLogger(__name__)

CoordinatorGraph = StateGraph[CoordinatorState, None, CoordinatorState, CoordinatorState]


def build_graph(deps: CoordinatorDeps) -> CoordinatorGraph:
    graph = StateGraph(CoordinatorState)
    nodes = make_nodes(deps)
    for name in NODE_ORDER:
        graph.add_node(name, cast(Any, nodes[name]))

    graph.set_entry_point(NODE_ORDER[0])
    for current, following in zip(NODE_ORDER, NODE_ORDER[1:], strict=False):
        graph.add_edge(current, following)
    graph.add_edge(NODE_ORDER[-1], END)
    return graph


def _flush_failed_run(deps: CoordinatorDeps, last: CoordinatorState, error: Exception) -> None:
    """Persist what the run recorded before it failed, plus a ``run_failed`` row."""
    failure = AuditEntry(
        incident_id=last["incident_id"],
        run_id=last["run_id"],
        node_name=RUN_FAILED_NODE,
        inputs_json="{}",
        outputs_json=json.dumps({"error": type(error).__name__}),
        latency_ms=0,
    )
    entries = [*last["audit_entries"], failure.model_dump(mode="json")]
    try:
        deps.repository.flush_audit(entries)  # idempotent: ON CONFLICT (id) DO NOTHING
    except Exception:
        logger.exception("Could not flush audit rows for failed run %s", last["run_id"])


def run_coordinator(
    incident_id: str,
    run_id: str,
    *,
    trigger_id: str | None = None,
    deps: CoordinatorDeps | None = None,
) -> CoordinatorState:
    active = deps if deps is not None else default_deps()
    start = initial_state(incident_id, run_id, trigger_id)
    last = start
    try:
        for snapshot in build_graph(active).compile().stream(start, stream_mode="values"):
            last = cast(CoordinatorState, snapshot)
    except Exception as error:
        _flush_failed_run(active, last, error)
        raise
    finally:
        active.scratch.pop(run_id, None)
    return last

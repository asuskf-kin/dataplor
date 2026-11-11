"""Wires the nodes into the cleaning graph (user's flowchart, 2026-11-09).

start -> intake* (país ISO 2, bottler, tradicional|moderno, off|on premise|ambos,
         Dataplor raw) -> choose_cleaning* (¿Va a limpiar el Dataplor?) -> fetch_raw (blob dataplorraw)
      -> collect_inputs* -> fetch_inputs (GeoJSON/clients blobs) -> confirm_plan* --cancel--> END
      -> [sí: prefilter (distancia | client bottler) -> stage_bronze (espejo + QA)
          -> confirm_bronze* -> upload_bronze (prospecting-data/bronze/ko/...)
          -> front_dataplor* (Front; result + JSON) -> fetch_front]
          [no: front_dataplor* -> fetch_front]
          -> check_patterns -> [update_patterns* if missing or > 6 months] -> load_input
      -> run_module (x N) -> finalize -> approve_output* --reject--> END
      -> publish -> executive_report -> ask_datamatch*
           sí: front_datamatch* -> qa_explore -> choose_thresholds* -> qa_run --+
           no: ------------------------------------------------------------------+
      -> confirm_upload* -> [upload] -> build_lineage -> END

* = human-in-the-loop interrupt. An invalid answer loops back to the same
question up to ``max_attempts`` times, then the run is cancelled.
Pending: priorización and the production warehouse layout for the upload.
"""

import inspect
from collections.abc import Callable
from typing import Literal

from langgraph.graph import END, START, StateGraph

from cleaning_agent.application.graph import delivery_nodes as delivery
from cleaning_agent.application.graph import franchise_nodes as franchise
from cleaning_agent.application.graph import gold_nodes as gold
from cleaning_agent.application.graph import nodes
from cleaning_agent.application.graph import priorizacion_nodes as prioritization
from cleaning_agent.application.graph import warehouse_nodes as warehouse
from cleaning_agent.application.graph.nodes import Dependencies
from cleaning_agent.application.graph.progress import tracked
from cleaning_agent.application.graph.state import CleaningState
from cleaning_agent.domain.models import CleaningMode
from cleaning_agent.domain.warehouse import Layer

# Ask nodes + modules + fixed nodes stay well below this; it only stops a bug loop
RECURSION_LIMIT = 100


def _after_answer(next_node: str, max_attempts: int) -> Callable[[CleaningState], str]:
    """Routes a question: valid -> next, invalid -> ask again, too many -> give up."""

    def route(state: CleaningState) -> str:
        if state.get("errors"):
            return _retry_or_give_up(state, max_attempts)
        return next_node

    return route


def _retry_or_give_up(state: CleaningState, max_attempts: int) -> str:
    return "ask_again" if state.get("attempts", 0) < max_attempts else "give_up"


def _after_plan(max_attempts: int) -> Callable[[CleaningState], str]:
    def route(state: CleaningState) -> str:
        if state.get("errors"):
            return _retry_or_give_up(state, max_attempts)
        if state.get("status") == "cancelled":
            return "cancelled"
        # No cleaning: the raw Dataplor goes to the Front first
        return (
            "front_dataplor" if state["mode"] == CleaningMode.NINGUNO else "prefilter"
        )

    return route


def _after_step(state: CleaningState) -> Literal["continue", "failed"]:
    return "failed" if state.get("status") == "failed" else "continue"


def _after_module(state: CleaningState) -> Literal["run_module", "finalize"]:
    return "run_module" if state["cursor"] < len(state["modules"]) else "finalize"


def _after_output(max_attempts: int) -> Callable[[CleaningState], str]:
    def route(state: CleaningState) -> str:
        if state.get("errors"):
            return _retry_or_give_up(state, max_attempts)
        return "rejected" if state.get("status") == "rejected" else "publish"

    return route


def _after_datamatch_choice(max_attempts: int) -> Callable[[CleaningState], str]:
    def route(state: CleaningState) -> str:
        if state.get("errors"):
            return _retry_or_give_up(state, max_attempts)
        return "front_datamatch" if state.get("run_datamatch") else "confirm_upload"

    return route


def _after_upload_decision(max_attempts: int) -> Callable[[CleaningState], str]:
    def route(state: CleaningState) -> str:
        if state.get("errors"):
            return _retry_or_give_up(state, max_attempts)
        return "kept_local" if state.get("status") == "kept_local" else "upload"

    return route


def _after_layer_answer(max_attempts: int) -> Callable[[CleaningState], str]:
    def route(state: CleaningState) -> str:
        if state.get("errors"):
            return _retry_or_give_up(state, max_attempts)
        return warehouse.after_confirm_bronze(state)

    return route


def _after_patterns_check(state: CleaningState) -> str:
    return "update" if (state.get("patterns") or {}).get("needs_update") else "ok"


def _after_patterns_update(max_attempts: int) -> Callable[[CleaningState], str]:
    def route(state: CleaningState) -> str:
        if state.get("errors"):
            return _retry_or_give_up(state, max_attempts)
        return "failed" if state.get("status") == "failed" else "load_input"

    return route


def _after_layer_upload(state: CleaningState) -> str:
    if state.get("status") == "failed":
        return "failed"
    return "ask_again" if state.get("errors") else "continue"


def _after_franchise_review(max_attempts: int) -> Callable[[CleaningState], str]:
    def route(state: CleaningState) -> str:
        if state.get("errors"):
            return _retry_or_give_up(state, max_attempts)
        return franchise.after_franchise_review(state)

    return route


def _after_priorizacion_answer(max_attempts: int) -> Callable[[CleaningState], str]:
    def route(state: CleaningState) -> str:
        if state.get("errors"):
            return _retry_or_give_up(state, max_attempts)
        return prioritization.after_ask_priorizacion(state)

    return route


def _after_layer_answer_to(
    _next: str, max_attempts: int
) -> Callable[[CleaningState], str]:
    # Same decision as bronze: approved -> upload, declined -> the run stops (kept local)
    return _after_layer_answer(max_attempts)


def _after_layer_upload_to(_next: str) -> Callable[[CleaningState], str]:
    return _after_layer_upload


def _after_stage_gold(state: CleaningState) -> str:
    pending = state.get("pending_upload") or {}
    return "continue" if pending.get("layer") == Layer.GOLD.value else "skip"


def _after_datamatch_loop(max_attempts: int) -> Callable[[CleaningState], str]:
    def route(state: CleaningState) -> str:
        if state.get("errors"):
            return _retry_or_give_up(state, max_attempts)
        return "done" if state.get("datamatch_loop_done") else "iterate"

    return route


def give_up(state: CleaningState) -> nodes.Update:
    """Done when a run with too many invalid answers is marked cancelled."""
    return {
        "status": "cancelled",
        "error": "Too many invalid answers: " + "; ".join(state.get("errors", [])),
    }


CleaningGraph = StateGraph[CleaningState, None, CleaningState, CleaningState]


def _add(g: CleaningGraph, name: str, fn: Callable[..., nodes.Update]) -> None:
    """Adds a node wrapped so its status lands in step_status (harness visibility)."""
    takes_config = "config" in inspect.signature(fn).parameters
    g.add_node(name, tracked(name, fn, takes_config))


def build_graph(deps: Dependencies) -> CleaningGraph:
    g: CleaningGraph = StateGraph(CleaningState)
    _add(g, "start", nodes.start)
    _add(g, "intake", nodes.make_intake(deps))
    _add(g, "choose_cleaning", nodes.choose_cleaning)
    _add(g, "fetch_raw", nodes.make_fetch_raw(deps))
    _add(g, "collect_inputs", nodes.make_collect_inputs(deps))
    _add(g, "fetch_inputs", nodes.make_fetch_inputs(deps))
    _add(g, "confirm_plan", nodes.make_confirm_plan(deps))
    _add(g, "prefilter", nodes.make_prefilter(deps))
    _add(g, "stage_bronze", warehouse.make_stage_bronze(deps))
    _add(g, "confirm_bronze", warehouse.make_confirm_layer(deps, Layer.BRONZE))
    _add(g, "upload_bronze", warehouse.make_upload_layer(deps, Layer.BRONZE))
    _add(g, "front_dataplor", warehouse.make_front_dataplor(deps))
    _add(g, "fetch_front", warehouse.make_fetch_front(deps))
    _add(g, "check_patterns", nodes.make_check_patterns(deps))
    _add(g, "update_patterns", nodes.make_update_patterns(deps))
    _add(g, "load_input", nodes.make_load_input(deps))
    _add(g, "run_module", nodes.make_run_module(deps))
    _add(g, "finalize", nodes.make_finalize(deps))
    _add(g, "prepare_franchise_review", franchise.make_prepare_franchise_review(deps))
    _add(g, "franchise_review", franchise.make_franchise_review(deps))
    _add(g, "confirm_franchises", franchise.confirm_franchises)
    _add(g, "stage_silver", warehouse.make_stage_silver(deps))
    _add(g, "confirm_silver", warehouse.make_confirm_layer(deps, Layer.SILVER))
    _add(g, "upload_silver", warehouse.make_upload_layer(deps, Layer.SILVER))
    _add(g, "stage_gold", warehouse.make_stage_gold(deps))
    _add(g, "confirm_gold", warehouse.make_confirm_layer(deps, Layer.GOLD))
    _add(g, "upload_gold", warehouse.make_upload_layer(deps, Layer.GOLD))
    _add(g, "publish", nodes.make_publish(deps))
    _add(g, "executive_report", delivery.make_executive_report(deps))
    _add(g, "front_datamatch", delivery.make_front_datamatch(deps))
    _add(g, "fetch_datamatch", warehouse.make_fetch_datamatch(deps))
    _add(g, "stage_datamatch_step", warehouse.make_stage_datamatch_step(deps))
    _add(g, "confirm_datamatch_step", warehouse.make_confirm_layer(deps, Layer.SILVER))
    _add(g, "upload_datamatch_step", warehouse.make_upload_layer(deps, Layer.SILVER))
    _add(g, "next_datamatch_step", warehouse.make_next_datamatch_step(deps))
    _add(g, "stage_prospects", warehouse.make_stage_prospects(deps))
    _add(g, "confirm_prospects", warehouse.make_confirm_layer(deps, Layer.GOLD))
    _add(g, "upload_prospects", warehouse.make_upload_layer(deps, Layer.GOLD))
    _add(g, "ask_priorizacion", prioritization.make_ask_priorizacion(deps))
    _add(g, "run_priorizacion", prioritization.make_run_priorizacion(deps))
    _add(g, "stage_priorizacion", prioritization.make_stage_priorizacion(deps))
    _add(g, "confirm_priorizacion", warehouse.make_confirm_layer(deps, Layer.BRONZE))
    _add(g, "upload_priorizacion", warehouse.make_upload_layer(deps, Layer.BRONZE))
    _add(g, "stage_gold_package", gold.make_stage_gold_package(deps))
    _add(g, "confirm_gold_package", warehouse.make_confirm_layer(deps, Layer.GOLD))
    _add(g, "upload_gold_package", warehouse.make_upload_layer(deps, Layer.GOLD))
    _add(g, "build_lineage", delivery.make_build_lineage(deps))
    _add(g, "give_up", give_up)

    g.add_edge(START, "start")
    g.add_edge("start", "intake")
    g.add_conditional_edges(
        "intake",
        _after_answer("choose_cleaning", deps.max_attempts),
        {
            "choose_cleaning": "choose_cleaning",
            "ask_again": "intake",
            "give_up": "give_up",
        },
    )
    g.add_conditional_edges(
        "choose_cleaning",
        _after_answer("fetch_raw", deps.max_attempts),
        {
            "fetch_raw": "fetch_raw",
            "ask_again": "choose_cleaning",
            "give_up": "give_up",
        },
    )
    g.add_conditional_edges(
        "fetch_raw", _after_step, {"continue": "collect_inputs", "failed": END}
    )
    g.add_conditional_edges(
        "collect_inputs",
        _after_answer("fetch_inputs", deps.max_attempts),
        {
            "fetch_inputs": "fetch_inputs",
            "ask_again": "collect_inputs",
            "give_up": "give_up",
        },
    )
    g.add_conditional_edges(
        "fetch_inputs", _after_step, {"continue": "confirm_plan", "failed": END}
    )
    g.add_conditional_edges(
        "confirm_plan",
        _after_plan(deps.max_attempts),
        {
            "prefilter": "prefilter",
            "front_dataplor": "front_dataplor",
            "ask_again": "confirm_plan",
            "give_up": "give_up",
            "cancelled": END,
        },
    )
    g.add_conditional_edges(
        "prefilter", _after_step, {"continue": "stage_bronze", "failed": END}
    )
    g.add_conditional_edges(
        "stage_bronze", _after_step, {"continue": "confirm_bronze", "failed": END}
    )
    g.add_conditional_edges(
        "confirm_bronze",
        _after_layer_answer(deps.max_attempts),
        {
            "upload": "upload_bronze",
            "stop": END,
            "ask_again": "confirm_bronze",
            "give_up": "give_up",
        },
    )
    g.add_conditional_edges(
        "upload_bronze",
        _after_layer_upload,
        {"continue": "front_dataplor", "ask_again": "confirm_bronze", "failed": END},
    )
    g.add_conditional_edges(
        "front_dataplor",
        _after_answer("fetch_front", deps.max_attempts),
        {
            "fetch_front": "fetch_front",
            "ask_again": "front_dataplor",
            "give_up": "give_up",
        },
    )
    g.add_conditional_edges(
        "fetch_front", _after_step, {"continue": "check_patterns", "failed": END}
    )
    g.add_conditional_edges(
        "check_patterns",
        _after_patterns_check,
        {"update": "update_patterns", "ok": "load_input"},
    )
    g.add_conditional_edges(
        "update_patterns",
        _after_patterns_update(deps.max_attempts),
        {
            "load_input": "load_input",
            "ask_again": "update_patterns",
            "give_up": "give_up",
            "failed": END,
        },
    )
    g.add_conditional_edges(
        "load_input", _after_step, {"continue": "run_module", "failed": END}
    )
    g.add_conditional_edges(
        "run_module",
        _after_module,
        {"run_module": "run_module", "finalize": "finalize"},
    )
    g.add_edge("finalize", "prepare_franchise_review")
    g.add_edge("prepare_franchise_review", "franchise_review")
    g.add_conditional_edges(
        "franchise_review",
        _after_franchise_review(deps.max_attempts),
        {
            "confirm": "confirm_franchises",
            "skip": "stage_silver",
            "ask_again": "franchise_review",
            "give_up": "give_up",
        },
    )
    g.add_conditional_edges(
        "confirm_franchises",
        _after_answer("stage_silver", deps.max_attempts),
        {
            "stage_silver": "stage_silver",
            "ask_again": "confirm_franchises",
            "give_up": "give_up",
        },
    )
    g.add_conditional_edges(
        "stage_silver", _after_step, {"continue": "publish", "failed": END}
    )
    g.add_conditional_edges(
        "confirm_silver",
        _after_layer_answer_to("upload", deps.max_attempts),
        {
            "upload": "upload_silver",
            "stop": END,
            "ask_again": "confirm_silver",
            "give_up": "give_up",
        },
    )
    g.add_conditional_edges(
        "upload_silver",
        _after_layer_upload_to("stage_gold"),
        {"continue": "stage_gold", "ask_again": "confirm_silver", "failed": END},
    )
    # Gold: the executive Excel + its metadata (user, 2026-11-10); nothing there -> skip
    g.add_conditional_edges(
        "stage_gold",
        _after_stage_gold,
        {"continue": "confirm_gold", "skip": "front_datamatch"},
    )
    g.add_conditional_edges(
        "confirm_gold",
        _after_layer_answer_to("upload", deps.max_attempts),
        {
            "upload": "upload_gold",
            "stop": END,
            "ask_again": "confirm_gold",
            "give_up": "give_up",
        },
    )
    g.add_conditional_edges(
        "upload_gold",
        _after_layer_upload_to("front_datamatch"),
        {"continue": "front_datamatch", "ask_again": "confirm_gold", "failed": END},
    )
    # The local CSV and the executive report (funnel, PDF, HTML) are built before the
    # silver approval so the person validates everything together (user, 2026-11-10).
    g.add_edge("publish", "executive_report")
    g.add_edge("executive_report", "confirm_silver")
    g.add_conditional_edges(
        "front_datamatch",
        _after_answer("fetch_datamatch", deps.max_attempts),
        {
            "fetch_datamatch": "fetch_datamatch",
            "ask_again": "front_datamatch",
            "give_up": "give_up",
        },
    )
    # Datamatch loop (user, 2026-11-11): each Front step drops the matched clients
    # from the base, goes to silver qa_process and repeats until the person says done
    g.add_conditional_edges(
        "fetch_datamatch",
        _after_step,
        {"continue": "stage_datamatch_step", "failed": END},
    )
    g.add_conditional_edges(
        "stage_datamatch_step",
        _after_step,
        {"continue": "confirm_datamatch_step", "failed": END},
    )
    g.add_conditional_edges(
        "confirm_datamatch_step",
        _after_layer_answer_to("upload", deps.max_attempts),
        {
            "upload": "upload_datamatch_step",
            "stop": END,
            "ask_again": "confirm_datamatch_step",
            "give_up": "give_up",
        },
    )
    g.add_conditional_edges(
        "upload_datamatch_step",
        _after_layer_upload_to("next_datamatch_step"),
        {
            "continue": "next_datamatch_step",
            "ask_again": "confirm_datamatch_step",
            "failed": END,
        },
    )
    g.add_conditional_edges(
        "next_datamatch_step",
        _after_datamatch_loop(deps.max_attempts),
        {
            "iterate": "front_datamatch",
            "done": "stage_prospects",
            "ask_again": "next_datamatch_step",
            "give_up": "give_up",
        },
    )
    # Loop done (user, 2026-11-11): the prospects file is the first data in gold and
    # the input of priorización; the old QA-threshold steps were replaced by the loop
    g.add_conditional_edges(
        "stage_prospects", _after_step, {"continue": "confirm_prospects", "failed": END}
    )
    g.add_conditional_edges(
        "confirm_prospects",
        _after_layer_answer_to("upload", deps.max_attempts),
        {
            "upload": "upload_prospects",
            "stop": END,
            "ask_again": "confirm_prospects",
            "give_up": "give_up",
        },
    )
    g.add_conditional_edges(
        "upload_prospects",
        _after_layer_upload_to("ask_priorizacion"),
        {
            "continue": "ask_priorizacion",
            "ask_again": "confirm_prospects",
            "failed": END,
        },
    )
    g.add_conditional_edges(
        "ask_priorizacion",
        _after_priorizacion_answer(deps.max_attempts),
        {
            "run": "run_priorizacion",
            "skip": "build_lineage",
            "ask_again": "ask_priorizacion",
            "give_up": "give_up",
        },
    )
    g.add_conditional_edges(
        "run_priorizacion",
        _after_step,
        {"continue": "stage_priorizacion", "failed": END},
    )
    g.add_conditional_edges(
        "stage_priorizacion",
        _after_step,
        {"continue": "confirm_priorizacion", "failed": END},
    )
    g.add_conditional_edges(
        "confirm_priorizacion",
        _after_layer_answer_to("upload", deps.max_attempts),
        {
            "upload": "upload_priorizacion",
            "stop": END,
            "ask_again": "confirm_priorizacion",
            "give_up": "give_up",
        },
    )
    g.add_conditional_edges(
        "upload_priorizacion",
        _after_layer_upload_to("stage_gold_package"),
        {
            "continue": "stage_gold_package",
            "ask_again": "confirm_priorizacion",
            "failed": END,
        },
    )
    # Gold delivery package (user, 2026-11-11): modelled on the approved Golfo package
    g.add_conditional_edges(
        "stage_gold_package",
        _after_step,
        {"continue": "confirm_gold_package", "failed": END},
    )
    g.add_conditional_edges(
        "confirm_gold_package",
        _after_layer_answer_to("upload", deps.max_attempts),
        {
            "upload": "upload_gold_package",
            "stop": END,
            "ask_again": "confirm_gold_package",
            "give_up": "give_up",
        },
    )
    g.add_conditional_edges(
        "upload_gold_package",
        _after_layer_upload_to("build_lineage"),
        {
            "continue": "build_lineage",
            "ask_again": "confirm_gold_package",
            "failed": END,
        },
    )
    g.add_edge("build_lineage", END)
    g.add_edge("give_up", END)
    return g

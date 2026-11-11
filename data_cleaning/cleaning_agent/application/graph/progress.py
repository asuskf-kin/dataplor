"""Status of every step of the run (harness: the run's progress must be visible).

Each node is wrapped by ``tracked``: when it returns, its step is recorded in
``step_status`` (status, start/end time, short detail). The step currently waiting
for a human is derived from the checkpoint (``snapshot.next``), because an
interrupted node never returns. ``step_view`` merges both with the planned order,
so ``status`` always shows done / waiting / pending / skipped for the whole flow.
"""

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from langchain_core.runnables import RunnableConfig

from cleaning_agent.domain.lineage import now_iso

Update = dict[str, Any]


class TrackedNode(Protocol):
    def __call__(self, state: Any, config: RunnableConfig) -> Update: ...


# Planned order of the flow (user's flowchart). run_module expands per module.
STEP_ORDER: list[tuple[str, str]] = [
    ("intake", "Datos de la corrida (país, bottler, canal, premise, raw)"),
    ("choose_cleaning", "¿Va a limpiar el Dataplor?"),
    ("fetch_raw", "Descarga del Dataplor raw"),
    ("collect_inputs", "Insumos del modo (GeoJSON / clientes / salida)"),
    ("fetch_inputs", "Descarga de insumos"),
    ("confirm_plan", "Aprobación del plan"),
    ("prefilter", "Pre-filtro (distancia / client bottler)"),
    ("stage_bronze", "Bronze: espejo local + QA"),
    ("confirm_bronze", "Bronze: aprobación de subida"),
    ("upload_bronze", "Bronze: subida a prospecting-data"),
    ("front_dataplor", "Front: proceso con el bronze (resultado + JSON)"),
    ("fetch_front", "Descarga del resultado del Front"),
    ("check_patterns", "Patrones del país: existen y tienen menos de 6 meses"),
    ("update_patterns", "Patrones del país: crear/actualizar (con tu OK)"),
    ("load_input", "Carga del Dataplor a limpiar"),
    ("run_module", "Pipeline Data clean"),
    ("finalize", "Auditoría y reporte de descartes"),
    ("prepare_franchise_review", "Review de franquicias: candidatos"),
    ("franchise_review", "Review de franquicias (Claude Code)"),
    ("confirm_franchises", "Review de franquicias: ¿eliminar las marcadas?"),
    ("stage_silver", "Silver: espejo local + QA"),
    ("publish", "Publicación del CSV limpio"),
    ("executive_report", "Reporte ejecutivo"),
    ("confirm_silver", "Silver: validación y aprobación de subida"),
    ("upload_silver", "Silver: subida a prospecting-data"),
    ("stage_gold", "Gold: espejo local (Excel ejecutivo + metadata)"),
    ("confirm_gold", "Gold: validación y aprobación de subida"),
    ("upload_gold", "Gold: subida a prospecting-data"),
    ("front_datamatch", "Datamatch en el Front"),
    ("fetch_datamatch", "Datamatch: descarga al espejo local"),
    ("stage_datamatch_step", "Datamatch: limpiar clientes encontrados + Excel"),
    ("confirm_datamatch_step", "Datamatch: validar y aprobar subida a silver"),
    ("upload_datamatch_step", "Datamatch: subida a silver qa_process"),
    ("next_datamatch_step", "Datamatch: ¿otro paso o seguimos?"),
    ("stage_prospects", "Gold: prospectos (sin clientes conocidos) + QA"),
    ("confirm_prospects", "Gold: validar y aprobar subida de prospectos"),
    ("upload_prospects", "Gold: subida de prospectos"),
    ("ask_priorizacion", "Priorización: ¿correr y con qué config?"),
    ("run_priorizacion", "Priorización"),
    ("stage_priorizacion", "Priorización: espejo local + QA"),
    ("confirm_priorizacion", "Priorización: validar y subir metadata"),
    ("upload_priorizacion", "Priorización: subida y verificación MD5"),
    ("stage_gold_package", "Gold: paquete KO / BOTTLER, Excel, mapas y deck + QA"),
    ("confirm_gold_package", "Gold: validar y aprobar subida del paquete"),
    ("upload_gold_package", "Gold: subida del paquete"),
    ("build_lineage", "Linaje de la corrida"),
]
DATAMATCH_STEPS: set[str] = set()  # Datamatch is always part of the flow (flow v4)
TERMINAL_STATUSES = {"cancelled", "rejected", "kept_local", "failed"}


def merge_steps(
    left: dict[str, dict[str, Any]] | None, right: dict[str, dict[str, Any]] | None
) -> dict[str, dict[str, Any]]:
    """Reducer: a step's latest record replaces the previous one, others are kept."""
    return {**(left or {}), **(right or {})}


def _step_key(name: str, state: Mapping[str, Any]) -> str:
    if name == "run_module" and state.get("modules"):
        cursor = int(state.get("cursor", 0))
        modules = list(state["modules"])
        if cursor < len(modules):
            return f"run_module:{modules[cursor]}"
    return name


def _outcome(update: Mapping[str, Any]) -> tuple[str, str]:
    if update.get("status") == "failed":
        return "failed", str(update.get("error") or "")
    if update.get("errors"):
        return "retry", "; ".join(map(str, update["errors"]))[:300]
    if update.get("status") in TERMINAL_STATUSES:
        return str(update["status"]), str(
            update.get("note") or update.get("error") or ""
        )
    return "done", ""


def tracked(
    name: str, fn: Callable[..., Update], takes_config: bool = False
) -> TrackedNode:
    """Wraps a node so its result is recorded in ``step_status``.

    It never catches exceptions: interrupts must propagate untouched (rules of
    interrupts), and real errors keep their traceback.
    """

    def run(state: Any, config: RunnableConfig) -> Update:
        started = now_iso()
        key = _step_key(name, state)
        update = fn(state, config) if takes_config else fn(state)
        status, detail = _outcome(update)
        record = {"status": status, "started_at": started, "finished_at": now_iso()}
        if detail:
            record["detail"] = detail
        return {**update, "step_status": {key: record}}

    run.__name__ = name
    return run


def step_view(
    values: Mapping[str, Any], waiting: tuple[str, ...]
) -> list[dict[str, Any]]:
    """The whole flow in order: what is done, waiting, pending or skipped."""
    recorded: Mapping[str, Mapping[str, Any]] = values.get("step_status") or {}
    mode = values.get("mode")
    run_datamatch = values.get("run_datamatch")
    finished = values.get("status") in TERMINAL_STATUSES
    view: list[dict[str, Any]] = []
    for name, label in STEP_ORDER:
        keys = [name]
        if name == "run_module":
            keys = [f"run_module:{m}" for m in values.get("modules") or []] or [name]
        for key in keys:
            entry: dict[str, Any] = {"step": key, "label": label}
            if key != name:
                entry["label"] = f"{label}: módulo {key.split(':')[1]}"
            if key in recorded:
                entry.update(recorded[key])
            elif name in waiting:
                entry["status"] = "waiting_for_human"
            elif (
                name
                in {
                    "prefilter",
                    "stage_bronze",
                    "confirm_bronze",
                    "upload_bronze",
                }
                and mode == "ninguno"
            ) or (name in DATAMATCH_STEPS and run_datamatch is False):
                entry["status"] = "skipped"
            elif finished:
                entry["status"] = "not_run"
            else:
                entry["status"] = "pending"
            view.append(entry)
    return view


def progress_markdown(thread_id: str, status: str, steps: list[dict[str, Any]]) -> str:
    """Human-readable progress file (handoff between sessions lives in the repo)."""
    icons = {
        "done": "✅",
        "waiting_for_human": "⏸️",
        "pending": "⬜",
        "skipped": "➖",
        "retry": "🔁",
        "failed": "❌",
        "not_run": "▫️",
        "cancelled": "⛔",
        "rejected": "⛔",
        "kept_local": "💾",
    }
    lines = [
        f"# Progreso de la corrida `{thread_id}`",
        "",
        f"Estado general: **{status}**",
        "",
        "| | Paso | Estado | Inicio | Fin | Detalle |",
        "|---|---|---|---|---|---|",
    ]
    for step in steps:
        lines.append(
            f"| {icons.get(step['status'], '')} | {step['label']} | {step['status']} | "
            f"{step.get('started_at', '')} | {step.get('finished_at', '')} | "
            f"{str(step.get('detail', '')).replace('|', '/')} |"
        )
    return "\n".join(lines) + "\n"

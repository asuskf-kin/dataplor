"""CLI of the cleaning agent. Built for two drivers:

- Claude Code (skill /limpiar-dataplor): ``start`` / ``resume`` / ``status`` print ONE
  JSON object on stdout (logs go to stderr). When ``status`` is ``waiting_for_human``
  the ``interrupt`` field holds the question to ask the user.
- A person in a terminal: ``interactive`` asks every question with input().

Each run is a LangGraph thread persisted in SQLite: closing the terminal between
questions loses nothing; ``resume`` continues the same thread.

    uv run python -m cleaning_agent start
    uv run python -m cleaning_agent resume --thread <id> --answer '{"mode": "geojson"}'
    uv run python -m cleaning_agent status --thread <id>
    uv run python -m cleaning_agent interactive
    uv run python -m cleaning_agent graph          # Mermaid diagram
    uv run python -m cleaning_agent maps --thread <id> --gold-dir data/gold/ko/<pais>/<bottler>/prospecting-data/<fecha>
    uv run python -m cleaning_agent sidecars --thread <id> --gold-dir data/gold/ko/<pais>/<bottler>/prospecting-data/<fecha>
"""

import argparse
import json
import logging
import secrets
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pydantic import ValidationError

from cleaning_agent.adapters.lineage import STAGE_KEY
from cleaning_agent.application.graph.builder import RECURSION_LIMIT, build_graph
from cleaning_agent.application.graph.delivery_nodes import datamatch_cycle_reset
from cleaning_agent.application.graph.gold_nodes import (
    gold_request,
    write_package_sidecars,
)
from cleaning_agent.application.graph.progress import progress_markdown, step_view
from cleaning_agent.application.graph.state import CleaningState
from cleaning_agent.domain.lineage import StageRecord
from cleaning_agent.domain.models import DatamatchInputs
from cleaning_agent.domain.warehouse import Layer, layer_prefix
from cleaning_agent.settings import PROJECT_ROOT
from cleaning_agent.wiring import checkpoints_path, default_dependencies, dwh_paths

MAX_ANSWER_CHARS = 20_000
# Step rules a redo may change (see run_redo)
DATAMATCH_RULES = {
    "umbral",
    "distancia_match_m",
    "solo_distancia",
    "enfoque",
    "filtrar_a_base",
}
THREAD_ID_MAX = 100


def _config(thread_id: str) -> RunnableConfig:
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": RECURSION_LIMIT,
    }


def new_thread_id() -> str:
    return f"dataplor-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def _check_thread_id(thread_id: str) -> str:
    if not 0 < len(thread_id) <= THREAD_ID_MAX or not all(
        ch.isalnum() or ch in "-_" for ch in thread_id
    ):
        raise SystemExit("thread id: 1-100 characters, letters, digits, '-' or '_'")
    return thread_id


@contextmanager
def open_app() -> Iterator[CompiledStateGraph[Any, Any, Any, Any]]:
    with SqliteSaver.from_conn_string(str(checkpoints_path())) as checkpointer:
        yield build_graph(default_dependencies()).compile(checkpointer=checkpointer)


def _pending(
    app: CompiledStateGraph[Any, Any, Any, Any], thread_id: str
) -> dict[str, Any] | None:
    interrupts = app.get_state(_config(thread_id)).interrupts
    return dict(interrupts[0].value) if interrupts else None


def describe(
    app: CompiledStateGraph[Any, Any, Any, Any], thread_id: str
) -> dict[str, Any]:
    """Machine-readable view of a thread for the driver (Claude Code or a person)."""
    snapshot = app.get_state(_config(thread_id))
    values = dict(snapshot.values)
    pending = _pending(app, thread_id)
    if not values and pending is None:
        status = "not_found"
    elif pending is not None:
        status = "waiting_for_human"
    else:
        status = str(values.get("status", "unknown"))
    steps = step_view(values, tuple(snapshot.next))
    current = next(
        (st["step"] for st in steps if st["status"] == "waiting_for_human"), None
    )
    return {
        "thread_id": thread_id,
        "status": status,
        "current_step": current,
        "steps": steps,
        "interrupt": pending,
        "error": values.get("error"),
        "result": {
            key: values.get(key)
            for key in (
                "mode",
                "modules",
                "summary",
                "report_path",
                "output_path",
                "note",
            )
            if values.get(key) is not None
        },
    }


def _merge_answer(pending: dict[str, Any], answer: Any) -> Any:
    # For path forms the driver may send only the fields that change
    if pending.get("kind") == "collect_inputs" and isinstance(answer, dict):
        return {**(pending.get("defaults") or {}), **answer}
    return answer


def _drive(
    app: CompiledStateGraph[Any, Any, Any, Any], payload: Any, thread_id: str
) -> None:
    """Runs until the next interrupt or the end, logging live progress of long steps."""
    log = logging.getLogger("cleaning_agent")
    for event in app.stream(
        payload, _config(thread_id), stream_mode="custom", durability="sync"
    ):
        if isinstance(event, dict) and "percent" in event:
            log.info(
                "%s: %s%% (%s / %s MB) %s",
                event.get("step"),
                event["percent"],
                event["done"] // 2**20,
                event["total"] // 2**20,
                event.get("file", ""),
            )


def save_progress(view: dict[str, Any]) -> None:
    """progress.json + PROGRESS.md per run: the state survives the session (handoff)."""
    folder = checkpoints_path().parent / "runs" / str(view["thread_id"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "progress.json").write_text(
        json.dumps(view, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (folder / "PROGRESS.md").write_text(
        progress_markdown(
            str(view["thread_id"]), str(view["status"]), view.get("steps") or []
        ),
        encoding="utf-8",
    )


def run_start(
    app: CompiledStateGraph[Any, Any, Any, Any], thread_id: str
) -> dict[str, Any]:
    if app.get_state(_config(thread_id)).values:
        raise SystemExit(f"Thread {thread_id} already exists: use resume or status")
    _drive(app, {}, thread_id)
    return describe(app, thread_id)


def _split_states(raw: str | None) -> list[str] | None:
    """``--excluir-estados "A, B"`` -> ["A", "B"]; an empty value clears the list."""
    if raw is None:
        return None
    return [s.strip() for s in raw.split(",") if s.strip()]


def run_redo(
    app: CompiledStateGraph[Any, Any, Any, Any],
    thread_id: str,
    after: str,
    umbral: float | None = None,
    datamatch_rules: dict[str, Any] | None = None,
    excluded_states: list[str] | None = None,
) -> dict[str, Any]:
    """Time travel: forks the thread as if ``after`` just finished and runs on.

    Used when a step's code changed (e.g. a deliverable format) and its result must be
    regenerated without repeating the expensive steps before it. The original
    checkpoints stay in the history.
    """
    if after not in app.get_graph().nodes:
        raise SystemExit(f"Unknown node {after!r}")
    if not app.get_state(_config(thread_id)).values:
        raise SystemExit(f"Thread {thread_id} does not exist")
    reset: dict[str, Any] = {"errors": [], "attempts": 0}
    # A redo reruns a step after its code was fixed: an earlier failure must not route
    # the fork straight to the end
    values = app.get_state(_config(thread_id)).values
    if values.get("status") == "failed":
        reset |= {"status": "running", "error": None}
    # Going back to before the Datamatch loop starts a new cycle (no old steps)
    reset |= datamatch_cycle_reset(after, cast(CleaningState, values))
    if umbral is not None:
        # Threshold chosen on the step's threshold page (same bounds as the answer field)
        if not 0 < umbral < 1:
            raise SystemExit("--umbral must be between 0 and 1")
        datamatch = reset.get("datamatch") or values.get("datamatch") or {}
        reset["datamatch"] = {**datamatch, "umbral": umbral}
    if excluded_states is not None:
        # Provinces the bottler does not serve: rebuilt prospects leave them out
        reset["excluded_states"] = excluded_states
    if datamatch_rules:
        # Step rules changed after reading its reports (umbral, distancia_match_m,
        # solo_distancia): validated with the same model as the front_datamatch answer
        unknown = set(datamatch_rules) - DATAMATCH_RULES
        if unknown:
            raise SystemExit(f"--datamatch accepts only {sorted(DATAMATCH_RULES)}")
        datamatch = reset.get("datamatch") or values.get("datamatch") or {}
        merged = {**datamatch, **datamatch_rules}
        try:
            DatamatchInputs.model_validate(merged)
        except ValidationError as exc:
            raise SystemExit(f"--datamatch: {exc}") from exc
        reset["datamatch"] = merged
    app.update_state(_config(thread_id), reset, as_node=after)
    _drive(app, None, thread_id)
    return describe(app, thread_id)


def run_resume(
    app: CompiledStateGraph[Any, Any, Any, Any], thread_id: str, answer: Any
) -> dict[str, Any]:
    pending = _pending(app, thread_id)
    if pending is None:
        raise SystemExit(f"Thread {thread_id} is not waiting for an answer")
    _drive(app, Command(resume=_merge_answer(pending, answer)), thread_id)
    return describe(app, thread_id)


def _parse_answer(raw: str) -> Any:
    if len(raw) > MAX_ANSWER_CHARS:
        raise SystemExit(f"answer longer than {MAX_ANSWER_CHARS} characters")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"answer is not valid JSON: {exc}") from exc


# --- interactive (person in a terminal) -------------------------------------------
def _ask_yes_no(prompt: str) -> bool:
    return input(f"{prompt} [s/n]: ").strip().lower() in {"s", "si", "sí", "y", "yes"}


def _interactive_answer(pending: dict[str, Any]) -> Any:
    kind = pending.get("kind")
    for error in pending.get("errors") or []:
        print(f"  ! {error}")
    print(f"\n{pending.get('question', '')}")
    if kind == "intake":
        # One question per field, in the order the payload lists them
        defaults = pending.get("defaults") or {}
        answer: dict[str, str] = {}
        for item in pending["fields"]:
            options = item.get("options")
            hint = f" {options}" if options else ""
            default = defaults.get(item["name"], "")
            shown = f" [{default}]" if default else ""
            value = input(f"{item['question']}{hint}{shown}: ").strip()
            answer[item["name"]] = value or str(default)
        return answer
    if kind == "choose_cleaning":
        options = pending["options"]
        for number, option in enumerate(options, start=1):
            print(f"  {number}. {option['label']}")
        choice = input("Elige un número: ").strip()
        index = int(choice) - 1 if choice.isdigit() else -1
        if not 0 <= index < len(options):
            return {"clean": choice}  # invalid on purpose: the graph re-asks
        return {k: v for k, v in options[index].items() if k != "label"}
    if kind == "collect_inputs":
        print(json.dumps(pending.get("defaults"), ensure_ascii=False, indent=2))
        raw = input(
            "Enter = usar estos valores, o pega un JSON con los campos a cambiar: "
        )
        return _parse_answer(raw) if raw.strip() else {}
    if kind == "confirm_plan":
        print(json.dumps(pending.get("modules"), ensure_ascii=False))
        for note in pending.get("notes") or []:
            print(f"  · {note}")
        approved = _ask_yes_no("¿Apruebas el plan?")
        raw = (
            input("Módulos (ej. 1,2,3; Enter = los propuestos): ").strip()
            if approved
            else ""
        )
        modules = [int(m) for m in raw.split(",") if m.strip().isdigit()] or None
        return {"approved": approved, "modules": modules}
    if kind == "approve_output":
        print(json.dumps(pending.get("summary"), ensure_ascii=False, indent=2))
        print(f"Reporte HTML: {pending.get('html_report')}")
        return {"approved": _ask_yes_no(f"¿Publico en {pending.get('output_csv')}?")}
    return _parse_answer(input("Respuesta JSON: "))


def run_interactive(
    app: CompiledStateGraph[Any, Any, Any, Any], thread_id: str
) -> dict[str, Any]:
    view = describe(app, thread_id)
    if view["status"] == "not_found":
        view = run_start(app, thread_id)
    print(f"Hilo: {thread_id}")
    while view["status"] == "waiting_for_human":
        view = run_resume(app, thread_id, _interactive_answer(view["interrupt"]))
    return view


def run_maps(
    app: CompiledStateGraph[Any, Any, Any, Any], thread_id: str, gold_dir: Path
) -> dict[str, Any]:
    """Rebuild only the KO / BOTTLER maps of a finished run's gold package.

    For map changes (basemap, colours, filters) after the package was built: the
    CSVs, Excel and deck stay byte-identical, so nothing already uploaded changes.
    The new maps stay in the local mirror; publishing them is a separate decision.
    """
    folder = gold_dir if gold_dir.is_absolute() else PROJECT_ROOT / gold_dir
    if not (folder / "results_ko").is_dir():
        raise SystemExit(f"{gold_dir} is not a gold package folder (no results_ko/)")
    state = app.get_state(_config(thread_id)).values
    if not state:
        raise SystemExit(f"Thread {thread_id} does not exist")
    deps = default_dependencies()
    # The checkpoint returns the graph's own state dict (keys of CleaningState)
    run_state = cast(CleaningState, state)
    maps = deps.gold_package.build_maps(gold_request(deps, run_state, folder))
    return {"status": "done", "thread_id": thread_id, "maps": maps}


def run_sidecars(
    app: CompiledStateGraph[Any, Any, Any, Any],
    thread_id: str,
    gold_dir: Path,
    raw_clients: str | None = None,
) -> dict[str, Any]:
    """Rewrite the ``_metadata.json`` + ``_qa.html`` (QA, destinations, ``vtm``) of a
    finished run's gold package, leaving its data files untouched.

    The package is rebuilt in a temporary folder only to recover its figures; the
    files in ``gold_dir`` (CSV, Excel, maps, deck) are never rewritten. A lineage-only
    sidecar left by older code is kept inside the new one as ``etapa_linaje``. The new
    sidecars stay in the local mirror; replacing them in Azure is a separate decision.

    ``raw_clients``: the original client base, for threads whose validation ran outside
    the graph (``clean-clients``) and so never recorded it (vtm "Path Info Cruda Clientes").
    """
    folder = gold_dir if gold_dir.is_absolute() else PROJECT_ROOT / gold_dir
    if not (folder / "results_ko").is_dir():
        raise SystemExit(f"{gold_dir} is not a gold package folder (no results_ko/)")
    today = folder.name
    if not (today.isdigit() and len(today) == 8):
        raise SystemExit(f"{gold_dir} must end in the package date (yyyymmdd)")
    state = app.get_state(_config(thread_id)).values
    if not state:
        raise SystemExit(f"Thread {thread_id} does not exist")
    deps = default_dependencies()
    run_state = cast(CleaningState, state)
    if raw_clients:
        validation = dict(run_state.get("clients_validation") or {})
        run_state = cast(
            CleaningState,
            {**run_state, "clients_validation": {**validation, "clients_file": raw_clients}},
        )
    prefix = layer_prefix(
        Layer.GOLD,
        run_state.get("country", ""),
        run_state.get("bottler", ""),
        today,
        deps.prospects_template,
    )
    with tempfile.TemporaryDirectory(prefix="gold_sidecars_") as tmp:
        scratch = Path(tmp)
        result = deps.gold_package.build(gold_request(deps, run_state, scratch))

        def here(paths: list[str]) -> list[str]:
            return [str(folder / Path(p).relative_to(scratch)) for p in paths]

        real = result.model_copy(
            update={
                "root": here(result.root),
                "ko": here(result.ko),
                "bottler": here(result.bottler),
            }
        )
    files = [*real.root, *real.ko, *real.bottler]
    missing = [Path(p).name for p in files if not Path(p).is_file()]
    if missing:
        raise SystemExit(f"Not in {gold_dir} (rebuild the package instead): {missing}")
    staged, registry, qa = write_package_sidecars(
        deps, run_state, gold_request(deps, run_state, folder), real, prefix, today
    )
    if not qa["qa_ok"]:
        raise SystemExit(f"Package QA failed, sidecars not written: {qa['checks']}")
    # The package's lineage record goes inside each sidecar, as the graph does now;
    # taken from the thread (not the old sidecar) so a second run gives the same result
    records = [
        StageRecord.model_validate(r)
        for r in run_state.get("lineage") or []
        if r.get("stage") == "stage_gold_package"
    ]
    if records:
        record = records[-1]
        by_name = {Path(o.path).name: o for o in record.outputs}
        resolver = dwh_paths()
        for path in files:
            output = by_name.get(Path(path).name)
            if output is None:
                continue
            target = _sidecar(path)
            meta = json.loads(target.read_text(encoding="utf-8"))
            stage = {**record.model_dump(), "archivo": output.model_dump(exclude_none=True)}
            target.write_text(
                json.dumps(
                    {**meta, STAGE_KEY: resolver.portable(stage)}, ensure_ascii=False, indent=2
                ),
                encoding="utf-8",
            )
    return {
        "status": "done",
        "thread_id": thread_id,
        "sidecars": [p for group in staged.values() for p in group if p not in files],
        "vtm": dwh_paths().portable(registry),
    }


def _sidecar(path: str) -> Path:
    file = Path(path)
    return file.with_name(f"{file.stem}_metadata.json")


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1252; the questions are in Spanish
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")
    # Credentials (AZURE_STORAGE_CONNECTION_STRING) come from the environment or the
    # project's .env; values already in the environment win and nothing is printed
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    # The Azure SDK logs every HTTP request at INFO; keep the agent's own log readable
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    parser = argparse.ArgumentParser(
        prog="cleaning_agent", description=__doc__.split("\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="Start a run; stops at the first question")
    start.add_argument("--thread", default=None)
    resume = sub.add_parser("resume", help="Answer the pending question")
    resume.add_argument("--thread", required=True)
    answer = resume.add_mutually_exclusive_group(required=True)
    answer.add_argument("--answer", help="JSON answer")
    answer.add_argument("--answer-file", help="File with the JSON answer")
    status = sub.add_parser("status", help="Show a run and its pending question")
    status.add_argument("--thread", required=True)
    interactive = sub.add_parser(
        "interactive", help="Ask every question in the terminal"
    )
    interactive.add_argument("--thread", default=None)
    redo = sub.add_parser(
        "redo", help="Re-run a thread from the step after --after (keeps the history)"
    )
    redo.add_argument("--thread", required=True)
    redo.add_argument("--after", required=True, help="Node whose next steps re-run")
    redo.add_argument(
        "--datamatch",
        default=None,
        help='Datamatch step rules as JSON, e.g. {"distancia_match_m": 25, "solo_distancia": true}'
        ' or {"filtrar_a_base": true} when the Front ran with an older client base',
    )
    redo.add_argument(
        "--excluir-estados",
        default=None,
        help='Provinces out of the bottler territory, comma separated (e.g. "Buenos Aires")',
    )
    redo.add_argument(
        "--umbral",
        type=float,
        default=None,
        help="Datamatch cleanup threshold for the redone step (0-1)",
    )
    sub.add_parser("graph", help="Print the graph as Mermaid")
    clean = sub.add_parser(
        "clean-clients",
        help="Paso 1 bottler: valida la base de clientes (canal, coordenadas dentro del país, QA)",
    )
    clean.add_argument("--src", required=True, help="CSV original de clientes")
    clean.add_argument("--country", required=True, help="ISO 2, p. ej. ar")
    clean.add_argument("--bottler", required=True, help="p. ej. andina")
    clean.add_argument("--fecha", help="yyyymmdd de la carpeta destino (hoy por defecto)")
    clean.add_argument(
        "--canal",
        default="todos",
        choices=["todos", "tradicional", "moderno", "ambos"],
        help="todos = no filtra por canal",
    )
    maps = sub.add_parser(
        "maps", help="Rebuild only the maps of a run's gold package (local mirror)"
    )
    maps.add_argument("--thread", required=True)
    maps.add_argument(
        "--gold-dir",
        required=True,
        help="Package folder, e.g. data/gold/ko/ar/andina/prospecting-data/20261111",
    )
    sidecars = sub.add_parser(
        "sidecars",
        help="Rewrite the metadata + QA pages (with vtm) of a run's gold package (local mirror)",
    )
    sidecars.add_argument("--thread", required=True)
    sidecars.add_argument(
        "--gold-dir",
        required=True,
        help="Package folder, e.g. data/gold/ko/ar/andina/prospecting-data/20261123",
    )
    sidecars.add_argument(
        "--clientes-crudos",
        default=None,
        help="Original client base (DWH path) when the thread did not record it",
    )
    args = parser.parse_args(argv)

    if args.command == "sidecars":
        with open_app() as app:
            view = run_sidecars(
                app, _check_thread_id(args.thread), Path(args.gold_dir), args.clientes_crudos
            )
        print(json.dumps(view, ensure_ascii=False, indent=2))
        return 0

    if args.command == "maps":
        with open_app() as app:
            view = run_maps(app, _check_thread_id(args.thread), Path(args.gold_dir))
        print(json.dumps(view, ensure_ascii=False, indent=2))
        return 0

    if args.command == "clean-clients":
        from cleaning_agent.entrypoints.clients_clean import clean_clients_command

        print(json.dumps(clean_clients_command(args), ensure_ascii=False, indent=2))
        return 0

    if args.command == "graph":
        print(build_graph(default_dependencies()).compile().get_graph().draw_mermaid())
        return 0

    thread_id = _check_thread_id(getattr(args, "thread", None) or new_thread_id())
    with open_app() as app:
        try:
            if args.command == "start":
                view = run_start(app, thread_id)
            elif args.command == "resume":
                raw = (
                    args.answer
                    if args.answer is not None
                    else Path(args.answer_file).read_text(encoding="utf-8")
                )
                view = run_resume(app, thread_id, _parse_answer(raw))
            elif args.command == "status":
                view = describe(app, thread_id)
            elif args.command == "redo":
                view = run_redo(
                    app,
                    thread_id,
                    args.after,
                    args.umbral,
                    _parse_answer(args.datamatch) if args.datamatch else None,
                    _split_states(args.excluir_estados),
                )
            else:
                view = run_interactive(app, thread_id)
        except (
            Exception
        ) as exc:  # boundary: report any failure as JSON, keep the thread
            logging.getLogger("cleaning_agent").exception("Run %s failed", thread_id)
            view = {**describe(app, thread_id), "status": "error", "error": str(exc)}
    if view["status"] != "not_found":
        save_progress(view)
    print(json.dumps(view, ensure_ascii=False, indent=2, default=str))
    return 1 if view["status"] in {"error", "failed", "not_found"} else 0

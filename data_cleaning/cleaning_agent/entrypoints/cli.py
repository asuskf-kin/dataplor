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
"""

import argparse
import json
import logging
import secrets
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from cleaning_agent.application.graph.builder import RECURSION_LIMIT, build_graph
from cleaning_agent.application.graph.progress import progress_markdown, step_view
from cleaning_agent.settings import PROJECT_ROOT
from cleaning_agent.wiring import checkpoints_path, default_dependencies

MAX_ANSWER_CHARS = 20_000
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
    sub.add_parser("graph", help="Print the graph as Mermaid")
    args = parser.parse_args(argv)

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

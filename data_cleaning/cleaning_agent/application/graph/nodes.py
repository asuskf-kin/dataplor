"""Graph nodes. Each one has a single, checkable job (see the docstrings).

Interrupt rules that shape this file (docs.langchain.com, "Rules of interrupts"):
- A node re-runs from the top when resumed, so nothing with side effects happens
  before ``interrupt()``: ask nodes only build the payload, then validate.
- ``interrupt()`` is never inside try/except; validation errors loop back through a
  conditional edge, not a ``while``.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.types import interrupt
from pydantic import BaseModel, ValidationError

from cleaning_agent.application.cleaning_catalog import (
    MODULE_NAMES,
    CleaningModule,
    build_module_plan,
    catalog_for,
    supported_countries,
)
from cleaning_agent.application.graph.state import CleaningState
from cleaning_agent.application.ports import (
    AuditPort,
    DatamatchQAPort,
    DatasetPort,
    ExecutiveReportPort,
    LayerStagingPort,
    LineagePort,
    PatternsPort,
    PrefilterPort,
    PriorizacionPort,
    StoragePort,
)
from cleaning_agent.domain.cleaning.step_metrics import analyze_step_drop
from cleaning_agent.domain.lineage import ArtifactRef, StageRecord, now_iso
from cleaning_agent.domain.models import (
    INPUT_MODELS,
    Channel,
    CleaningChoice,
    CleaningMode,
    CleaningType,
    ClientInputs,
    GeojsonInputs,
    IntakeAnswer,
    NoPrefilterInputs,
    OutputDecision,
    OutputPaths,
    PatternsDecision,
    PlanDecision,
    Premise,
    StepMetric,
    blob_location,
    raw_blob_location,
)
from cleaning_agent.domain.patterns_policy import needs_update
from cleaning_agent.observability import CorrelationAdapter

Update = dict[str, Any]


class NodeFn(Protocol):
    """A node as LangGraph types it: the parameter must be named ``state``."""

    def __call__(self, state: CleaningState) -> Update: ...


INTAKE_QUESTION = "Datos de la corrida: país, bottler, canal, premise y Dataplor raw."
CLEANING_QUESTION = "¿Va a limpiar el Dataplor?"
INPUT_STEP = "00_input"
# Errors a pre-filter or module raises for bad data; anything else is a bug and
# must surface with its traceback
DATA_ERRORS = (FileNotFoundError, ValueError, OSError, KeyError)


@dataclass(frozen=True)
class Dependencies:
    """Everything the nodes need from outside, injected (hexagonal ports)."""

    prefilters: Mapping[CleaningMode, PrefilterPort]
    datasets: DatasetPort
    audit: AuditPort
    qa: DatamatchQAPort
    storage: StoragePort
    lineage: LineagePort
    executive_report: ExecutiveReportPort
    priorizacion: PriorizacionPort
    staging: LayerStagingPort
    patterns: PatternsPort
    defaults: Mapping[CleaningMode, dict[str, Any]]
    default_modules: list[int]
    items_to_track: list[str] = field(default_factory=list)
    max_attempts: int = 3
    modules_for: Callable[[str], Mapping[int, CleaningModule]] = catalog_for
    supported_countries: Callable[[], list[str]] = supported_countries
    front_url: str = ""
    # Default container ONLY for the raw Dataplor (not for GeoJSON, clients or uploads)
    raw_container: str = "dataplorraw"
    raw_local_dir: Path = Path("data/raw")
    # Production DWH (user-defined): container, path template and local mirror root
    dwh_container: str = "prospecting-data"
    dwh_path_template: str = "{layer}/ko/{pais}/{bottler}/{fecha}"
    mirror_root: Path = Path("data")
    # Local folder of each run: intermediate steps and the lineage document
    runs_dir: Path = Path("data/runs")
    # Defaults for the Front (datamatch) form and the Azure upload form
    datamatch_defaults: Mapping[str, Any] = field(default_factory=dict)
    upload_defaults: Mapping[str, Any] = field(default_factory=dict)


def _logger(state: CleaningState) -> CorrelationAdapter:
    # The thread id is the run's Correlation ID: it is on every log line
    return CorrelationAdapter(
        logging.getLogger("cleaning_agent"),
        {"correlation_id": state.get("run_id", "-")},
    )


def record_stage(
    deps: Dependencies,
    state: CleaningState,
    stage: str,
    name: str,
    started_at: str,
    inputs: list[ArtifactRef],
    outputs: list[ArtifactRef],
    metrics: Mapping[str, Any] | None = None,
) -> Update:
    """Lineage of one stage: writes its sidecars and returns the state update."""
    record = StageRecord(
        run_id=state["run_id"],
        stage=stage,
        name=name,
        started_at=started_at,
        finished_at=now_iso(),
        code_version=deps.lineage.code_version(),
        inputs=inputs,
        outputs=outputs,
        metrics=dict(metrics or {}),
    )
    return {
        "lineage": [record.model_dump()],
        "sidecars": deps.lineage.write_sidecars(record),
    }


def _catalog(deps: Dependencies, state: CleaningState) -> Mapping[int, CleaningModule]:
    # Chain patterns depend on the run's country, chosen in the intake
    return deps.modules_for(state.get("country") or "")


def _mode(state: CleaningState) -> CleaningMode:
    mode = state.get("mode")
    if mode is None:
        raise ValueError("No cleaning mode in the state: choose_mode did not run")
    return CleaningMode(mode)


def _errors(exc: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(part) for part in err['loc']) or 'answer'}: {err['msg']}"
        for err in exc.errors()
    ]


def _validate[M: BaseModel](model: type[M], answer: object) -> M | list[str]:
    if isinstance(answer, model):
        return answer
    try:
        return model.model_validate(answer)
    except ValidationError as exc:
        return _errors(exc)


def _retry(state: CleaningState, errors: list[str]) -> Update:
    return {"errors": errors, "attempts": state.get("attempts", 0) + 1}


def _ok() -> Update:
    return {"errors": [], "attempts": 0}


def start(state: CleaningState, config: RunnableConfig) -> Update:
    """Done when run_id equals the thread id and the defaults are in the state."""
    run_id = str(config["configurable"]["thread_id"])
    return {
        "run_id": run_id,
        # Fixed at the start so a run resumed the next day keeps its warehouse folder
        "run_date": f"{datetime.now():%Y%m%d}",
        "status": "asking",
        "error": None,
        "attempts": 0,
        "errors": [],
        "cursor": 0,
        "metrics": [],
    }


def make_intake(deps: Dependencies) -> NodeFn:
    def intake(state: CleaningState) -> Update:
        """HITL 1. Done when country (supported ISO 2), bottler, channel, premise and an
        existing raw Dataplor path are known."""
        answer = interrupt(
            {
                "kind": "intake",
                "question": INTAKE_QUESTION,
                # Ask in this order (the user's flow): country, bottler, channel, premise, raw
                "fields": [
                    {
                        "name": "country",
                        "question": "País (ISO 2)",
                        "options": deps.supported_countries(),
                    },
                    {"name": "bottler", "question": "Bottler (embotellador)"},
                    {
                        "name": "channel",
                        "question": "¿Tradicional o moderno?",
                        "options": [c.value for c in Channel],
                    },
                    {
                        "name": "premise",
                        "question": "¿Off premise, on premise o los dos?",
                        "options": [p.value for p in Premise],
                    },
                    {
                        "name": "dataplor_raw",
                        "question": "Path del Dataplor raw (.parquet, part-*.parquet o .csv)",
                    },
                ],
                "defaults": state.get("intake") or {},
                "errors": state.get("errors", []),
            }
        )
        parsed = _validate(IntakeAnswer, answer)
        if isinstance(parsed, list):
            return {
                **_retry(state, parsed),
                "intake": answer if isinstance(answer, dict) else None,
            }
        errors = []
        # Any ISO 2 is valid: missing patterns are created later (check_patterns)
        errors += _check_raw(deps, parsed.dataplor_raw)
        if errors:
            return {**_retry(state, errors), "intake": parsed.model_dump(mode="json")}
        _logger(state).info(
            "Run context: %s / %s / %s / %s",
            parsed.country,
            parsed.bottler,
            parsed.channel.value,
            parsed.premise.value,
        )
        return {
            "intake": parsed.model_dump(mode="json"),
            "country": parsed.country,
            "bottler": parsed.bottler,
            "channel": parsed.channel.value,
            "premise": parsed.premise.value,
            **_ok(),
        }

    return intake


def _check_raw(deps: Dependencies, raw: str) -> list[str]:
    """The raw Dataplor is a blob in ``deps.raw_container`` by default, or a local file."""
    if deps.datasets.exists(raw) or deps.datasets.matches(raw):
        return []
    location = raw_blob_location(raw, deps.raw_container)
    if location is None:
        return [f"dataplor_raw: no local file matches {raw}"]
    if not deps.storage.is_configured():
        return [
            (
                "dataplor_raw: Azure is not configured (AZURE_STORAGE_CONNECTION_STRING "
                "in .env or the environment)"
            )
        ]
    try:
        found = deps.storage.list_blobs(*location)
    except (RuntimeError, OSError) as exc:
        return [f"dataplor_raw: could not list {raw}: {exc}"]
    return [] if found else [f"dataplor_raw: no blob matches {raw}"]


def _progress_writer() -> Callable[[str, int, int], None]:
    """Emits download progress on LangGraph's custom stream (every 5%)."""
    writer = get_stream_writer()
    last: dict[str, int] = {}

    def report(name: str, done: int, total: int) -> None:
        percent = int(done * 100 / total) if total else 0
        if percent - last.get(name, -5) >= 5 or done == total:
            last[name] = percent
            writer(
                {
                    "step": "fetch_raw",
                    "file": name,
                    "done": done,
                    "total": total,
                    "percent": percent,
                }
            )

    return report


def make_fetch_raw(deps: Dependencies) -> NodeFn:
    def fetch_raw(state: CleaningState) -> Update:
        """Done when the raw Dataplor is on local disk (downloaded from its blob if needed)."""
        raw = str((state.get("intake") or {}).get("dataplor_raw", ""))
        location = raw_blob_location(raw, deps.raw_container)
        if location is None or deps.datasets.exists(raw) or deps.datasets.matches(raw):
            return {"raw_local": raw}
        local_dir = (
            deps.raw_local_dir
            / state.get("country", "")
            / bottler_folder(state.get("bottler", ""))
            / "dataplor_raw"
        )
        started = now_iso()
        try:
            files = deps.storage.download(
                *location, local_dir, progress=_progress_writer()
            )
        except (RuntimeError, OSError) as exc:
            _logger(state).error("Raw Dataplor download failed: %s", exc)
            return {"status": "failed", "error": f"Dataplor raw ({raw}): {exc}"}
        raw_local = files[0] if len(files) == 1 else str(local_dir / "*.parquet")
        lineage = record_stage(
            deps,
            state,
            "fetch_raw",
            "Descarga del Dataplor raw",
            started,
            [ArtifactRef(path=raw, blob=f"{location[0]}/{location[1]}")],
            [deps.lineage.describe(f) for f in files],
            {"files": len(files)},
        )
        return {"raw_local": raw_local, **lineage}

    return fetch_raw


def choose_cleaning(state: CleaningState) -> Update:
    """HITL 2. Done when it is known whether (and how) the raw Dataplor is cleaned first."""
    answer = interrupt(
        {
            "kind": "choose_cleaning",
            "question": CLEANING_QUESTION,
            "options": [
                {
                    "clean": True,
                    "type": CleaningType.DISTANCIA.value,
                    "label": "Sí, por distancia: cruzar con el GeoJSON del territorio",
                },
                {
                    "clean": True,
                    "type": CleaningType.CLIENT_BOTTLER.value,
                    "label": "Sí, por client bottler: lo cercano a los clientes del bottler",
                },
                {
                    "clean": False,
                    "label": "No: el Dataplor raw va directo al Pipeline Data clean",
                },
            ],
            "answer_format": {"clean": True, "type": "distancia | client_bottler"},
            "errors": state.get("errors", []),
        }
    )
    parsed = _validate(CleaningChoice, answer)
    if isinstance(parsed, list):
        return _retry(state, parsed)
    _logger(state).info("Cleaning mode chosen: %s", parsed.mode.value)
    return {"mode": parsed.mode.value, **_ok()}


def bottler_folder(bottler: str) -> str:
    return "_".join(bottler.lower().split()) or "bottler"


def form_defaults(
    deps: Dependencies, state: CleaningState, mode: CleaningMode
) -> dict[str, Any]:
    """Config defaults overridden by what the intake already answered."""
    country = state.get("country", "")
    folder = bottler_folder(state.get("bottler", ""))
    raw = state.get("raw_local") or str(
        (state.get("intake") or {}).get("dataplor_raw", "")
    )
    premise = state.get("premise", "")
    defaults = {
        **deps.defaults[mode],
        "raw_csv": f"data/raw/{country}/{folder}/dataplor_cleaned.csv",
        "output_csv": (
            f"data/processed/{country}/{folder}/"
            f"dataplor_final_pipeline_output_{country}_{premise}.csv"
        ),
    }
    if mode == CleaningMode.NINGUNO:
        defaults["raw_csv"] = (
            raw  # no pre-filter: the raw Dataplor is the cleaning input
        )
    else:
        defaults["parquet"] = raw
    return defaults


def _remote_inputs(inputs: OutputPaths) -> dict[str, str]:
    """GeoJSON / client base fields of the form, by name."""
    fields: dict[str, str] = {}
    if isinstance(inputs, GeojsonInputs):
        fields["geojson"] = inputs.geojson
    if isinstance(inputs, ClientInputs):
        fields["clients_csv"] = inputs.clients_csv
    return fields


def _check_files(inputs: OutputPaths, deps: Dependencies) -> list[str]:
    """Deterministic existence checks (Pydantic only checks the format).

    GeoJSON and client base may be local files or ``<container>/<blob>`` in Azure.
    """
    datasets = deps.datasets
    errors: list[str] = []
    for name, path in _remote_inputs(inputs).items():
        if datasets.exists(path):
            continue
        location = blob_location(path)
        if location is None:
            errors.append(f"{name}: file not found {path}")
        elif not deps.storage.is_configured():
            errors.append(
                f"{name}: {path} looks like a blob but Azure is not configured"
            )
        else:
            try:
                if not deps.storage.list_blobs(*location):
                    errors.append(f"{name}: not found locally or in Azure ({path})")
            except (RuntimeError, OSError) as exc:
                errors.append(f"{name}: could not list {path}: {exc}")
    # Mode 'ninguno' reads raw_csv; the other modes write it
    if isinstance(inputs, NoPrefilterInputs) and not (
        datasets.exists(inputs.raw_csv) or datasets.matches(inputs.raw_csv)
    ):
        errors.append(f"raw_csv: file not found {inputs.raw_csv}")
    return errors


def make_fetch_inputs(deps: Dependencies) -> NodeFn:
    def fetch_inputs(state: CleaningState) -> Update:
        """Done when the GeoJSON / client base given as blobs are on local disk."""
        mode = _mode(state)
        inputs = INPUT_MODELS[mode].model_validate(state["inputs"])
        local_dir = (
            deps.raw_local_dir
            / state.get("country", "")
            / bottler_folder(state.get("bottler", ""))
            / "insumos"
        )
        updated = dict(state["inputs"] or {})
        sources: list[ArtifactRef] = []
        outputs: list[ArtifactRef] = []
        started = now_iso()
        for name, path in _remote_inputs(inputs).items():
            location = None if deps.datasets.exists(path) else blob_location(path)
            if location is None:
                continue
            try:
                files = deps.storage.download(*location, local_dir)
            except (RuntimeError, OSError) as exc:
                _logger(state).error("Download of %s failed: %s", name, exc)
                return {"status": "failed", "error": f"{name} ({path}): {exc}"}
            updated[name] = files[0]
            sources.append(ArtifactRef(path=path, blob=f"{location[0]}/{location[1]}"))
            outputs += [deps.lineage.describe(f) for f in files]
        if not sources:
            return {}
        lineage = record_stage(
            deps,
            state,
            "fetch_inputs",
            "Descarga de insumos (GeoJSON / clientes)",
            started,
            sources,
            outputs,
            {"files": len(outputs)},
        )
        return {"inputs": updated, **lineage}

    return fetch_inputs


def make_collect_inputs(deps: Dependencies) -> NodeFn:
    def collect_inputs(state: CleaningState) -> Update:
        """HITL 2. Done when ``inputs`` validates against the mode model and its files exist."""
        mode = _mode(state)
        model = INPUT_MODELS[mode]
        answer = interrupt(
            {
                "kind": "collect_inputs",
                "mode": mode.value,
                "question": f"Datos para el modo '{mode.value}': confirma o cambia las rutas.",
                # The previous (invalid) answer wins over config defaults on a retry
                "defaults": state.get("inputs") or form_defaults(deps, state, mode),
                "schema": model.model_json_schema(),
                "errors": state.get("errors", []),
            }
        )
        parsed = _validate(model, answer)
        if isinstance(parsed, list):
            return {
                **_retry(state, parsed),
                "inputs": answer if isinstance(answer, dict) else None,
            }
        missing = _check_files(parsed, deps)
        if missing:
            return {**_retry(state, missing), "inputs": parsed.model_dump()}
        return {"inputs": parsed.model_dump(), **_ok()}

    return collect_inputs


def make_confirm_plan(deps: Dependencies) -> NodeFn:
    def confirm_plan(state: CleaningState) -> Update:
        """HITL 3. Done when the plan is approved with a valid module list, or cancelled."""
        proposed, notes = build_module_plan(
            state.get("modules") or deps.default_modules
        )
        answer = interrupt(
            {
                "kind": "confirm_plan",
                "question": "¿Apruebas este plan de limpieza?",
                "country": state.get("country"),
                "bottler": state.get("bottler"),
                "channel": state.get("channel"),
                "premise": state.get("premise"),
                "mode": state["mode"],
                "inputs": state["inputs"],
                "modules": [{"id": m, "name": MODULE_NAMES[m]} for m in proposed],
                "available_modules": MODULE_NAMES,
                "notes": notes,
                "answer_format": {"approved": True, "modules": proposed, "note": None},
                "errors": state.get("errors", []),
            }
        )
        parsed = _validate(PlanDecision, answer)
        if isinstance(parsed, list):
            return _retry(state, parsed)
        if not parsed.approved:
            _logger(state).info("Plan rejected by the user")
            return {"status": "cancelled", "note": parsed.note, **_ok()}
        try:
            modules, notes = build_module_plan(parsed.modules or proposed)
        except ValueError as exc:
            return _retry(state, [f"modules: {exc}"])
        return {
            "status": "planned",
            "modules": modules,
            "plan_notes": notes,
            "note": parsed.note,
            **_ok(),
        }

    return confirm_plan


def make_prefilter(deps: Dependencies) -> NodeFn:
    def prefilter(state: CleaningState) -> Update:
        """Done when the raw Parquet was narrowed into inputs.raw_csv (or the run failed)."""
        mode = _mode(state)
        inputs = INPUT_MODELS[mode].model_validate(state["inputs"])
        log = _logger(state)
        log.info("Running pre-filter '%s'", mode.value)
        started = now_iso()
        try:
            result = deps.prefilters[mode].run(inputs, state["run_id"])
        except DATA_ERRORS as exc:
            log.error("Pre-filter failed: %s", exc)
            return {"status": "failed", "error": f"Pre-filter '{mode.value}': {exc}"}
        # The raw Parquet is not copied to the warehouse: its hash in the lineage
        # is what proves which export was used
        sources = deps.datasets.matches(str(getattr(inputs, "parquet", "")))
        reference = getattr(inputs, "geojson", None) or getattr(
            inputs, "clients_csv", None
        )
        kept = result.counts.get("inside_territory", result.counts.get("near_client"))
        lineage = record_stage(
            deps,
            state,
            "prefilter",
            f"Pre-filtro {mode.value}",
            started,
            [deps.lineage.describe(path) for path in sources]
            + ([deps.lineage.describe(str(reference))] if reference else []),
            [deps.lineage.describe(result.output_csv, rows=kept)],
            result.counts,
        )
        return {"status": "running", "prefilter": result.model_dump(), **lineage}

    return prefilter


def make_load_input(deps: Dependencies) -> NodeFn:
    def load_input(state: CleaningState) -> Update:
        """Done when the input CSV is saved as step 00 of this run."""
        inputs = state["inputs"] or {}
        raw_csv = str(inputs["raw_csv"])
        log = _logger(state)
        try:
            df = deps.datasets.load_input(raw_csv)
        except DATA_ERRORS as exc:
            log.error("Could not read %s: %s", raw_csv, exc)
            return {"status": "failed", "error": f"Input CSV: {exc}"}
        deps.datasets.clear_previous_drops()
        items = list(deps.items_to_track)
        log.info("Input loaded: %s rows from %s", f"{df.height:,}", raw_csv)
        return {
            "status": "running",
            "items_to_track": items,
            "audit_file": deps.audit.start(items),
            "input_rows": df.height,
            "current_path": deps.datasets.save_step(state["run_id"], INPUT_STEP, df),
            "cursor": 0,
        }

    return load_input


def make_run_module(deps: Dependencies) -> NodeFn:
    def run_module(state: CleaningState) -> Update:
        """Done when modules[cursor] wrote its step file and appended one metric."""
        module = _catalog(deps, state)[state["modules"][state["cursor"]]]
        log = _logger(state)
        before = deps.datasets.load_step(str(state["current_path"]))
        log.info("Executing %s on %s rows", module.name, f"{before.height:,}")
        outcome = module.run(before, state.get("items_to_track", []))

        path = deps.datasets.save_step(state["run_id"], module.file_stem, outcome.df)
        try:
            deps.datasets.save_dropped(
                before, outcome.df, module.file_stem, outcome.dropped
            )
        except DATA_ERRORS as exc:
            # The drop CSV is an audit aid; losing it must not lose the run
            log.warning("Could not save drops for %s: %s", module.name, exc)
        if outcome.report:
            deps.audit.write_step(
                state.get("audit_file"),
                f"MODULE {module.module_id} ({module.name})",
                outcome.report,
            )
        drop = analyze_step_drop(before, outcome.df, module.name)
        metric = StepMetric(
            module_id=module.module_id,
            step_name=module.name,
            rows_before=before.height,
            rows_after=outcome.df.height,
            top_dropped=[(str(name), int(freq)) for name, freq in drop["top_dropped"]],
        )
        log.info(
            "%s: %s -> %s rows",
            module.name,
            f"{before.height:,}",
            f"{outcome.df.height:,}",
        )
        return {
            "current_path": path,
            "cursor": state["cursor"] + 1,
            "items_to_track": outcome.items_to_track,
            "metrics": [metric.model_dump()],
        }

    return run_module


def make_finalize(deps: Dependencies) -> NodeFn:
    def finalize(state: CleaningState) -> Update:
        """Done when the audit is closed, the HTML report exists and a summary is ready."""
        final_df = deps.datasets.load_step(str(state["current_path"]))
        deps.audit.finish(
            state.get("audit_file"), final_df, state.get("items_to_track", [])
        )
        metrics = [StepMetric.model_validate(m) for m in state.get("metrics", [])]
        report = deps.audit.html_report(metrics)
        summary = {
            "prefilter": state.get("prefilter"),
            "input_rows": state.get("input_rows", 0),
            "final_rows": final_df.height,
            "steps": [
                {"module": m.step_name, "dropped": m.dropped, "remaining": m.rows_after}
                for m in metrics
            ],
        }
        return {
            "status": "awaiting_approval",
            "report_path": str(report) if report else None,
            "summary": summary,
        }

    return finalize


def approve_output(state: CleaningState) -> Update:
    """HITL 4. Done when the human approved (-> publish) or rejected the result."""
    answer = interrupt(
        {
            "kind": "approve_output",
            "question": "¿Publico el CSV limpio?",
            "summary": state.get("summary"),
            "html_report": state.get("report_path"),
            "output_csv": (state.get("inputs") or {}).get("output_csv"),
            "answer_format": {"approved": True, "note": None},
            "errors": state.get("errors", []),
        }
    )
    parsed = _validate(OutputDecision, answer)
    if isinstance(parsed, list):
        return _retry(state, parsed)
    if not parsed.approved:
        _logger(state).info("Output rejected by the user")
        return {"status": "rejected", "note": parsed.note, **_ok()}
    return {"note": parsed.note, **_ok()}


def make_publish(deps: Dependencies) -> NodeFn:
    def publish(state: CleaningState) -> Update:
        """Done when the final CSV is written to inputs.output_csv (rerun-safe: overwrites)."""
        started = now_iso()
        df = deps.datasets.load_step(str(state["current_path"]))
        output = deps.datasets.publish(df, str((state["inputs"] or {})["output_csv"]))
        _logger(state).info("Published %s rows -> %s", f"{df.height:,}", output)
        lineage = record_stage(
            deps,
            state,
            "pipeline_data_clean",
            "Pipeline Data clean (módulos "
            + ", ".join(map(str, state["modules"]))
            + ")",
            started,
            [
                deps.lineage.describe(
                    str((state["inputs"] or {})["raw_csv"]),
                    rows=state.get("input_rows"),
                )
            ],
            [deps.lineage.describe(output, rows=df.height)],
            {
                "steps": (state.get("summary") or {}).get("steps", []),
                "approved_note": state.get("note"),
            },
        )
        return {"status": "published", "output_path": output, **lineage}

    return publish


def make_check_patterns(deps: Dependencies) -> NodeFn:
    def check_patterns(state: CleaningState) -> Update:
        """Done when it is known whether the country's patterns must be created/updated."""
        status = deps.patterns.status(state.get("country", ""))
        must, reason = needs_update(status, datetime.now().date())
        _logger(state).info("Patterns %s: %s", state.get("country"), reason)
        return {
            "patterns": {
                **status.model_dump(),
                "needs_update": must,
                "reason": reason,
            }
        }

    return check_patterns


def make_update_patterns(deps: Dependencies) -> NodeFn:
    def update_patterns(state: CleaningState) -> Update:
        """HITL. Done when the person approved the new/updated patterns file (re-validated)."""
        info = state.get("patterns") or {}
        country = state.get("country", "")
        today = datetime.now().date().isoformat()
        answer = interrupt(
            {
                "kind": "update_patterns",
                "question": f"Patrones de cadenas para '{country}': {info.get('reason')}",
                "country": country,
                "file": str(deps.patterns.path(country)),
                "exists": info.get("exists"),
                "last_update": info.get("updated"),
                "instructions": (
                    "Claude Code: crea o actualiza el archivo con CHAIN_REGEX (cadenas y franquicias "
                    "reconocidas del país: supermercados, conveniencia, farmacias, comida rápida...) "
                    f'y PATTERNS_UPDATED = "{today}". Muestra el diff al usuario y espera su OK '
                    'antes de responder {"approved": true}.'
                ),
                "answer_format": {"approved": True, "note": None},
                "errors": state.get("errors", []),
            }
        )
        parsed = _validate(PatternsDecision, answer)
        if isinstance(parsed, list):
            return _retry(state, parsed)
        if not parsed.approved:
            if info.get("exists"):
                return {
                    "warnings": [
                        f"Patrones de {country} sin actualizar: {info.get('reason')}"
                    ],
                    **_ok(),
                }
            return {
                "status": "failed",
                "error": f"No hay patrones para '{country}'",
                **_ok(),
            }
        # The file was edited by Claude Code: check it really is usable and fresh
        status = deps.patterns.status(country)
        must, reason = needs_update(status, datetime.now().date())
        try:
            chains = deps.patterns.reload(country) if status.exists else 0
        except (SyntaxError, ImportError, ValueError) as exc:
            return _retry(state, [f"patterns file does not load: {exc}"])
        if must or chains == 0:
            return _retry(
                state, [f"patterns still not usable: {reason}; CHAIN_REGEX={chains}"]
            )
        return {
            "patterns": {
                **status.model_dump(),
                "needs_update": False,
                "chains": chains,
            },
            "note": parsed.note,
            **_ok(),
        }

    return update_patterns

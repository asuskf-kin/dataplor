"""Delivery nodes, after the cleaned CSV is published locally:

    ¿Datamatch?* --sí--> Front (datamatch)* -> QA explore -> thresholds* -> QA run --+
         |                                                                         v
         +---------------------------no------------------------------> confirm_upload* -> upload -> Fin

Datamatch itself is run by a person in the Kin web app (the "Front"); the graph
waits for its output file and then runs the QA. Nothing leaves the machine until
the upload is explicitly approved. Same interrupt rules as nodes.py.
"""

from datetime import datetime

from langgraph.types import interrupt

from cleaning_agent.application.graph.nodes import (
    Dependencies,
    NodeFn,
    Update,
    _logger,
    _ok,
    _retry,
    _validate,
    bottler_folder,
    layer_dir,
    record_stage,
)
from cleaning_agent.application.graph.state import CleaningState
from cleaning_agent.application.graph.warehouse_nodes import (
    check_remote,
    with_dwh_container,
)
from cleaning_agent.domain.lineage import (
    LINEAGE_FILE,
    StageRecord,
    build_lineage_document,
    now_iso,
)
from cleaning_agent.domain.models import (
    DatamatchInputs,
    ThresholdDecision,
    UploadDecision,
)
from cleaning_agent.domain.warehouse import Layer

# The QA adapter raises RuntimeError subclasses; files/config problems are OSError/ValueError
DELIVERY_ERRORS = (RuntimeError, OSError, ValueError)


def _bottler(state: CleaningState) -> str:
    return bottler_folder(state.get("bottler", ""))


def make_front_datamatch(deps: Dependencies) -> NodeFn:
    def front_datamatch(state: CleaningState) -> Update:
        """HITL 6. Done when the Datamatch output from the Front and the client base exist,
        or the person chose to skip Datamatch ({"skip": true})."""
        fields = DatamatchInputs.model_fields
        defaults = {
            "datamatch_file": "",
            "client_name": _bottler(state),
            # datamatch_defaults also holds the QA thresholds: keep only this form's fields
            **{k: v for k, v in deps.datamatch_defaults.items() if k in fields},
            **(state.get("datamatch") or {}),
        }
        answer = interrupt(
            {
                "kind": "front_datamatch",
                "question": (
                    "Sube el CSV limpio al Front, corre Datamatch y descarga su resultado. "
                    "Luego indica dónde quedó el archivo. Si no vas a hacer Datamatch, "
                    "responde skip_answer."
                ),
                "front_url": deps.front_url,
                "file_to_upload": state.get("output_path"),
                "default_container": deps.dwh_container,
                "defaults": defaults,
                "schema": DatamatchInputs.model_json_schema(),
                "skip_answer": {"skip": True},
                "errors": state.get("errors", []),
            }
        )
        # Datamatch is optional (user, 2026-11-11): without it priorización runs on the
        # cleaned CSV, which still holds the bottler's known clients
        if isinstance(answer, dict) and answer.get("skip") is True:
            _logger(state).warning("Datamatch skipped by the person")
            return {"datamatch_skipped": True, **_ok()}
        if isinstance(answer, dict):
            answer = {**defaults, **answer, "country": state.get("country", "")}
        parsed = _validate(DatamatchInputs, answer)
        if isinstance(parsed, list):
            return {
                **_retry(state, parsed),
                "datamatch": answer if isinstance(answer, dict) else None,
            }
        # Local file or blob; DWH paths without a container go to prospecting-data
        parsed = parsed.model_copy(
            update={
                "datamatch_file": with_dwh_container(deps, parsed.datamatch_file),
                "clients_file": with_dwh_container(deps, parsed.clients_file),
                "step_json": with_dwh_container(deps, parsed.step_json)
                if parsed.step_json
                else "",
            }
        )
        missing = check_remote(
            deps, "datamatch_file", parsed.datamatch_file
        ) + check_remote(deps, "clients_file", parsed.clients_file)
        if parsed.step_json:
            missing += check_remote(deps, "step_json", parsed.step_json)
        if missing:
            return {**_retry(state, missing), "datamatch": parsed.model_dump()}
        return {"datamatch": parsed.model_dump(), **_ok()}

    return front_datamatch


def make_qa_explore(deps: Dependencies) -> NodeFn:
    def qa_explore(state: CleaningState) -> Update:
        """Done when the QA threshold report (HTML, on-brand) is in the gold mirror with
        its metadata, or the run failed."""
        inputs = DatamatchInputs.model_validate(state["datamatch"])
        started = now_iso()
        try:
            # The QA deliverables belong to gold (user, 2026-11-11)
            result = deps.qa.explore(
                inputs, state["run_id"], layer_dir(deps, state, Layer.GOLD)
            )
        except DELIVERY_ERRORS as exc:
            _logger(state).error("QA explore failed: %s", exc)
            return {"status": "failed", "error": f"QA datamatch (explore): {exc}"}
        lineage = record_stage(
            deps,
            state,
            "qa_explore",
            "QA Datamatch: reporte de thresholds",
            started,
            # Client base: only its path is recorded in the run, never its rows
            [deps.lineage.describe(inputs.datamatch_file)],
            [deps.lineage.describe(result.report_html)],
            {"client_name": inputs.client_name},
        )
        return {"qa_report": result.report_html, **lineage}

    return qa_explore


def make_choose_thresholds(deps: Dependencies) -> NodeFn:
    def choose_thresholds(state: CleaningState) -> Update:
        """HITL 7. Done when match <= super_match, both in [0, 1]."""
        defaults = state.get("thresholds") or dict(
            deps.datamatch_defaults.get("thresholds", {})
        )
        answer = interrupt(
            {
                "kind": "qa_thresholds",
                "question": "Revisa el reporte de thresholds del QA y fija match / super_match.",
                "qa_report": state.get("qa_report"),
                "defaults": defaults,
                "answer_format": {"match": 0.71, "super_match": 0.8},
                "errors": state.get("errors", []),
            }
        )
        if isinstance(answer, dict):
            answer = {**defaults, **answer}
        parsed = _validate(ThresholdDecision, answer)
        if isinstance(parsed, list):
            return _retry(state, parsed)
        return {"thresholds": parsed.model_dump(), **_ok()}

    return choose_thresholds


def make_qa_run(deps: Dependencies) -> NodeFn:
    def qa_run(state: CleaningState) -> Update:
        """Done when the QA wrote the final Datamatch CSVs, or the run failed."""
        inputs = DatamatchInputs.model_validate(state["datamatch"])
        thresholds = ThresholdDecision.model_validate(state["thresholds"])
        try:
            result = deps.qa.run(
                inputs,
                state["run_id"],
                thresholds.match,
                thresholds.super_match,
                layer_dir(deps, state, Layer.GOLD),
            )
        except DELIVERY_ERRORS as exc:
            _logger(state).error("QA run failed: %s", exc)
            return {"status": "failed", "error": f"QA datamatch (run): {exc}"}
        return {"qa_outputs": result.files}

    return qa_run


def _deliverables(state: CleaningState) -> list[str]:
    files = [str(state["output_path"])] if state.get("output_path") else []
    return files + list(state.get("qa_outputs") or [])


def make_confirm_upload(deps: Dependencies) -> NodeFn:
    def confirm_upload(state: CleaningState) -> Update:
        """HITL 8. Done when the upload target is approved (and storage is configured) or declined."""
        template = str(
            deps.upload_defaults.get(
                "blob_prefix", "prospeccion/{country}/{bottler}/{date}"
            )
        )
        defaults = {
            "container": str(deps.upload_defaults.get("container", "")),
            "blob_prefix": template.format(
                country=state.get("country", ""),
                bottler=_bottler(state),
                date=f"{datetime.now():%Y%m%d}",
            ),
            **(state.get("upload_target") or {}),
        }
        answer = interrupt(
            {
                "kind": "confirm_upload",
                "question": "¿Guardo estos archivos en Azure?",
                "files": _deliverables(state),
                "defaults": defaults,
                "storage_configured": deps.storage.is_configured(),
                "answer_format": {
                    "approved": True,
                    "container": "<container>",
                    "blob_prefix": "<ruta>",
                },
                "errors": state.get("errors", []),
            }
        )
        if isinstance(answer, dict):
            answer = {**defaults, **answer}
        parsed = _validate(UploadDecision, answer)
        if isinstance(parsed, list):
            return {
                **_retry(state, parsed),
                "upload_target": answer if isinstance(answer, dict) else None,
            }
        if not parsed.approved:
            _logger(state).info("Upload to Azure declined; deliverables stay local")
            return {"status": "kept_local", "note": parsed.note, **_ok()}
        if not deps.storage.is_configured():
            return _retry(
                state,
                [
                    (
                        "Azure is not configured: set AZURE_STORAGE_ACCOUNT_URL (or "
                        "AZURE_STORAGE_CONNECTION_STRING) and answer again"
                    )
                ],
            )
        return {
            "upload_target": {
                "container": parsed.container,
                "blob_prefix": parsed.blob_prefix,
            },
            **_ok(),
        }

    return confirm_upload


def make_upload(deps: Dependencies) -> NodeFn:
    def upload(state: CleaningState) -> Update:
        """Done when every deliverable is in Azure (overwrite: rerun-safe), or the run failed."""
        target = state["upload_target"] or {}
        try:
            result = deps.storage.upload(
                _deliverables(state), target["container"], target["blob_prefix"]
            )
        except DELIVERY_ERRORS as exc:
            _logger(state).error("Upload failed: %s", exc)
            return {"status": "failed", "error": f"Azure upload: {exc}"}
        return {"status": "uploaded", "uploaded": result.uploaded}

    return upload


def make_executive_report(deps: Dependencies) -> NodeFn:
    def executive_report(state: CleaningState) -> Update:
        """Done when the executive report (HTML, PDF, Excel) exists, or a warning explains why not.

        A report failure never loses the cleaned data: it is logged and listed in the
        lineage's 'por_verificar'.
        """
        started = now_iso()
        inputs = state.get("inputs") or {}
        try:
            outcome = deps.executive_report.generate(
                str(inputs["raw_csv"]),
                str(inputs.get("output_csv") or state["output_path"]),
                state.get("country", ""),
                state.get("bottler", ""),
                state.get("premise", ""),
                state["run_id"],
                # Every report file is a silver deliverable, the Excel included; gold
                # gets a copy of the Excel + metadata later (user, 2026-11-10)
                layer_dir(deps, state, Layer.SILVER),
                layer_dir(deps, state, Layer.SILVER),
            )
        except DELIVERY_ERRORS + (KeyError,) as exc:
            _logger(state).warning("Executive report failed: %s", exc)
            return {"warnings": [f"Reporte ejecutivo no generado: {exc}"]}
        lineage = record_stage(
            deps,
            state,
            "executive_report",
            "Reporte ejecutivo (ex report.ipynb)",
            started,
            [deps.lineage.describe(str(state["output_path"]))],
            [deps.lineage.describe(path) for path in outcome.files],
            outcome.summary,
        )
        update: Update = {
            "report_files": outcome.files,
            "report_summary": outcome.summary,
            **lineage,
        }
        pending = state.get("pending_upload") or {}
        if pending.get("layer") == Layer.SILVER.value:
            # The silver upload is the whole silver mirror folder (cleaned parquet,
            # drop report, executive HTML/PDF, channel CSV and their metadata)
            listed = deps.staging.list_files(layer_dir(deps, state, Layer.SILVER))
            raw_files = pending.get("files")
            files = [str(f) for f in raw_files] if isinstance(raw_files, list) else []
            update["pending_upload"] = {
                **pending,
                "files": files + [f for f in listed if f not in files],
            }
        return update

    return executive_report


def make_build_lineage(deps: Dependencies) -> NodeFn:
    def build_lineage(state: CleaningState) -> Update:
        """Done when the run's lineage document (only THIS run's stages) is on disk."""
        records = [StageRecord.model_validate(r) for r in state.get("lineage", [])]
        run = {
            "run_id": state.get("run_id"),
            "run_date": state.get("run_date"),
            "country": state.get("country"),
            "bottler": state.get("bottler"),
            "channel": state.get("channel"),
            "premise": state.get("premise"),
            "mode": state.get("mode"),
            "modules": state.get("modules"),
            "status": state.get("status"),
            "code_version": deps.lineage.code_version(),
        }
        document = build_lineage_document(records, run, list(state.get("warnings", [])))
        path = deps.lineage.write_document(
            document, deps.runs_dir / state["run_id"] / LINEAGE_FILE
        )
        return {"lineage_path": path}

    return build_lineage

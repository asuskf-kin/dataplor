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
    record_stage,
)
from cleaning_agent.application.graph.state import CleaningState
from cleaning_agent.domain.lineage import (
    LINEAGE_FILE,
    StageRecord,
    build_lineage_document,
    now_iso,
)
from cleaning_agent.domain.models import (
    DatamatchChoice,
    DatamatchInputs,
    ThresholdDecision,
    UploadDecision,
)

# The QA adapter raises RuntimeError subclasses; files/config problems are OSError/ValueError
DELIVERY_ERRORS = (RuntimeError, OSError, ValueError)


def _bottler(state: CleaningState) -> str:
    return bottler_folder(state.get("bottler", ""))


def ask_datamatch(state: CleaningState) -> Update:
    """HITL 5. Done when run_datamatch is True or False."""
    answer = interrupt(
        {
            "kind": "ask_datamatch",
            "question": "¿Hacemos Datamatch con este resultado?",
            "output_csv": state.get("output_path"),
            "answer_format": {"run_datamatch": True},
            "errors": state.get("errors", []),
        }
    )
    parsed = _validate(DatamatchChoice, answer)
    if isinstance(parsed, list):
        return _retry(state, parsed)
    return {"run_datamatch": parsed.run_datamatch, **_ok()}


def make_front_datamatch(deps: Dependencies) -> NodeFn:
    def front_datamatch(state: CleaningState) -> Update:
        """HITL 6. Done when the Datamatch output from the Front and the client base exist."""
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
                    "Luego indica dónde quedó el archivo."
                ),
                "front_url": deps.front_url,
                "file_to_upload": state.get("output_path"),
                "defaults": defaults,
                "schema": DatamatchInputs.model_json_schema(),
                "errors": state.get("errors", []),
            }
        )
        if isinstance(answer, dict):
            answer = {**defaults, **answer, "country": state.get("country", "")}
        parsed = _validate(DatamatchInputs, answer)
        if isinstance(parsed, list):
            return {
                **_retry(state, parsed),
                "datamatch": answer if isinstance(answer, dict) else None,
            }
        missing = [
            f"{name}: file not found {path}"
            for name, path in (
                ("datamatch_file", parsed.datamatch_file),
                ("clients_file", parsed.clients_file),
            )
            if not deps.datasets.exists(path)
        ]
        if missing:
            return {**_retry(state, missing), "datamatch": parsed.model_dump()}
        return {"datamatch": parsed.model_dump(), **_ok()}

    return front_datamatch


def make_qa_explore(deps: Dependencies) -> NodeFn:
    def qa_explore(state: CleaningState) -> Update:
        """Done when the QA threshold report (HTML) exists, or the run failed."""
        inputs = DatamatchInputs.model_validate(state["datamatch"])
        try:
            result = deps.qa.explore(inputs, state["run_id"])
        except DELIVERY_ERRORS as exc:
            _logger(state).error("QA explore failed: %s", exc)
            return {"status": "failed", "error": f"QA datamatch (explore): {exc}"}
        return {"qa_report": result.report_html}

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
                inputs, state["run_id"], thresholds.match, thresholds.super_match
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
                str(state["output_path"]),
                state.get("country", ""),
                state.get("bottler", ""),
                state.get("premise", ""),
                state["run_id"],
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
        return {
            "report_files": outcome.files,
            "report_summary": outcome.summary,
            **lineage,
        }

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

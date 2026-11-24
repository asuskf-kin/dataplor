"""QA de la prospección, después del último paso del Datamatch (user, 2026-11-23).

    next_datamatch_step (done) -> prepare_prospection_qa -> prospection_qa_review*
        -> build_prospection_qa -> [confirm_false_negatives*] -> stage_prospects

``prospection_qa_review`` lo contesta Claude Code (cruce de categorías, categorías que no
venden bebidas y el benchmark de mercado con búsqueda web); ``confirm_false_negatives`` lo
decide la persona: si los falsos negativos salen de los prospectos. El QA nunca frena la
prospección: si falla, queda un aviso y se sigue con los prospectos como estaban.

Los archivos con nombres o coordenadas de clientes (mapas, falsos negativos, no_match
enriquecido) quedan solo en el espejo local; solo el reporte agregado se sube.
"""

import json
from pathlib import Path
from typing import Any

import polars as pl
from langgraph.types import interrupt

from cleaning_agent.application.graph.nodes import (
    Dependencies,
    NodeFn,
    Update,
    _logger,
    _ok,
    _retry,
    _validate,
    record_stage,
)
from cleaning_agent.application.graph.state import CleaningState
from cleaning_agent.application.graph.warehouse_nodes import (
    cleaned_dataplor,
    loop_match_files,
)
from cleaning_agent.domain.lineage import ArtifactRef, now_iso
from cleaning_agent.domain.models import (
    FalseNegativesDecision,
    ProspectionQaPrepared,
    ProspectionQaReview,
)
from cleaning_agent.domain.warehouse import Layer, layer_prefix

QA_FOLDER = "prospection_qa"
# Front JSON keys -> the columns the QA reads (when the step JSON is missing)
DEFAULT_CLIENT_COLS = {
    "id": "pos_id",
    "name": "pos_name",
    "latitude": "pos_latitude",
    "longitude": "pos_longitude",
}
DEFAULT_DATAPLOR_COLS = {
    "id": "dataplor_id",
    "name": "name",
    "latitude": "latitude",
    "longitude": "longitude",
}
QA_ERRORS = (ValueError, OSError, RuntimeError, KeyError, pl.exceptions.PolarsError)


def qa_base(deps: Dependencies, state: CleaningState) -> str:
    """Silver qa_process folder of the cycle (where the cycle Excel lives)."""
    return layer_prefix(
        Layer.SILVER,
        state.get("country", ""),
        state.get("bottler", ""),
        str(state.get("qa_process_date", "")),
        deps.qa_process_template,
    )


def _front_columns(deps: Dependencies, state: CleaningState) -> tuple[dict[str, str], dict[str, str]]:
    """Client and Dataplor columns from the first step's Front JSON (as the Front read them)."""
    history = state.get("datamatch_history") or []
    client, dataplor = dict(DEFAULT_CLIENT_COLS), dict(DEFAULT_DATAPLOR_COLS)
    if not history:
        return client, dataplor
    step = str(history[0].get("paso", ""))
    path = deps.mirror_root / qa_base(deps, state) / step / f"{step}.json"
    if not path.is_file():
        return client, dataplor
    params: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    for target, section in ((client, "client"), (dataplor, "options")):
        columns = (params.get(section) or {}).get("columns") or {}
        target.update({k: str(v) for k, v in columns.items() if k in target and v})
    return client, dataplor


def _skip(reason: str) -> Update:
    return {"prospection_qa": {"skipped": True, "reason": reason}}


def make_prepare_prospection_qa(deps: Dependencies) -> NodeFn:
    def prepare_prospection_qa(state: CleaningState) -> Update:
        """Done when match / no_match, the false negatives and the categories to review
        are in the local mirror, or the QA was skipped (no port, no steps, an error)."""
        history = [dict(h) for h in state.get("datamatch_history") or []]
        if deps.prospection_qa is None or not history:
            return _skip("sin pasos de Datamatch" if deps.prospection_qa else "QA no configurado")
        client_cols, dataplor_cols = _front_columns(deps, state)
        out_dir = deps.mirror_root / qa_base(deps, state) / QA_FOLDER
        try:
            prepared = deps.prospection_qa.prepare(
                cleaned_dataplor(state),
                loop_match_files(deps, state),
                [str(s) for s in state.get("excluded_states") or []],
                # The full base: the one given to the first step, before any reduction
                str(history[0]["clients_file"]),
                client_cols,
                dataplor_cols,
                out_dir,
            )
        except QA_ERRORS as exc:
            _logger(state).warning("Prospection QA skipped: %s", exc)
            return {
                **_skip(str(exc)),
                "warnings": [f"QA de prospección no corrió: {exc}"],
            }
        _logger(state).info(
            "Prospection QA: %d false negatives among %d prospects",
            prepared.mistakes,
            prepared.no_match,
        )
        return {
            "prospection_qa": {
                "prepared": prepared.model_dump(),
                "dataplor_cols": dataplor_cols,
                "started": now_iso(),
            }
        }

    return prepare_prospection_qa


def make_prospection_qa_review(deps: Dependencies) -> NodeFn:
    def prospection_qa_review(state: CleaningState) -> Update:
        """HITL (Claude Code). Done when the category crosswalk, the non-beverage
        categories and the market benchmark are known (any of them may be empty)."""
        info = dict(state.get("prospection_qa") or {})
        prepared = ProspectionQaPrepared.model_validate(info["prepared"])
        total = prepared.match + prepared.no_match
        answer = interrupt(
            {
                "kind": "prospection_qa_review",
                "question": (
                    "QA de prospección: cruza las categorías de Dataplor con las de la base "
                    "de clientes, marca las que no venden bebidas y busca la penetración de "
                    "Coca-Cola en el mercado."
                ),
                "country": state.get("country"),
                "categories_file": prepared.categories_file,
                "match_rate_pct": round(100 * prepared.match / total, 2) if total else 0.0,
                "false_negatives": prepared.mistakes,
                "instructions": (
                    "Claude Code: lee categories_file (categorías únicas de ambas bases con "
                    "conteos; no trae nombres de clientes). 1) category_mapping: para cada "
                    "categoría de 'prospection' la más parecida de 'client' (o vacía) con "
                    "confidence High/Medium/Low; 2) non_beverage: solo las que claramente no "
                    "venden bebidas (ante la duda, no la marques); 3) benchmark: busca en la web "
                    "la penetración o share de Coca-Cola en el país (solo el nombre del país en "
                    "la búsqueda, nunca coordenadas ni datos de la corrida) y escribe 3-5 "
                    "oraciones con fuentes https. Sin cifra confiable: penetration_pct null."
                ),
                "answer_format": {
                    "category_mapping": [
                        {
                            "prospection_category": "restaurant",
                            "client_category": "RESTAURANTE",
                            "confidence": "High",
                            "notes": "",
                        }
                    ],
                    "non_beverage": [{"category": "hardware_store", "reason": "ferretería"}],
                    "benchmark": {
                        "country": "Argentina",
                        "penetration_pct": None,
                        "penetration_text": "",
                        "paragraph": "...",
                        "sources": [{"title": "...", "url": "https://..."}],
                    },
                },
                "errors": state.get("errors", []),
            }
        )
        parsed = _validate(ProspectionQaReview, answer)
        if isinstance(parsed, list):
            return _retry(state, parsed)
        if parsed.review_file:
            try:
                content = json.loads(Path(parsed.review_file).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                return _retry(state, [f"review_file: {exc}"])
            if isinstance(content, dict):
                content.pop("review_file", None)
            parsed = _validate(ProspectionQaReview, content)
            if isinstance(parsed, list):
                return _retry(state, [f"review_file: {e}" for e in parsed])
        return {"prospection_qa": {**info, "review": parsed.model_dump()}, **_ok()}

    return prospection_qa_review


def make_build_prospection_qa(deps: Dependencies) -> NodeFn:
    def build_prospection_qa(state: CleaningState) -> Update:
        """Done when the QA Excel files, maps and report are in the mirror and the report
        is queued to go up with the prospects (or the build failed: a warning)."""
        info = dict(state.get("prospection_qa") or {})
        prepared = ProspectionQaPrepared.model_validate(info["prepared"])
        review = ProspectionQaReview.model_validate(info.get("review") or {})
        client = str((state.get("datamatch") or {}).get("client_name", "")).lower()
        if deps.prospection_qa is None:
            return _skip("QA no configurado")
        try:
            result = deps.prospection_qa.build(
                prepared,
                review,
                client,
                state.get("country", ""),
                dict(info.get("dataplor_cols") or DEFAULT_DATAPLOR_COLS),
            )
        except QA_ERRORS as exc:
            _logger(state).warning("Prospection QA build failed: %s", exc)
            return {
                "prospection_qa": {**info, "result": None},
                "warnings": [f"QA de prospección sin reporte: {exc}"],
            }
        lineage = record_stage(
            deps,
            state,
            "prospection_qa",
            "QA de prospección (falsos negativos, categorías, mercado)",
            str(info.get("started") or now_iso()),
            [ArtifactRef(path=prepared.categories_file), ArtifactRef(path=prepared.mistakes_file)],
            [deps.lineage.describe(result.report)],
            result.summary,
        )
        extra: dict[str, object] = {
            "files": [result.report, *(str(s) for s in lineage.get("sidecars", []))],
            "container": deps.dwh_container,
            "blob_prefix": qa_base(deps, state),
        }
        return {
            **lineage,
            "prospection_qa": {**info, "result": result.model_dump(), "upload": extra},
        }

    return build_prospection_qa


def after_build_prospection_qa(state: CleaningState) -> str:
    info = state.get("prospection_qa") or {}
    prepared = info.get("prepared") or {}
    return "confirm" if int(prepared.get("mistakes", 0)) > 0 else "continue"


def confirm_false_negatives(state: CleaningState) -> Update:
    """HITL. Done when the person decided whether the false negatives leave the prospects."""
    info = dict(state.get("prospection_qa") or {})
    prepared = ProspectionQaPrepared.model_validate(info["prepared"])
    result = info.get("result") or {}
    answer = interrupt(
        {
            "kind": "confirm_false_negatives",
            "question": (
                f"El QA encontró {prepared.mistakes:,} prospectos que parecen clientes de la "
                "base (falsos negativos del Datamatch). ¿Los saco de los prospectos?"
            ),
            "by_reason": prepared.by_reason,
            "report": result.get("report"),
            "mistakes_file": prepared.mistakes_file,
            "local_files": result.get("local_files", []),
            "summary": result.get("summary", {}),
            "answer_format": {"remove": True, "note": None},
            "errors": state.get("errors", []),
        }
    )
    parsed = _validate(FalseNegativesDecision, answer)
    if isinstance(parsed, list):
        return _retry(state, parsed)
    return {
        "prospection_qa": {**info, "remove": parsed.remove, "note": parsed.note},
        **_ok(),
    }

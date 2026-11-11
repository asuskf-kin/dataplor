"""Priorización (last step of the flow), run in its own project after the uploads.

    ask_priorizacion* -> run_priorizacion -> stage_priorizacion -> confirm* -> upload
        -> stage_gold_package (with Datamatch) | build_lineage (Datamatch skipped)

Input: the gold prospects, or the silver cleaned CSV when Datamatch was skipped.

Priorización reads its input from Azure and writes its outputs to Azure itself,
so the question is also the approval for those writes.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

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
from cleaning_agent.application.graph.warehouse_nodes import _cleaned_dataplor
from cleaning_agent.domain.lineage import ArtifactRef, now_iso
from cleaning_agent.domain.models import (
    PriorizacionDecision,
    PriorizacionRun,
    blob_location,
)
from cleaning_agent.domain.priorizacion import (
    country_name,
    geodata_prefix,
    output_names,
    priorizacion_qa,
)
from cleaning_agent.domain.warehouse import Layer, layer_prefix

PRIORIZACION_ERRORS = (RuntimeError, OSError, ValueError, KeyError)


def _guess_config(deps: Dependencies, configs: list[str], country: str) -> str | None:
    # A YAML of the same country first; otherwise the single-base parameters donor
    try:
        name = country_name(country).lower()
    except ValueError:
        name = ""
    same_country = next(
        (c for c in configs if name and c.lower().startswith(name)), None
    )
    if same_country:
        return same_country
    return (
        deps.priorizacion_base_config
        if deps.priorizacion_base_config in configs
        else None
    )


def _output_dir(deps: Dependencies, state: CleaningState, today: str) -> str:
    country, bottler = state.get("country", ""), state.get("bottler", "")
    try:
        name = country_name(country)
    except ValueError:
        name = country
    template = deps.priorizacion_output_template.replace("{pais_nombre}", name)
    template = template.replace("{bottler}_", f"{bottler_folder(bottler)}_")
    return layer_prefix(Layer.BRONZE, country, bottler, today, template)


def _default_input(deps: Dependencies, state: CleaningState) -> str | None:
    if without_prospects(state):
        return _cleaned_blob(deps, state)
    csvs = [u for u in state.get("uploaded") or [] if u.endswith(".csv")]
    return csvs[-1] if csvs else None


def without_prospects(state: CleaningState) -> bool:
    return bool(state.get("datamatch_skipped")) and not state.get("datamatch_history")


def _cleaned_blob(deps: Dependencies, state: CleaningState) -> str | None:
    """Blob of the silver CSV of the executive report (cleaned, no franchises).

    "uploaded" only keeps the last upload (gold), so the blob comes from the mirror:
    data/<blob> is the local copy of <dwh container>/<blob>."""
    cleaned = Path(_cleaned_dataplor(state))
    try:
        blob = cleaned.relative_to(deps.mirror_root).as_posix()
    except ValueError:
        return None  # not in the mirror, so never uploaded: the person gives it
    return f"{deps.dwh_container}/{blob}"


def _notes(state: CleaningState) -> list[str]:
    if without_prospects(state):
        return [
            (
                "Sin Datamatch: la entrada es el CSV limpio, que todavía incluye los "
                "clientes que el bottler ya tiene; después de la priorización no se arma "
                "el paquete gold."
            )
        ]
    return []


def make_ask_priorizacion(deps: Dependencies) -> NodeFn:
    def ask_priorizacion(state: CleaningState) -> Update:
        """HITL. Done when it is decided whether (and with what) priorización runs."""
        configs = deps.priorizacion.list_configs()
        today = datetime.now().strftime("%Y%m%d")  # outputs use the current date (user)
        output_dir = _output_dir(deps, state, today)
        defaults = {
            "run": True,
            "base_config": _guess_config(deps, configs, state.get("country", "")),
            "period": today[:6],
            "input_blob": _default_input(deps, state),
            "output_dir": output_dir,
            **(state.get("priorizacion") or {}),
        }
        answer = interrupt(
            {
                "kind": "ask_priorizacion",
                "question": (
                    "¿Corro la priorización? Lee el CSV limpio de Azure y escribe sus salidas en "
                    "output_dir (mismo contenedor)."
                ),
                "configs": configs,
                "defaults": defaults,
                "notes": _notes(state),
                "answer_format": {"run": True},
                "errors": state.get("errors", []),
            }
        )
        if isinstance(answer, dict):
            answer = {**defaults, **answer}
        parsed = _validate(PriorizacionDecision, answer)
        if isinstance(parsed, list):
            return _retry(state, parsed)
        if parsed.run and parsed.base_config not in configs:
            return _retry(state, [f"base_config: unknown config {parsed.base_config}"])
        if parsed.run and (
            parsed.input_blob is None or blob_location(parsed.input_blob) is None
        ):
            return _retry(
                state, ["input_blob: needs <container>/<blob> of the cleaned CSV"]
            )
        return {"priorizacion": parsed.model_dump(), **_ok()}

    return ask_priorizacion


def make_run_priorizacion(deps: Dependencies) -> NodeFn:
    def run_priorizacion(state: CleaningState) -> Update:
        """Done when priorización wrote its two outputs (or the run failed)."""
        decision = PriorizacionDecision.model_validate(state["priorizacion"])
        location = blob_location(str(decision.input_blob))
        if location is None or decision.base_config is None or decision.period is None:
            return {"status": "failed", "error": "Priorización: incomplete decision"}
        started = now_iso()
        bottler, country = (
            bottler_folder(state.get("bottler", "")),
            state.get("country", ""),
        )
        try:
            step1, step2 = output_names(bottler, country, decision.period)
            run = PriorizacionRun(
                input_blob=location[1],
                input_container=location[0],
                output_container=deps.dwh_container,
                output_dir=decision.output_dir.strip("/"),
                step1_name=step1,
                step2_name=step2,
                geodata_prefix=geodata_prefix(country),
                run_name=f"{bottler}_{country}_{decision.period}",
            )
            config = deps.priorizacion.build_config(decision.base_config, run)
            result = deps.priorizacion.run(config, state["run_id"])
        except PRIORIZACION_ERRORS as exc:
            _logger(state).error("Priorización failed: %s", exc)
            return {"status": "failed", "error": f"Priorización: {exc}"}
        lineage = record_stage(
            deps,
            state,
            "priorizacion",
            "Priorización On Premise",
            started,
            [ArtifactRef(path=str(decision.input_blob), blob=str(decision.input_blob))],
            [ArtifactRef(path=o, blob=o) for o in result.outputs],
            {"config": result.config_path, "base_config": decision.base_config},
        )
        return {
            "status": "prioritized",
            "priorizacion_outputs": result.outputs,
            **lineage,
        }

    return run_priorizacion


def after_ask_priorizacion(state: CleaningState) -> str:
    return "run" if (state.get("priorizacion") or {}).get("run") else "skip"


def make_stage_priorizacion(deps: Dependencies) -> NodeFn:
    def stage_priorizacion(state: CleaningState) -> Update:
        """Done when both priorización outputs are mirrored under data/, pass the QA and
        have their metadata + QA page queued for approval, or the QA failed."""
        decision = PriorizacionDecision.model_validate(state["priorizacion"])
        outputs = [str(o) for o in state.get("priorizacion_outputs") or []]
        local_dir = deps.mirror_root / decision.output_dir.strip("/")
        started = now_iso()
        try:
            local: list[str] = []
            for output in outputs:
                location = blob_location(output)
                if location is None:
                    raise ValueError(f"not a <container>/<blob> path: {output}")
                local += deps.storage.download(*location, local_dir)
            if len(local) != 2:
                raise ValueError(f"expected 2 outputs, got {len(local)}")
            input_blob = blob_location(str(decision.input_blob))
            input_local = deps.mirror_root / input_blob[1] if input_blob else None
            step1_rows = deps.staging.count_rows(local[0])
            input_rows = (
                deps.staging.count_rows(str(input_local))
                if input_local is not None and input_local.is_file()
                else step1_rows
            )
            qa = priorizacion_qa(
                input_rows,
                step1_rows,
                deps.staging.count_rows(local[1]),
                deps.staging.columns(local[1]),
            )
        except (RuntimeError, OSError, ValueError) as exc:
            _logger(state).error("Priorización staging failed: %s", exc)
            return {"status": "failed", "error": f"Priorización (QA): {exc}"}
        if not qa["qa_ok"]:
            failed = [c["check"] for c in qa["checks"] if not c["ok"]]
            return {"status": "failed", "error": f"QA de priorización falló: {failed}"}
        sidecars: list[str] = []
        for path, output in zip(local, outputs, strict=True):
            name = Path(path).stem
            metadata: dict[str, Any] = {
                "origen": str(decision.input_blob),
                "archivo": Path(path).name,
                "fecha": datetime.now().strftime("%Y%m%d"),
                "canal": state.get("channel"),
                "analisis": "priorizacion_on_premise",
                "#": {"total": qa["filas_leidas"], "utiles": qa["filas_conservadas"]},
                "% datos utiles": round(100 - qa["pct_eliminado"], 2),
                "por que se limpiaron": {},
                "alertas": [c for c in qa["checks"] if not c["ok"]],
                "POR VERIFICAR": [],
                "insumos": [
                    str(decision.input_blob),
                    geodata_prefix(state.get("country", "")),
                ],
                "capa": Layer.BRONZE.value,
                "destinos": [output],
                "espejo_local": path,
                "pais": state.get("country"),
                "bottler": state.get("bottler"),
                "premise": state.get("premise"),
                "proceso": "Priorización On Premise (score + capas geográficas)",
                "base_config": decision.base_config,
                "periodo": decision.period,
                "run_id": state["run_id"],
                "code_version": deps.lineage.code_version(),
                "qa": qa,
            }
            sidecars += deps.staging.write_sidecars(
                metadata,
                local_dir / f"{name}_metadata.json",
                local_dir / f"{name}_qa.html",
            )
        lineage = record_stage(
            deps,
            state,
            "stage_priorizacion",
            "Priorización: espejo local + QA",
            started,
            [ArtifactRef(path=o, blob=o) for o in outputs],
            [deps.lineage.describe(p) for p in local],
            {k: v for k, v in qa.items() if k != "checks"},
        )
        return {
            **lineage,
            # The CSVs are already in Azure (priorización wrote them) and the local copies
            # were downloaded from those blobs in this step, so only the new sidecars go
            # up. Priorización uploads without Content-MD5, so the CSVs cannot be checked
            # by MD5 against Azure; the download is what ties local and remote together.
            "pending_upload": {
                "layer": Layer.BRONZE.value,
                "files": sidecars,
                "already_in_azure": local,
                "container": deps.dwh_container,
                "blob_prefix": decision.output_dir.strip("/"),
                "copies": [],
                "qa": dict(qa),
            },
        }

    return stage_priorizacion

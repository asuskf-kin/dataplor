"""Publishing a step's result to a DWH layer: stage (mirror + QA) -> ask -> upload.

Same three steps for every layer, so silver and gold reuse them:
- stage_<layer>: copies the file into the local mirror ``data/<blob path>`` and
  writes its ``_metadata.json`` (QA, origins, lineage) and ``_qa.html``.
- confirm_<layer>*: always asks before anything leaves the machine.
- upload_<layer>: uploads file + sidecars (overwrite: re-running is safe).
"""

from pathlib import Path
from typing import Any

from langgraph.types import interrupt

from cleaning_agent.application.graph.nodes import (
    Dependencies,
    NodeFn,
    Update,
    _logger,
    _mode,
    _ok,
    _retry,
    _validate,
    record_stage,
)
from cleaning_agent.application.graph.state import CleaningState
from cleaning_agent.domain.lineage import ArtifactRef, now_iso
from cleaning_agent.domain.models import (
    CleaningMode,
    FrontResult,
    UploadDecision,
    blob_location,
)
from cleaning_agent.domain.qa import prefilter_qa
from cleaning_agent.domain.warehouse import Layer, folder, layer_prefix

# Folder right after the date: which method cleaned the data (user-defined names)
METHOD_FOLDER = {
    CleaningMode.GEOJSON: "distance",
    CleaningMode.CLIENTES_BOTTLER: "clients_bottler",
}
PROCESS_LABEL = {
    CleaningMode.GEOJSON: "Pre-filtro por distancia (GeoJSON del territorio)",
    CleaningMode.CLIENTES_BOTTLER: "Pre-filtro por clientes del bottler",
}


def _origins(state: CleaningState) -> list[str]:
    """Blob (or local) paths the run's inputs came from, from this run's lineage."""
    origins: list[str] = []
    for record in state.get("lineage", []):
        if record.get("stage") in {"fetch_raw", "fetch_inputs"}:
            items = record.get("inputs")
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict):
                    origins.append(str(item.get("blob") or item.get("path")))
    intake_raw = (state.get("intake") or {}).get("dataplor_raw")
    if intake_raw and not any(
        str(intake_raw).endswith(o.split("/", 1)[-1]) for o in origins
    ):
        origins.insert(0, str(intake_raw))
    return origins


def _files(pending: dict[str, object]) -> list[str]:
    value = pending.get("files")
    return [str(f) for f in value] if isinstance(value, list) else []


def make_stage_bronze(deps: Dependencies) -> NodeFn:
    def stage_bronze(state: CleaningState) -> Update:
        """Done when the pre-filter output, its metadata and QA are in the local mirror."""
        mode = _mode(state)
        prefilter = state.get("prefilter") or {}
        raw_counts = prefilter.get("counts")
        counts = {
            str(k): int(v)
            for k, v in (raw_counts if isinstance(raw_counts, dict) else {}).items()
        }
        source = str(prefilter.get("output_csv"))
        country, bottler = state.get("country", ""), state.get("bottler", "")
        method = METHOD_FOLDER[mode]
        prefix = "/".join(
            (
                layer_prefix(
                    Layer.BRONZE,
                    country,
                    bottler,
                    state["run_date"],
                    deps.dwh_path_template,
                ),
                method,
            )
        )
        name = (
            f"dataplor_{method}_{folder(country)}_{folder(bottler)}_{state['run_date']}"
        )
        local_dir = deps.mirror_root / prefix
        started = now_iso()
        try:
            mirrored = deps.staging.mirror(source, local_dir / f"{name}.csv")
            qa = prefilter_qa(counts, deps.staging.count_rows(mirrored))
        except (OSError, ValueError, RuntimeError) as exc:
            _logger(state).error("Bronze staging failed: %s", exc)
            return {"status": "failed", "error": f"Bronze ({source}): {exc}"}
        destination = f"{deps.dwh_container}/{prefix}/{name}.csv"
        metadata: dict[str, Any] = {
            "archivo": f"{name}.csv",
            "capa": Layer.BRONZE.value,
            "destino": destination,
            "espejo_local": mirrored,
            "run_id": state["run_id"],
            "fecha": state["run_date"],
            "pais": country,
            "bottler": bottler,
            "canal": state.get("channel"),
            "premise": state.get("premise"),
            "proceso": PROCESS_LABEL[mode],
            "metodo": method,
            "origen": _origins(state),
            "qa": qa,
            "conteos": counts,
            "code_version": deps.lineage.code_version(),
            "linaje": [
                {
                    "etapa": r.get("stage"),
                    "nombre": r.get("name"),
                    "inicio": r.get("started_at"),
                    "fin": r.get("finished_at"),
                    "entrada": r.get("inputs"),
                    "salida": r.get("outputs"),
                }
                for r in state.get("lineage", [])
            ],
        }
        sidecars = deps.staging.write_sidecars(
            metadata, local_dir / f"{name}_metadata.json", local_dir / f"{name}_qa.html"
        )
        lineage = record_stage(
            deps,
            state,
            "stage_bronze",
            "Bronze: espejo local + QA",
            started,
            [deps.lineage.describe(source)],
            [
                ArtifactRef(
                    path=mirrored, rows=qa["filas_conservadas"], blob=destination
                )
            ],
            {k: v for k, v in qa.items() if k != "checks"},
        )
        return {
            **lineage,
            "pending_upload": {
                "layer": Layer.BRONZE.value,
                "files": [mirrored, *sidecars],
                "container": deps.dwh_container,
                "blob_prefix": prefix,
                "qa": {k: v for k, v in qa.items()},
            },
            "warnings": []
            if qa["qa_ok"]
            else [f"Bronze QA con alertas: {qa['checks']}"],
        }

    return stage_bronze


def make_confirm_layer(deps: Dependencies, layer: Layer) -> NodeFn:
    def confirm_layer(state: CleaningState) -> Update:
        """HITL. Done when the person approved (and Azure is configured) or declined."""
        pending = state.get("pending_upload") or {}
        defaults = {
            "container": pending.get("container", deps.dwh_container),
            "blob_prefix": pending.get("blob_prefix", ""),
        }
        answer = interrupt(
            {
                "kind": "confirm_layer_upload",
                "layer": layer.value,
                "question": f"¿Subo estos archivos a {layer.value}?",
                "files": _files(pending),
                "qa": pending.get("qa"),
                "qa_html": next(
                    (f for f in _files(pending) if str(f).endswith("_qa.html")),
                    None,
                ),
                "defaults": defaults,
                "storage_configured": deps.storage.is_configured(),
                "answer_format": {"approved": True},
                "errors": state.get("errors", []),
            }
        )
        if isinstance(answer, dict):
            answer = {**defaults, **answer}
        parsed = _validate(UploadDecision, answer)
        if isinstance(parsed, list):
            return _retry(state, parsed)
        if not parsed.approved:
            _logger(state).info(
                "%s upload declined: stays in the local mirror", layer.value
            )
            # Without the upload the Front has nothing to work on: the run stops here
            return {
                "pending_upload": {**pending, "approved": False},
                "status": "kept_local",
                "note": parsed.note,
                **_ok(),
            }
        if not deps.storage.is_configured():
            return _retry(
                state, ["Azure is not configured (AZURE_STORAGE_CONNECTION_STRING)"]
            )
        return {
            "pending_upload": {
                **pending,
                "approved": True,
                "container": parsed.container,
                "blob_prefix": parsed.blob_prefix.strip("/"),
            },
            **_ok(),
        }

    confirm_layer.__name__ = f"confirm_{layer.value}"
    return confirm_layer


def make_upload_layer(deps: Dependencies, layer: Layer) -> NodeFn:
    def upload_layer(state: CleaningState) -> Update:
        """Done when the layer's files are in Azure (or the run failed)."""
        pending = state.get("pending_upload") or {}
        files = [str(f) for f in _files(pending)]
        started = now_iso()
        try:
            result = deps.storage.upload(
                files, str(pending["container"]), str(pending["blob_prefix"])
            )
        except (RuntimeError, OSError) as exc:
            _logger(state).error("%s upload failed: %s", layer.value, exc)
            return {"status": "failed", "error": f"Upload {layer.value}: {exc}"}
        lineage = record_stage(
            deps,
            state,
            f"upload_{layer.value}",
            f"Subida a {layer.value}",
            started,
            [deps.lineage.describe(f) for f in files],
            [ArtifactRef(path=Path(b).name, blob=b) for b in result.uploaded],
            {"files": len(result.uploaded)},
        )
        return {"uploaded": result.uploaded, **lineage}

    upload_layer.__name__ = f"upload_{layer.value}"
    return upload_layer


def after_confirm_layer(state: CleaningState) -> str:
    return "upload" if (state.get("pending_upload") or {}).get("approved") else "skip"


def _mirror_dir(deps: Dependencies, container: str, blob: str) -> Path:
    """Local mirror of a blob's folder: data/<blob dir> for the DWH container."""
    parent = Path(*Path(blob).parent.parts) if "/" in blob else Path()
    if container == deps.dwh_container:
        return deps.mirror_root / parent
    return deps.mirror_root / container / parent


def _check_remote(deps: Dependencies, name: str, path: str) -> list[str]:
    if deps.datasets.exists(path):
        return []
    location = blob_location(path)
    if location is None:
        return [f"{name}: not found locally or in Azure ({path})"]
    if not deps.storage.is_configured():
        return [f"{name}: Azure is not configured (AZURE_STORAGE_CONNECTION_STRING)"]
    try:
        found = deps.storage.list_blobs(*location)
    except (RuntimeError, OSError) as exc:
        return [f"{name}: could not list {path}: {exc}"]
    return [] if found else [f"{name}: no blob matches {path}"]


def make_front_dataplor(deps: Dependencies) -> NodeFn:
    def front_dataplor(state: CleaningState) -> Update:
        """HITL. Done when the Front's result file and its JSON exist (blob or local)."""
        pending = state.get("pending_upload") or {}
        bronze = [
            f"{pending.get('container')}/{pending.get('blob_prefix')}/{Path(f).name}"
            for f in _files(pending)
            if f.endswith((".csv", ".parquet"))
        ]
        answer = interrupt(
            {
                "kind": "front_dataplor",
                "question": (
                    "Continúa el proceso en el Front con el Dataplor indicado y, al terminar, "
                    "dame el path del resultado y el JSON de ese paso."
                ),
                "front_url": deps.front_url,
                "bronze_files": bronze,
                # Mode 'no cleaning': the Front works on the raw Dataplor directly
                "dataplor_file": None
                if bronze
                else (state.get("intake") or {}).get("dataplor_raw"),
                "defaults": state.get("front") or {},
                "answer_format": {
                    "result_file": "<contenedor>/<ruta>/resultado.csv",
                    "metadata_json": "<contenedor>/<ruta>/resultado.json",
                },
                "errors": state.get("errors", []),
            }
        )
        parsed = _validate(FrontResult, answer)
        if isinstance(parsed, list):
            return {
                **_retry(state, parsed),
                "front": answer if isinstance(answer, dict) else None,
            }
        errors = _check_remote(deps, "result_file", parsed.result_file) + _check_remote(
            deps, "metadata_json", parsed.metadata_json
        )
        if errors:
            return {**_retry(state, errors), "front": parsed.model_dump()}
        return {"front": parsed.model_dump(), **_ok()}

    return front_dataplor


def make_fetch_front(deps: Dependencies) -> NodeFn:
    def fetch_front(state: CleaningState) -> Update:
        """Done when the Front's result and JSON are in the local mirror and the result is
        the cleaning input."""
        front = FrontResult.model_validate(state["front"])
        started = now_iso()
        local: dict[str, str] = {}
        sources: list[ArtifactRef] = []
        for name, path in (
            ("result_file", front.result_file),
            ("metadata_json", front.metadata_json),
        ):
            location = None if deps.datasets.exists(path) else blob_location(path)
            if location is None:
                local[name] = path
                sources.append(deps.lineage.describe(path))
                continue
            try:
                files = deps.storage.download(*location, _mirror_dir(deps, *location))
            except (RuntimeError, OSError) as exc:
                _logger(state).error("Front download failed: %s", exc)
                return {"status": "failed", "error": f"Front ({path}): {exc}"}
            local[name] = files[0]
            sources.append(ArtifactRef(path=path, blob=f"{location[0]}/{location[1]}"))
        lineage = record_stage(
            deps,
            state,
            "front_dataplor",
            "Resultado del Front (descargado al espejo local)",
            started,
            sources,
            [
                deps.lineage.describe(local["result_file"]),
                deps.lineage.describe(local["metadata_json"]),
            ],
            {"front_metadata_json": local["metadata_json"]},
        )
        # The Front's result is what the Pipeline Data clean reads next
        inputs = {**(state.get("inputs") or {}), "raw_csv": local["result_file"]}
        return {"inputs": inputs, "front_local": local, **lineage}

    return fetch_front


def after_confirm_bronze(state: CleaningState) -> str:
    return "upload" if (state.get("pending_upload") or {}).get("approved") else "stop"

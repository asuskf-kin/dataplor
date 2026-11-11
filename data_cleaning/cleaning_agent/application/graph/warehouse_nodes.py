"""Publishing a step's result to a DWH layer: stage (mirror + QA) -> ask -> upload.

Same three steps for every layer, so silver and gold reuse them:
- stage_<layer>: copies the file into the local mirror ``data/<blob path>`` and
  writes its ``_metadata.json`` (QA, origins, lineage) and ``_qa.html``.
- confirm_<layer>*: always asks before anything leaves the machine.
- upload_<layer>: uploads file + sidecars (overwrite: re-running is safe).
"""

from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import polars as pl
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
    layer_dir,
    record_stage,
)
from cleaning_agent.application.graph.state import CleaningState
from cleaning_agent.domain.datamatch_steps import prospects_qa, step_folder
from cleaning_agent.domain.franchises import mark_franchises
from cleaning_agent.domain.lineage import ArtifactRef, now_iso
from cleaning_agent.domain.models import (
    CleaningMode,
    DatamatchInputs,
    DatamatchLoopDecision,
    FrontResult,
    UploadDecision,
    UploadResult,
    blob_location,
    raw_blob_location,
)
from cleaning_agent.domain.qa import pipeline_qa, prefilter_qa
from cleaning_agent.domain.storage_errors import BlobExistsError
from cleaning_agent.domain.warehouse import Layer, folder, layer_prefix, pdv_label

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


def _copies(pending: dict[str, object]) -> list[dict[str, str]]:
    value = pending.get("copies")
    return [c for c in value if isinstance(c, dict)] if isinstance(value, list) else []


def _extras(pending: dict[str, object]) -> list[dict[str, object]]:
    """Files that go to another folder of the same upload (e.g. a step's report in
    the date folder while the step's files go to its own folder)."""
    extra = pending.get("extra")
    return [e for e in extra if isinstance(e, dict)] if isinstance(extra, list) else []


def _extra_files(extra: dict[str, object]) -> list[str]:
    files = extra.get("files")
    return [str(f) for f in files] if isinstance(files, list) else []


def _files(pending: dict[str, object]) -> list[str]:
    value = pending.get("files")
    return [str(f) for f in value] if isinstance(value, list) else []


def _raw_copy_targets(deps: Dependencies, state: CleaningState) -> list[dict[str, str]]:
    """Copy of the layer file inside the raw's folder, under ``<method>/<yyyymmdd>``.

    ``dataplorraw/dataplor_raw_parquet/2026-10-15_ar.csv.parquet/part-0.parquet`` ->
    ``dataplorraw/dataplor_raw_parquet/2026-10-15_ar.csv.parquet/distance/20261109``
    (user rule), so each cleaning of that raw is kept apart.
    """
    raw = str((state.get("intake") or {}).get("dataplor_raw", ""))
    location = raw_blob_location(raw, deps.raw_container)
    if location is None:
        return []
    folder_path = (
        PurePosixPath(location[1]).parent
        / METHOD_FOLDER[_mode(state)]
        / state["run_date"]
    )
    return [{"container": location[0], "blob_prefix": str(folder_path)}]


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
            # Layer files are Parquet (user rule); the pipeline keeps reading its CSV
            mirrored = deps.staging.mirror(source, local_dir / f"{name}.parquet")
            qa = prefilter_qa(counts, deps.staging.count_rows(mirrored))
        except (OSError, ValueError, RuntimeError) as exc:
            _logger(state).error("Bronze staging failed: %s", exc)
            return {"status": "failed", "error": f"Bronze ({source}): {exc}"}
        if not qa["qa_ok"]:
            # Guideline: a failed QA stops the stage before uploading (files stay local)
            failed = [c["check"] for c in qa["checks"] if not c["ok"]]
            _logger(state).error("Bronze QA failed: %s", failed)
            return {
                "status": "failed",
                "error": f"QA de bronze falló: {failed} ({mirrored})",
            }
        destination = f"{deps.dwh_container}/{prefix}/{name}.parquet"
        copies = _raw_copy_targets(deps, state)
        origins = _origins(state)
        # Key order follows the guideline example (Lineamientos Blob CP v1.1, page 7)
        metadata: dict[str, Any] = {
            "origen": origins[0] if origins else "",
            "archivo": f"{name}.parquet",
            "fecha": state["run_date"],
            "canal": state.get("channel"),
            "analisis": method,
            "#": {"total": qa["filas_leidas"], "utiles": qa["filas_conservadas"]},
            "% datos utiles": round(100 - qa["pct_eliminado"], 2),
            "por que se limpiaron": qa["eliminadas_por_motivo"],
            "alertas": [c for c in qa["checks"] if not c["ok"]],
            "POR VERIFICAR": [],
            "insumos": origins[1:],
            "capa": Layer.BRONZE.value,
            "destinos": [destination]
            + [f"{c['container']}/{c['blob_prefix']}/{name}.parquet" for c in copies],
            "espejo_local": mirrored,
            "pais": country,
            "bottler": bottler,
            "premise": state.get("premise"),
            "proceso": PROCESS_LABEL[mode],
            "run_id": state["run_id"],
            "code_version": deps.lineage.code_version(),
            "qa": qa,
            "conteos": counts,
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
                # Also next to the raw Dataplor it came from (user rule)
                "copies": copies,
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
                "destinations": [
                    f"{pending.get('container')}/{pending.get('blob_prefix')}",
                    *(f"{c['container']}/{c['blob_prefix']}" for c in _copies(pending)),
                ],
                "extra_destinations": [
                    {
                        "destination": f"{e.get('container')}/{e.get('blob_prefix')}",
                        "files": e.get("files"),
                    }
                    for e in _extras(pending)
                ],
                "qa": pending.get("qa"),
                "qa_html": next(
                    (f for f in _files(pending) if str(f).endswith("_qa.html")),
                    None,
                ),
                "defaults": defaults,
                # Executive report (funnel, PDF, HTML) to review with the layer files
                "report_files": state.get("report_files", []),
                "storage_configured": deps.storage.is_configured(),
                "answer_format": {"approved": True, "replace": False},
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
                "replace": parsed.replace,
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
            targets = [
                (str(pending["container"]), str(pending["blob_prefix"])),
                *((c["container"], c["blob_prefix"]) for c in _copies(pending)),
            ]
            uploaded: list[str] = []
            skipped: list[str] = []
            batches = [(files, container, prefix) for container, prefix in targets]
            batches += [
                (
                    _extra_files(e),
                    str(e["container"]),
                    str(e["blob_prefix"]),
                )
                for e in _extras(pending)
            ]
            for batch, container, prefix in batches:
                part = deps.storage.upload(
                    batch, container, prefix, replace=bool(pending.get("replace"))
                )
                uploaded += part.uploaded
                skipped += part.skipped
            result = UploadResult(uploaded=uploaded, skipped=skipped)
        except BlobExistsError as exc:
            # Guideline: never replace without explicit permission -> ask again
            return {
                "pending_upload": {**pending, "approved": False},
                "errors": [
                    (
                        f"{exc} ya existe con otro contenido: responde replace: true para "
                        "reemplazarlo (verifico tamaño y MD5) o approved: false para no subir"
                    )
                ],
                "attempts": 0,
            }
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
            {"files": len(result.uploaded), "skipped": result.skipped},
        )
        return {"uploaded": result.uploaded + result.skipped, **lineage}

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


def _with_front_container(deps: Dependencies, path: str) -> str:
    """Front results default to the prospection-datacleaning container (user rule).

    A local file, or a path that already starts with a valid container, is kept.
    """
    if deps.datasets.exists(path) or blob_location(path) is not None:
        return path
    return f"{deps.front_container}/{path.lstrip('/')}"


LAYER_NAMES = {layer.value for layer in Layer}


def with_dwh_container(deps: Dependencies, path: str) -> str:
    """A DWH path (``silver/ko/...``) lives in the DWH container (user, 2026-11-11).

    Local files and ``<container>/<blob>`` paths are kept; a bare blob path whose first
    segment is a layer (or no valid container) gets the DWH container in front.
    """
    if deps.datasets.exists(path):
        return path
    normalized = path.replace("\\", "/").lstrip("/")
    if normalized.split("/", 1)[0] not in LAYER_NAMES and blob_location(path):
        return path
    return f"{deps.dwh_container}/{normalized}"


def check_remote(deps: Dependencies, name: str, path: str) -> list[str]:
    return _check_remote(deps, name, path)


def make_fetch_datamatch(deps: Dependencies) -> NodeFn:
    def fetch_datamatch(state: CleaningState) -> Update:
        """Done when the Datamatch result and the client base are in the local mirror
        (blobs downloaded; local files used as they are), or the download failed."""
        datamatch = dict(state.get("datamatch") or {})
        started = now_iso()
        sources: list[ArtifactRef] = []
        local: list[str] = []
        for name in ("datamatch_file", "clients_file", "step_json"):
            path = str(datamatch.get(name, ""))
            if not path:  # step_json is optional
                continue
            location = None if deps.datasets.exists(path) else blob_location(path)
            if location is None:
                sources.append(deps.lineage.describe(path))
                local.append(path)
                continue
            try:
                files = deps.storage.download(*location, _mirror_dir(deps, *location))
            except (RuntimeError, OSError) as exc:
                _logger(state).error("Datamatch download failed (%s): %s", name, exc)
                return {"status": "failed", "error": f"Datamatch ({name}): {exc}"}
            datamatch[name] = files[0]
            local.append(files[0])
            sources.append(ArtifactRef(path=path, blob=f"{location[0]}/{location[1]}"))
        lineage = record_stage(
            deps,
            state,
            "fetch_datamatch",
            "Resultado de Datamatch y base de clientes (espejo local)",
            started,
            sources,
            # Client base: only described (hash, size), never read row by row here
            [deps.lineage.describe(path) for path in local],
            {},
        )
        return {"datamatch": datamatch, **lineage}

    return fetch_datamatch


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
                "default_container": deps.front_container,
                "answer_format": {
                    "result_file": "<bottler>_<ISO3>_<fecha>/dataplor_cleaned/x.csv",
                    "metadata_json": "<bottler>_<ISO3>_<fecha>/dataplor_cleaned/json_config.json",
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
        parsed = parsed.model_copy(
            update={
                "result_file": _with_front_container(deps, parsed.result_file),
                "metadata_json": _with_front_container(deps, parsed.metadata_json),
            }
        )
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


def make_stage_silver(deps: Dependencies) -> NodeFn:
    def stage_silver(state: CleaningState) -> Update:
        """Done when the cleaned result (franchise review applied), its metadata and QA
        are in the local silver mirror, or the QA failed (stage stops before upload)."""
        df = deps.datasets.load_step(str(state["current_path"]))
        franchises = state.get("franchises") or {}
        flags = franchises.get("flags") or {}
        removed = 0
        if flags:
            df = mark_franchises(df, flags)
            if franchises.get("remove"):
                before = df.height
                df = df.filter(pl.col("es_franquicia") == "No")
                removed = before - df.height
        country, bottler = state.get("country", ""), state.get("bottler", "")
        # Silver has no method folder (user rule): silver/ko/<pais>/<bottler>/dataplor/<fecha>
        prefix = layer_prefix(
            Layer.SILVER, country, bottler, state["run_date"], deps.dwh_path_template
        )
        label = pdv_label(state.get("channel"), state.get("premise"))
        name = f"{label}_{folder(country)}_{folder(bottler)}_{state['run_date']}"
        local_dir = deps.mirror_root / prefix
        started = now_iso()
        summary = state.get("summary") or {}
        raw_steps = summary.get("steps")
        steps = (
            [s for s in raw_steps if isinstance(s, dict)]
            if isinstance(raw_steps, list)
            else []
        )
        raw_input = summary.get("input_rows")
        input_rows = raw_input if isinstance(raw_input, int) else 0
        try:
            written = deps.staging.write_parquet(df, local_dir / f"{name}.parquet")
            qa = pipeline_qa(
                input_rows,
                steps,
                removed,
                deps.staging.count_rows(written),
            )
        except (OSError, ValueError, RuntimeError) as exc:
            _logger(state).error("Silver staging failed: %s", exc)
            return {"status": "failed", "error": f"Silver: {exc}"}
        if not qa["qa_ok"]:
            failed = [c["check"] for c in qa["checks"] if not c["ok"]]
            return {
                "status": "failed",
                "error": f"QA de silver falló: {failed} ({written})",
            }
        front = state.get("front") or {}
        destination = f"{deps.dwh_container}/{prefix}/{name}.parquet"
        metadata: dict[str, Any] = {
            "origen": str(
                front.get("result_file") or (state.get("inputs") or {}).get("raw_csv")
            ),
            "archivo": f"{name}.parquet",
            "fecha": state["run_date"],
            "canal": state.get("channel"),
            "analisis": "dataplor_clean",
            "#": {"total": qa["filas_leidas"], "utiles": qa["filas_conservadas"]},
            "% datos utiles": round(100 - qa["pct_eliminado"], 2),
            "por que se limpiaron": qa["eliminadas_por_motivo"],
            "alertas": [c for c in qa["checks"] if not c["ok"]],
            "POR VERIFICAR": [],
            "insumos": [str(front["metadata_json"])]
            if front.get("metadata_json")
            else [],
            "franquicias": {
                "marcadas": franchises.get("marked_rows", 0),
                "eliminadas": removed,
                "por_marca": franchises.get("by_brand", {}),
            },
            "modulos": state.get("modules"),
            "capa": Layer.SILVER.value,
            "destinos": [destination],
            "espejo_local": written,
            "pais": country,
            "bottler": bottler,
            "premise": state.get("premise"),
            "proceso": "Pipeline Data clean + review de franquicias",
            "run_id": state["run_id"],
            "code_version": deps.lineage.code_version(),
            "qa": qa,
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
            "stage_silver",
            "Silver: espejo local + QA",
            started,
            [deps.lineage.describe(str(state["current_path"]))],
            [ArtifactRef(path=written, rows=qa["filas_conservadas"], blob=destination)],
            {k: v for k, v in qa.items() if k != "checks"},
        )
        return {
            **lineage,
            "pending_upload": {
                "layer": Layer.SILVER.value,
                "files": [written, *sidecars],
                "container": deps.dwh_container,
                "blob_prefix": prefix,
                "copies": [],
                "qa": dict(qa),
            },
        }

    return stage_silver


def make_stage_gold(deps: Dependencies) -> NodeFn:
    def stage_gold(state: CleaningState) -> Update:
        """Done when the executive Excel + its metadata are copied from silver into the
        gold mirror and queued for the person's approval, or there is no Excel (skip)."""
        silver = set(deps.staging.list_files(layer_dir(deps, state, Layer.SILVER)))
        gold_dir = layer_dir(deps, state, Layer.GOLD)
        files: list[str] = []
        for report in state.get("report_files", []):
            if not str(report).endswith(".xlsx"):
                continue
            path = Path(report)
            sidecar = str(path.with_name(f"{path.stem}_metadata.json"))
            for source in (str(path), sidecar):
                if source == str(path) or source in silver:
                    files.append(deps.staging.copy(source, gold_dir))
        if not files:
            _logger(state).info("Gold: no files in the local mirror, step skipped")
            return {"pending_upload": None}
        prefix = layer_prefix(
            Layer.GOLD,
            state.get("country", ""),
            state.get("bottler", ""),
            state["run_date"],
            deps.dwh_path_template,
        )
        return {
            "pending_upload": {
                "layer": Layer.GOLD.value,
                "files": files,
                "container": deps.dwh_container,
                "blob_prefix": prefix,
                "copies": [],
                "qa": None,
            }
        }

    return stage_gold


def make_stage_datamatch_step(deps: Dependencies) -> NodeFn:
    def stage_datamatch_step(state: CleaningState) -> Update:
        """Done when this Datamatch step's reduced client base, matches, Front JSON and
        Excel (with their metadata) are in the silver mirror and queued for approval,
        or the step failed."""
        inputs = DatamatchInputs.model_validate(state["datamatch"])
        prior = [dict(h) for h in state.get("datamatch_history") or []]
        folder = step_folder(inputs.step_json, len(prior) + 1)
        # A step run again (same folder) replaces its own summary, never duplicates it
        history = [h for h in prior if h.get("paso") != folder]
        # qa_process uses the date the cycle started (today on its first step), not the
        # run date; later steps keep it so the whole cycle shares one folder (user rule)
        cycle_date = str(
            state.get("qa_process_date") or datetime.now().strftime("%Y%m%d")
        )
        base = layer_prefix(
            Layer.SILVER,
            state.get("country", ""),
            state.get("bottler", ""),
            cycle_date,
            deps.qa_process_template,
        )
        prefix = f"{base}/{folder}"
        started = now_iso()
        try:
            result = deps.datamatch_steps.run(
                inputs,
                deps.mirror_root / prefix,
                # The step's Excel report lives in the date folder (user, 2026-11-11)
                deps.mirror_root / base,
                folder,
                deps.datamatch_step_threshold,
                history,
                state["run_id"],
            )
        except (ValueError, OSError, RuntimeError, pl.exceptions.PolarsError) as exc:
            _logger(state).error("Datamatch step %s failed: %s", folder, exc)
            return {"status": "failed", "error": f"Datamatch {folder}: {exc}"}
        lineage = record_stage(
            deps,
            state,
            f"datamatch_{folder}",
            f"Datamatch {folder}: base de clientes sin los encontrados",
            started,
            # The client base is described (hash, size), its rows never logged
            [
                deps.lineage.describe(inputs.datamatch_file),
                deps.lineage.describe(inputs.clients_file),
            ],
            [deps.lineage.describe(path) for path in result.files],
            {k: v for k, v in result.summary.items() if not k.endswith("_file")},
        )
        sidecars = [str(s) for s in lineage.get("sidecars", [])]
        step_dir = (deps.mirror_root / prefix).resolve()
        produced = [*result.files, *sidecars]
        in_step = [f for f in produced if Path(f).resolve().parent == step_dir]
        in_root = [f for f in produced if f not in in_step]
        return {
            **lineage,
            "datamatch_history": [*history, result.summary],
            "qa_process_date": cycle_date,
            "pending_upload": {
                "layer": Layer.SILVER.value,
                "files": in_step,
                "container": deps.dwh_container,
                "blob_prefix": prefix,
                "copies": [],
                "extra": [
                    {
                        "files": in_root,
                        "container": deps.dwh_container,
                        "blob_prefix": base,
                    }
                ]
                if in_root
                else [],
                "qa": {
                    k: result.summary[k]
                    for k in (
                        "clientes_inicio",
                        "clientes_con_match",
                        "clientes_restantes",
                        "pct_encontrado",
                        "umbral_limpieza",
                        "cuadra",
                    )
                },
            },
        }

    return stage_datamatch_step


def make_next_datamatch_step(deps: Dependencies) -> NodeFn:
    def next_datamatch_step(state: CleaningState) -> Update:
        """HITL. Done when the person asked for another Datamatch step (the new client
        base becomes its default) or said the loop is done (prospecting continues)."""
        pending = state.get("pending_upload") or {}
        history = state.get("datamatch_history") or []
        last = dict(history[-1]) if history else {}
        new_clients = (
            f"{pending.get('container')}/{pending.get('blob_prefix')}/"
            f"{last.get('nuevo_client_bottler', '')}"
        )
        answer = interrupt(
            {
                "kind": "datamatch_loop",
                "question": (
                    "¿Corres otro paso de Datamatch en el Front con el nuevo client "
                    "bottler, o ya estamos y seguimos con la prospección?"
                ),
                "front_url": deps.front_url,
                "new_clients_file": new_clients,
                "last_step": last,
                "steps": len(history),
                "answer_format": {"done": False},
                "errors": state.get("errors", []),
            }
        )
        parsed = _validate(DatamatchLoopDecision, answer)
        if isinstance(parsed, list):
            return _retry(state, parsed)
        if parsed.done:
            _logger(state).info("Datamatch loop done after %d step(s)", len(history))
            return {"datamatch_loop_done": True, "note": parsed.note, **_ok()}
        previous = state.get("datamatch") or {}
        return {
            "datamatch_loop_done": False,
            # Next Front step: the reduced base is the default, result and JSON are new
            "datamatch": {
                "client_name": previous.get("client_name", ""),
                "clients_file": new_clients,
                "datamatch_file": "",
                "step_json": "",
            },
            **_ok(),
        }

    return next_datamatch_step


def _loop_match_files(deps: Dependencies, state: CleaningState) -> list[str]:
    """Matches file of every Datamatch step, in the silver qa_process mirror."""
    base = layer_prefix(
        Layer.SILVER,
        state.get("country", ""),
        state.get("bottler", ""),
        str(state.get("qa_process_date", "")),
        deps.qa_process_template,
    )
    client = str((state.get("datamatch") or {}).get("client_name", "")).lower()
    return [
        str(
            deps.mirror_root
            / base
            / str(h["paso"])
            / f"datamatch_matches_{client}_{h['paso']}.csv"
        )
        for h in state.get("datamatch_history") or []
    ]


def _cleaned_dataplor(state: CleaningState) -> str:
    """The silver CSV without franchises (the executive report's channel CSV)."""
    csvs = [str(f) for f in state.get("report_files", []) if str(f).endswith(".csv")]
    return csvs[0] if csvs else str(state.get("output_path", ""))


def make_stage_prospects(deps: Dependencies) -> NodeFn:
    def stage_prospects(state: CleaningState) -> Update:
        """Done when the prospects file (cleaned Dataplor minus the points the bottler
        already has as clients), its metadata and QA are in the gold mirror and queued
        for approval, or the QA failed (stops before upload)."""
        today = datetime.now().strftime("%Y%m%d")  # gold uses the current date (user)
        country, bottler = state.get("country", ""), state.get("bottler", "")
        prefix = layer_prefix(
            Layer.GOLD, country, bottler, today, deps.prospects_template
        )
        label = pdv_label(state.get("channel"), state.get("premise"))
        name = f"prospects_{label}_{folder(country)}_{folder(bottler)}_{today}"
        local_dir = deps.mirror_root / prefix
        cleaned = _cleaned_dataplor(state)
        match_files = _loop_match_files(deps, state)
        started = now_iso()
        try:
            result = deps.datamatch_steps.build_prospects(
                cleaned, match_files, local_dir / f"{name}.csv"
            )
        except (ValueError, OSError, RuntimeError, pl.exceptions.PolarsError) as exc:
            _logger(state).error("Prospects failed: %s", exc)
            return {"status": "failed", "error": f"Prospectos: {exc}"}
        qa = prospects_qa(
            result.rows_in, result.known_ids, result.known_in_file, result.rows_out
        )
        if not qa["qa_ok"]:
            failed = [c["check"] for c in qa["checks"] if not c["ok"]]
            return {"status": "failed", "error": f"QA de prospectos falló: {failed}"}
        destination = f"{deps.dwh_container}/{prefix}/{name}.csv"
        metadata: dict[str, Any] = {
            "origen": cleaned,
            "archivo": f"{name}.csv",
            "fecha": today,
            "canal": state.get("channel"),
            "analisis": "dataplor_prospects",
            "#": {"total": qa["filas_leidas"], "utiles": qa["filas_conservadas"]},
            "% datos utiles": round(100 - qa["pct_eliminado"], 2),
            "por que se limpiaron": qa["eliminadas_por_motivo"],
            "alertas": [c for c in qa["checks"] if not c["ok"]],
            "POR VERIFICAR": [],
            "insumos": match_files,
            "pasos_datamatch": [
                h.get("paso") for h in state.get("datamatch_history") or []
            ],
            "capa": Layer.GOLD.value,
            "destinos": [destination],
            "espejo_local": result.file,
            "pais": country,
            "bottler": bottler,
            "premise": state.get("premise"),
            "proceso": "Dataplor limpio sin franquicias - clientes ya conocidos del bottler",
            "run_id": state["run_id"],
            "code_version": deps.lineage.code_version(),
            "qa": qa,
        }
        sidecars = deps.staging.write_sidecars(
            metadata, local_dir / f"{name}_metadata.json", local_dir / f"{name}_qa.html"
        )
        lineage = record_stage(
            deps,
            state,
            "stage_prospects",
            "Gold: prospectos (Dataplor sin clientes conocidos)",
            started,
            [
                deps.lineage.describe(cleaned),
                *(deps.lineage.describe(f) for f in match_files),
            ],
            [ArtifactRef(path=result.file, rows=result.rows_out, blob=destination)],
            {k: v for k, v in qa.items() if k != "checks"},
        )
        return {
            **lineage,
            "pending_upload": {
                "layer": Layer.GOLD.value,
                "files": [result.file, *sidecars],
                "container": deps.dwh_container,
                "blob_prefix": prefix,
                "copies": [],
                "qa": dict(qa),
            },
        }

    return stage_prospects

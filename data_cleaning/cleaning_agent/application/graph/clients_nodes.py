"""Paso 1 bottler dentro del flujo: validar la base de clientes antes del Datamatch.

    ... -> ask_validate_clients* -> validate_clients -> confirm_clients*
                                 -> upload_clients -> front_datamatch

Obligatorio (usuario, 2026-11-23): solo se salta si el país no tiene límites
configurados. Además de la base pide el GeoJSON del territorio del bottler (el de la
corrida o el que se encuentra en ``<front_container>/global_geojson/``) y cruza cada
cliente con él (``territorio_bottler``).

Mismas reglas y QA que la validación de clientes de Customer Potential (``dw_validar``):
canal, coordenada válida, dentro del país (polígono oficial, sin tolerancia; lat/lon
invertidas o sin signo se corrigen), coordenada única y no aislado. El CSV validado
queda como base de clientes por defecto del primer paso del Datamatch. Nada se sube sin
el OK de la persona (``confirm_clients`` reutiliza la confirmación de capa de bronze).
Se pregunta una sola vez: los pasos 2+ del Datamatch usan la base reducida del anterior.
"""

from pathlib import Path

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
    check_remote,
    mirror_dir,
    with_dwh_container,
)
from cleaning_agent.domain.lineage import ArtifactRef, now_iso
from cleaning_agent.domain.models import (
    ClientChannel,
    ClientValidationAnswer,
    blob_location,
)
from cleaning_agent.domain.warehouse import Layer


def _default_clients_file(deps: Dependencies, state: CleaningState) -> str:
    """La base que ya dio la persona: la del Front, la del pre-filtro o la de config."""
    datamatch = state.get("datamatch") or {}
    inputs = state.get("inputs") or {}
    return str(
        datamatch.get("clients_file")
        or inputs.get("clients_csv")
        or deps.datamatch_defaults.get("clients_file", "")
    )


TERRITORY_FOLDER = "global_geojson"


def territory_candidates(deps: Dependencies, state: CleaningState) -> list[str]:
    """GeoJSONs of the bottler's territory: the run's own, then the ones in the DWH.

    The Front keeps one per country and bottler (``global_geojson/Argentina_Andina.geojson``);
    only files whose name carries the bottler are offered. A listing failure leaves the
    list short: the person is asked anyway.
    """
    found: list[str] = []
    own = str((state.get("inputs") or {}).get("geojson") or "")
    if own:
        found.append(own)
    bottler = str(state.get("bottler", "")).lower()
    try:
        blobs = deps.storage.list_blobs(deps.front_container, f"{TERRITORY_FOLDER}/*")
    except Exception as exc:  # noqa: BLE001 - storage unset or down: ask the person
        _logger(state).warning("Territory GeoJSONs not listed: %s", exc.__class__.__name__)
        blobs = []
    found += sorted(
        f"{deps.front_container}/{b}"
        for b in blobs
        if b.lower().endswith((".geojson", ".json")) and bottler and bottler in b.lower()
    )
    return list(dict.fromkeys(found))


def make_ask_validate_clients(deps: Dependencies) -> NodeFn:
    def ask_validate_clients(state: CleaningState) -> Update:
        """HITL. Done when the client base and the bottler's territory GeoJSON are given
        and exist (validation is mandatory); skipped only if no validator fits the country."""
        country = str(state.get("country", ""))
        validator = deps.client_validation
        if validator is None or not validator.supports(country):
            _logger(state).warning(
                "No country boundary for '%s': client validation skipped", country
            )
            return {"clients_validation": {"validate_clients": False}, **_ok()}
        previous = state.get("clients_validation") or {}
        candidates = territory_candidates(deps, state)
        defaults = {
            "validate_clients": True,
            "clients_file": _default_clients_file(deps, state),
            "canal": ClientChannel.TODOS.value,
            "territorio_geojson": candidates[0] if candidates else "",
            **previous,
        }
        answer = interrupt(
            {
                "kind": "validate_clients",
                "question": (
                    "Validación obligatoria de los clientes bottler antes del Datamatch: "
                    "confirma la base, el canal y el GeoJSON del territorio donde trabaja "
                    "el bottler. Canal, coordenadas dentro del país (lat/lon invertidas o "
                    "sin signo se corrigen), coordenada única, no aislado y cruce con el "
                    "territorio; deja CSV + metadata + QA con mapa en bronze y el CSV pasa "
                    "a ser la base del Datamatch."
                ),
                "defaults": defaults,
                "options": [c.value for c in ClientChannel],
                "territory_candidates": candidates,
                "schema": ClientValidationAnswer.model_json_schema(),
                "errors": state.get("errors", []),
            }
        )
        if isinstance(answer, dict):
            answer = {**defaults, **answer}
        parsed = _validate(ClientValidationAnswer, answer)
        if isinstance(parsed, list):
            return {
                **_retry(state, parsed),
                "clients_validation": answer if isinstance(answer, dict) else None,
            }
        parsed = parsed.model_copy(
            update={
                "clients_file": with_dwh_container(deps, parsed.clients_file),
                "territorio_geojson": with_dwh_container(deps, parsed.territorio_geojson),
            }
        )
        missing = check_remote(deps, "clients_file", parsed.clients_file) + check_remote(
            deps, "territorio_geojson", parsed.territorio_geojson
        )
        if missing:
            return {
                **_retry(state, missing),
                "clients_validation": parsed.model_dump(mode="json"),
            }
        return {"clients_validation": parsed.model_dump(mode="json"), **_ok()}

    return ask_validate_clients


def after_ask_validate_clients(state: CleaningState) -> str:
    choice = state.get("clients_validation") or {}
    return "validate" if choice.get("validate_clients") else "skip"


def make_validate_clients(deps: Dependencies) -> NodeFn:
    def validate_clients(state: CleaningState) -> Update:
        """Done when the validated base, its metadata and its QA (with map) are in the
        bronze mirror, the QA passed and the files wait for upload approval; or failed."""
        choice = ClientValidationAnswer.model_validate(state["clients_validation"])
        validator = deps.client_validation
        if validator is None:  # ask_validate_clients never routes here without one
            return {"status": "failed", "error": "Validación de clientes no configurada"}
        started = now_iso()
        path = choice.clients_file
        source = ArtifactRef(path=path)
        territory = choice.territorio_geojson
        territory_ref = ArtifactRef(path=territory)
        try:
            location = None if deps.datasets.exists(path) else blob_location(path)
            if location is not None:
                path = deps.storage.download(*location, mirror_dir(deps, *location))[0]
                source = ArtifactRef(path=path, blob=f"{location[0]}/{location[1]}")
            where = None if deps.datasets.exists(territory) else blob_location(territory)
            if where is not None:
                territory = deps.storage.download(*where, mirror_dir(deps, *where))[0]
                territory_ref = ArtifactRef(path=territory, blob=f"{where[0]}/{where[1]}")
            result = validator.validate(
                path,
                str(state.get("country", "")),
                str(state.get("bottler", "")),
                choice.canal.value,
                str(state.get("run_date", "")),
                state["run_id"],
                territory,
            )
        except (AssertionError, RuntimeError, OSError, ValueError) as exc:
            # AssertionError = el QA no cuadró: no queda metadata de un archivo malo
            _logger(state).error("Client validation failed: %s", exc)
            return {"status": "failed", "error": f"Validación de clientes: {exc}"}
        files = [result.csv, result.metadata, result.qa]
        validated_blob = f"{deps.dwh_container}/{result.blob_prefix}/{Path(result.csv).name}"
        lineage = record_stage(
            deps,
            state,
            "validate_clients",
            "Clientes bottler: validación + QA (bronze)",
            started,
            # Client base: only its path is recorded in the run, never its rows
            [source, territory_ref],
            [ArtifactRef(path=result.csv, rows=result.rows_valid, blob=validated_blob)],
            {"rows_read": result.rows_read, "rows_valid": result.rows_valid},
        )
        _logger(state).info(
            "Client base validated: %d of %d rows", result.rows_valid, result.rows_read
        )
        return {
            **lineage,
            # The validated base becomes the default client base of Datamatch step 1
            "datamatch": {**(state.get("datamatch") or {}), "clients_file": validated_blob},
            "pending_upload": {
                "layer": Layer.BRONZE.value,
                "files": files,
                "container": deps.dwh_container,
                "blob_prefix": result.blob_prefix,
                "copies": [],
                "qa": {"qa_ok": result.qa_ok, **result.summary},
            },
        }

    return validate_clients

"""Gold delivery package (last data step, after priorización).

    upload_priorizacion -> stage_gold_package -> confirm_gold_package* -> upload -> lineage

Modelled on the approved Golfo package: KO / BOTTLER results, opportunity Excel,
offline maps and the results deck, in the gold folder of the prospects
(user, 2026-11-11). Everything is built in the local mirror first, passes a QA, ships
with its metadata + QA page and is uploaded only after the person approves.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from cleaning_agent.application.graph.nodes import (
    Dependencies,
    NodeFn,
    Update,
    _logger,
    bottler_folder,
    record_stage,
)
from cleaning_agent.application.graph.state import CleaningState
from cleaning_agent.domain.gold_package import package_qa, period_label
from cleaning_agent.domain.lineage import now_iso
from cleaning_agent.domain.models import (
    ClientColumns,
    GoldPackageRequest,
    PriorizacionDecision,
    blob_location,
)
from cleaning_agent.domain.priorizacion import country_name
from cleaning_agent.domain.warehouse import Layer, layer_prefix

GOLD_ERRORS = (ValueError, OSError, RuntimeError, KeyError)


def _request(
    deps: Dependencies, state: CleaningState, out_dir: Path
) -> GoldPackageRequest:
    decision = PriorizacionDecision.model_validate(state["priorizacion"])
    outputs = [str(o) for o in state.get("priorizacion_outputs") or []]
    deliverable = blob_location(outputs[-1]) if outputs else None
    if deliverable is None or decision.period is None:
        raise ValueError("priorización has no deliverable to package")
    history = [dict(h) for h in state.get("datamatch_history") or []]
    if not history:
        raise ValueError("no Datamatch step: the client base and matches are unknown")
    country, bottler = state.get("country", ""), state.get("bottler", "")
    # The state holds JSON values: counts come back as plain ints written by the loop
    matched = sum(int(str(h.get("clientes_con_match", 0))) for h in history)
    scored_local = deps.mirror_root / deliverable[1]
    scored_rows = deps.staging.count_rows(str(scored_local))
    label = bottler_folder(bottler).replace("_", " ").title()
    return GoldPackageRequest(
        scored_file=str(scored_local),
        clients_file=str(history[0]["clients_file"]),
        territory_geojson=str((state.get("inputs") or {}).get("geojson") or ""),
        out_dir=out_dir,
        bottler=bottler_folder(bottler),
        bottler_label=label,
        client_label=deps.gold_client_label.format(bottler=label),
        country=country,
        country_name=country_name(country),
        country_label=country_name(country).title(),
        period=decision.period,
        period_label=period_label(decision.period),
        clients_total=int(str(history[0]["clientes_inicio"])),
        dataplor_total=scored_rows + matched,
        matched=matched,
        run_name=state["run_id"],
        contacts=list(deps.gold_contacts),
        client_columns=ClientColumns(**deps.gold_client_columns),
    )


def make_stage_gold_package(deps: Dependencies) -> NodeFn:
    def stage_gold_package(state: CleaningState) -> Update:
        """Done when the package (KO / BOTTLER results, Excel, maps, deck) is in the gold
        mirror with its metadata + QA pages and queued for approval, or the QA failed."""
        today = datetime.now().strftime("%Y%m%d")  # same gold folder as the prospects
        prefix = layer_prefix(
            Layer.GOLD,
            state.get("country", ""),
            state.get("bottler", ""),
            today,
            deps.prospects_template,
        )
        out_dir = deps.mirror_root / prefix
        started = now_iso()
        try:
            request = _request(deps, state, out_dir)
            result = deps.gold_package.build(request)
        except GOLD_ERRORS as exc:
            # Full traceback in the log: the package touches many files and renderers
            _logger(state).exception("Gold package failed: %s", exc)
            return {"status": "failed", "error": f"Paquete gold: {exc}"}
        qa = package_qa(
            result.rows,
            result.ko_rows,
            result.bottler_rows,
            result.ko_column_names,
            result.prioritized,
        )
        if not qa["qa_ok"]:
            failed = [c["check"] for c in qa["checks"] if not c["ok"]]
            return {"status": "failed", "error": f"QA del paquete gold falló: {failed}"}

        alerts = (
            [
                (
                    "La base de clientes trae latitud y longitud intercambiadas: se corrigieron "
                    "para las distancias (área 300 m y cliente más cercano). Revisar la base y el "
                    "Datamatch del Front, que leyó las mismas columnas."
                )
            ]
            if result.client_coordinates_swapped
            else []
        )
        if alerts:
            _logger(state).warning(alerts[0])
        groups = (
            ("", result.root),
            ("results_ko", result.ko),
            ("results_bottler", result.bottler),
        )
        staged: dict[str, list[str]] = {}
        for folder, files in groups:
            sidecars: list[str] = []
            for path in files:
                stem = Path(path).stem
                metadata: dict[str, Any] = {
                    "origen": request.scored_file,
                    "archivo": Path(path).name,
                    "fecha": today,
                    "canal": state.get("channel"),
                    "analisis": "paquete_gold_prospeccion",
                    "audiencia": folder.replace("results_", "") or "ambas",
                    "#": {"total": result.rows, "utiles": result.ko_rows},
                    "% datos utiles": 100.0,
                    "por que se limpiaron": {},
                    "alertas": alerts,
                    "POR VERIFICAR": alerts,
                    "insumos": [request.scored_file, request.clients_file],
                    "capa": Layer.GOLD.value,
                    "destinos": [
                        f"{deps.dwh_container}/{prefix}/{folder + '/' if folder else ''}{Path(path).name}"
                    ],
                    "espejo_local": path,
                    "pais": state.get("country"),
                    "bottler": state.get("bottler"),
                    "periodo": request.period,
                    "run_id": state["run_id"],
                    "code_version": deps.lineage.code_version(),
                    "qa": qa,
                    "cifras": {
                        k: v
                        for k, v in result.figures.items()
                        if isinstance(v, (int, float, str))
                    },
                }
                sidecars += deps.staging.write_sidecars(
                    metadata,
                    Path(path).with_name(f"{stem}_metadata.json"),
                    Path(path).with_name(f"{stem}_qa.html"),
                )
            staged[folder] = [*files, *sidecars]

        lineage = record_stage(
            deps,
            state,
            "stage_gold_package",
            "Gold: paquete de entrega (KO, BOTTLER, Excel, mapas, deck)",
            started,
            [deps.lineage.describe(request.scored_file)],
            [deps.lineage.describe(p) for _, files in groups for p in files],
            {k: v for k, v in qa.items() if k != "checks"},
        )
        return {
            **lineage,
            "pending_upload": {
                "layer": Layer.GOLD.value,
                "files": staged[""],
                "container": deps.dwh_container,
                "blob_prefix": prefix,
                "copies": [],
                "extra": [
                    {
                        "files": staged[folder],
                        "container": deps.dwh_container,
                        "blob_prefix": f"{prefix}/{folder}",
                    }
                    for folder in ("results_ko", "results_bottler")
                ],
                "qa": dict(qa),
            },
        }

    return stage_gold_package

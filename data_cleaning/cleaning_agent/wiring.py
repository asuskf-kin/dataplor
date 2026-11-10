"""Composition root: the only place that binds ports to real adapters and config."""

from functools import partial
from pathlib import Path
from typing import Any

from cleaning_agent.adapters.azure_storage import AzureBlobStorage
from cleaning_agent.adapters.executive_report import FileExecutiveReport
from cleaning_agent.adapters.filesystem import FileSystemAudit, FileSystemDatasets
from cleaning_agent.adapters.layer_staging import FileLayerStaging
from cleaning_agent.adapters.lineage import FileLineage
from cleaning_agent.adapters.patterns_files import FilePatterns
from cleaning_agent.adapters.prefilters import (
    ClientProximityPrefilter,
    TerritoryPrefilter,
)
from cleaning_agent.adapters.priorizacion import PriorizacionSubprocess
from cleaning_agent.adapters.qa_datamatch import QADatamatchSubprocess
from cleaning_agent.application.cleaning_catalog import catalog_for
from cleaning_agent.application.graph.nodes import Dependencies
from cleaning_agent.domain.models import CleaningMode
from cleaning_agent.settings import (
    AGENT_SETTINGS,
    AZURE_SETTINGS,
    CLIENT_SETTINGS,
    DATA_DIR,
    DATAMATCH_SETTINGS,
    DWH_SETTINGS,
    NIGHTLIFE_SETTINGS,
    PRIORIZACION_SETTINGS,
    PROJECT_ROOT,
    RAW_SETTINGS,
    REPORT_SETTINGS,
    TERRITORY_SETTINGS,
)


def form_defaults() -> dict[CleaningMode, dict[str, Any]]:
    # raw_csv / output_csv / parquet are filled from the intake of each run
    return {
        CleaningMode.GEOJSON: dict(TERRITORY_SETTINGS),
        CleaningMode.CLIENTES_BOTTLER: dict(CLIENT_SETTINGS),
        CleaningMode.NINGUNO: {},
    }


def checkpoints_path() -> Path:
    path = PROJECT_ROOT / str(AGENT_SETTINGS["checkpoints"])
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def default_dependencies() -> Dependencies:
    return Dependencies(
        prefilters={
            CleaningMode.GEOJSON: TerritoryPrefilter(PROJECT_ROOT),
            CleaningMode.CLIENTES_BOTTLER: ClientProximityPrefilter(PROJECT_ROOT),
        },
        datasets=FileSystemDatasets(
            PROJECT_ROOT, DATA_DIR, PROJECT_ROOT / str(AGENT_SETTINGS["runs_dir"])
        ),
        audit=FileSystemAudit(DATA_DIR),
        qa=QADatamatchSubprocess(
            PROJECT_ROOT,
            (PROJECT_ROOT / str(DATAMATCH_SETTINGS["qa_project_dir"])).resolve(),
            PROJECT_ROOT / str(AGENT_SETTINGS["runs_dir"]),
            timeout_s=float(DATAMATCH_SETTINGS["qa_timeout_s"]),
        ),
        lineage=FileLineage(PROJECT_ROOT),
        executive_report=FileExecutiveReport(
            PROJECT_ROOT,
            DATA_DIR / "dropped",
            PROJECT_ROOT / str(REPORT_SETTINGS["carpeta"]),
            str(REPORT_SETTINGS["nombre"]),
        ),
        priorizacion=PriorizacionSubprocess(
            (PROJECT_ROOT / str(PRIORIZACION_SETTINGS["repo_dir"])).resolve(),
            PROJECT_ROOT / str(AGENT_SETTINGS["runs_dir"]),
            timeout_s=float(PRIORIZACION_SETTINGS["timeout_s"]),
        ),
        modules_for=partial(catalog_for, nightlife=NIGHTLIFE_SETTINGS),
        raw_container=str(RAW_SETTINGS["container"]),
        raw_local_dir=PROJECT_ROOT / str(RAW_SETTINGS["local_dir"]),
        staging=FileLayerStaging(),
        patterns=FilePatterns(
            PROJECT_ROOT, PROJECT_ROOT / "cleaning_agent" / "domain" / "patterns"
        ),
        dwh_container=str(DWH_SETTINGS["container"]),
        dwh_path_template=str(DWH_SETTINGS["path_template"]),
        mirror_root=PROJECT_ROOT / str(DWH_SETTINGS["mirror_dir"]),
        runs_dir=PROJECT_ROOT / str(AGENT_SETTINGS["runs_dir"]),
        storage=AzureBlobStorage(
            timeout_s=float(AZURE_SETTINGS["timeout_s"]),
            max_attempts=int(AZURE_SETTINGS["max_attempts"]),
        ),
        defaults=form_defaults(),
        default_modules=[int(m) for m in AGENT_SETTINGS["default_modules"]],
        items_to_track=[str(i) for i in AGENT_SETTINGS["items_to_track"]],
        max_attempts=int(AGENT_SETTINGS["max_input_attempts"]),
        front_url=str(DATAMATCH_SETTINGS["front_url"]),
        datamatch_defaults={
            "clients_file": str(DATAMATCH_SETTINGS["clients_file"]),
            "thresholds": dict(DATAMATCH_SETTINGS["thresholds"]),
        },
        upload_defaults={
            "container": str(AZURE_SETTINGS["container"]),
            "blob_prefix": str(AZURE_SETTINGS["blob_prefix"]),
        },
    )

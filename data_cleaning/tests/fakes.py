"""In-memory adapters for the ports: the graph runs end to end without real data."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl

from cleaning_agent.application.cleaning_catalog import CleaningModule
from cleaning_agent.application.graph.nodes import Dependencies
from cleaning_agent.domain.lineage import ArtifactRef, StageRecord
from cleaning_agent.domain.models import (
    CleaningMode,
    DatamatchInputs,
    ExecutiveReportOutcome,
    GeojsonInputs,
    OutputPaths,
    PrefilterResult,
    PriorizacionResult,
    QAExploreResult,
    QARunResult,
    StepMetric,
    UploadResult,
)
from cleaning_agent.domain.patterns_policy import PatternsStatus


def sample_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "dataplor_id": ["a", "b", "c", "d"],
            "name": ["TIENDA A", "OXXO", "TIENDA C", "TIENDA D"],
            "latitude": [19.1, 19.2, 19.3, 19.4],
            "longitude": [-103.1, -103.2, -103.3, -103.4],
        }
    )


@dataclass
class FakeDatasets:
    files: set[str] = field(default_factory=set)
    inputs: dict[str, pl.DataFrame] = field(default_factory=dict)
    steps: dict[str, pl.DataFrame] = field(default_factory=dict)
    published: dict[str, pl.DataFrame] = field(default_factory=dict)
    drops: list[str] = field(default_factory=list)
    cleared: int = 0

    def exists(self, path: str) -> bool:
        return path in self.files

    def matches(self, pattern: str) -> list[str]:
        prefix = pattern.split("*")[0]
        return sorted(
            f for f in self.files if f.startswith(prefix) and f.endswith(".parquet")
        )

    def load_input(self, raw_csv: str) -> pl.DataFrame:
        if raw_csv not in self.inputs:
            raise FileNotFoundError(raw_csv)
        return self.inputs[raw_csv]

    def save_step(self, run_id: str, file_stem: str, df: pl.DataFrame) -> str:
        key = f"{run_id}/{file_stem}"
        self.steps[key] = df
        return key

    def load_step(self, path: str) -> pl.DataFrame:
        return self.steps[path]

    def save_dropped(
        self,
        before: pl.DataFrame,
        after: pl.DataFrame,
        file_stem: str,
        dropped: pl.DataFrame | None,
    ) -> None:
        self.drops.append(file_stem)

    def clear_previous_drops(self) -> None:
        self.cleared += 1

    def publish(self, df: pl.DataFrame, output_csv: str) -> str:
        self.published[output_csv] = df
        return output_csv


@dataclass
class FakeAudit:
    steps: list[str] = field(default_factory=list)
    finished: bool = False

    def start(self, items_to_track: list[str]) -> str | None:
        return "audit.txt" if items_to_track else None

    def write_step(self, audit_file: str | None, title: str, text: str) -> None:
        self.steps.append(title)

    def finish(
        self, audit_file: str | None, final_df: pl.DataFrame, items_to_track: list[str]
    ) -> None:
        self.finished = True

    def html_report(self, metrics: list[StepMetric]) -> Path | None:
        return Path("report.html") if metrics else None


@dataclass
class FakePrefilter:
    datasets: FakeDatasets
    error: Exception | None = None
    calls: list[str] = field(default_factory=list)

    def run(self, inputs: OutputPaths, correlation_id: str) -> PrefilterResult:
        self.calls.append(correlation_id)
        if self.error:
            raise self.error
        # Like the real adapters: the pre-filter produces raw_csv for load_input
        self.datasets.inputs[inputs.raw_csv] = sample_df()
        # Same counter names as the real pre-filters, so the bronze QA adds up
        kept_key, out_key = (
            ("inside_territory", "outside_territory")
            if isinstance(inputs, GeojsonInputs)
            else ("near_client", "far_from_client")
        )
        counts = {
            "rows_read": 10,
            "invalid_coordinates": 1,
            "dropped_by_status": 2,
            out_key: 3,
            kept_key: 4,
        }
        return PrefilterResult(output_csv=inputs.raw_csv, counts=counts)


@dataclass
class FakeQA:
    error: Exception | None = None
    runs: list[tuple[float, float]] = field(default_factory=list)

    def explore(self, inputs: DatamatchInputs, run_id: str) -> QAExploreResult:
        if self.error:
            raise self.error
        return QAExploreResult(
            report_html=f"{run_id}/threshold_report.html", output_dir=run_id
        )

    def run(
        self, inputs: DatamatchInputs, run_id: str, match: float, super_match: float
    ) -> QARunResult:
        self.runs.append((match, super_match))
        return QARunResult(
            files=[f"{run_id}/Datamatch_Final_{inputs.client_name}.csv"],
            output_dir=run_id,
        )


@dataclass
class FakeStorage:
    configured: bool = True
    error: Exception | None = None
    uploads: list[tuple[list[str], str, str]] = field(default_factory=list)

    def is_configured(self) -> bool:
        return self.configured

    blobs: list[str] = field(default_factory=list)
    downloads: list[tuple[str, str]] = field(default_factory=list)

    def list_blobs(self, container: str, pattern: str) -> list[str]:
        prefix = pattern.split("*")[0]
        return [b for b in self.blobs if b.startswith(prefix)]

    def download(
        self,
        container: str,
        pattern: str,
        local_dir: Path,
        progress: Any = None,
    ) -> list[str]:
        self.downloads.append((container, pattern))
        if progress:
            progress(pattern, 10, 10)
        return [
            str(local_dir / Path(b).name) for b in self.list_blobs(container, pattern)
        ]

    def upload(self, files: list[str], container: str, prefix: str) -> UploadResult:
        if self.error:
            raise self.error
        self.uploads.append((files, container, prefix))
        return UploadResult(
            uploaded=[f"{container}/{prefix}/{Path(f).name}" for f in files]
        )


@dataclass
class FakeLineage:
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)

    def code_version(self) -> str:
        return "abc1234"

    def describe(self, path: str, rows: int | None = None) -> ArtifactRef:
        return ArtifactRef(path=path, rows=rows, bytes=10, sha256="0" * 64)

    def write_sidecars(self, record: StageRecord) -> list[str]:
        return [f"{o.path}_metadata.json" for o in record.outputs]

    def write_document(self, document: dict[str, Any], path: Path) -> str:
        self.documents[str(path)] = document
        return str(path)


@dataclass
class FakeExecutiveReport:
    error: Exception | None = None
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def generate(
        self,
        raw_csv: str,
        output_csv: str,
        country: str,
        bottler: str,
        premise: str,
        correlation_id: str,
    ) -> ExecutiveReportOutcome:
        if self.error:
            raise self.error
        self.calls.append(
            (raw_csv, output_csv, country, bottler, premise, correlation_id)
        )
        return ExecutiveReportOutcome(
            files=[f"reports/reporte_{country}_{bottler}.html"],
            summary={"final_rows": 2},
        )


@dataclass
class FakePriorizacion:
    def list_configs(self) -> list[str]:
        return ["mexico_cdf.yaml"]

    def build_config(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"run": {"name": "x"}}

    def run(self, config: dict[str, Any], run_id: str) -> PriorizacionResult:
        return PriorizacionResult(config_path="cfg.yaml", outputs=[])


@dataclass
class FakeStaging:
    rows: int | None = None
    mirrored: list[str] = field(default_factory=list)
    metadata: list[dict[str, Any]] = field(default_factory=list)

    def count_rows(self, path: str) -> int:
        return self.rows if self.rows is not None else 4

    def mirror(self, source: str, target: Path) -> str:
        self.mirrored.append(str(target))
        return str(target)

    def write_sidecars(
        self, metadata: dict[str, Any], json_path: Path, html_path: Path
    ) -> list[str]:
        self.metadata.append(metadata)
        return [str(json_path), str(html_path)]


@dataclass
class FakePatterns:
    exists: bool = True
    updated: str | None = "2099-01-01"
    chains: int = 5
    reloads: int = 0

    def path(self, country: str) -> Path:
        return Path(f"patterns_{country}.py")

    def status(self, country: str) -> PatternsStatus:
        return PatternsStatus(
            country=country,
            path=str(self.path(country)),
            exists=self.exists,
            updated=self.updated,
            source="PATTERNS_UPDATED",
        )

    def reload(self, country: str) -> int:
        self.reloads += 1
        return self.chains


def _drop_chains(df: pl.DataFrame, items: list[str]) -> tuple[Any, ...]:
    kept = df.filter(pl.col("name") != "OXXO")
    return kept, items, "removed chains", df.filter(pl.col("name") == "OXXO")


def _drop_last(df: pl.DataFrame, items: list[str]) -> tuple[Any, ...]:
    return df.head(df.height - 1), items, None


FAKE_MODULES = {
    0: CleaningModule(
        0, "Fake 0: nightlife", "00_fake", lambda df, items: (df, items, None)
    ),
    1: CleaningModule(1, "Fake 1: chains", "01_fake", _drop_chains),
    2: CleaningModule(2, "Fake 2: drop last", "02_fake", _drop_last),
    5: CleaningModule(
        5, "Fake 5: regex", "05_fake", lambda df, items: (df, items, None)
    ),
}

RAW = "data/raw/mx/femsa/part-*.parquet"
INTAKE = {
    "country": "mx",
    "bottler": "Femsa",
    "channel": "tradicional",
    "premise": "on_premise",
    "dataplor_raw": RAW,
}
CLEANING = {
    "geojson": {"clean": True, "type": "distancia"},
    "clientes_bottler": {"clean": True, "type": "client_bottler"},
    "ninguno": {"clean": False},
}

PATHS = {
    "raw_csv": "data/raw/mx/femsa/dataplor_cleaned.csv",
    "output_csv": "data/processed/mx/femsa/dataplor_final_pipeline_output_mx_on_premise.csv",
}
GEO = {
    "parquet": "data/raw/mx/femsa/part-*.parquet",
    "geojson": "data/raw/mx/femsa/territorio.geojson",
    **PATHS,
}
CLIENTS = {
    "parquet": "data/raw/mx/femsa/part-*.parquet",
    "clients_csv": "data/raw/mx/femsa/clientes.csv",
    **PATHS,
}


DATAMATCH_FILE = "data/front/final_output.csv"
FRONT_RESULT = "data/front/dataplor_front_result.csv"
FRONT_JSON = "data/front/dataplor_front_result.json"
CLIENTS_FILE = "data/raw/mx/femsa/clientes.csv"


def make_deps(
    prefilter_error: Exception | None = None,
    qa: FakeQA | None = None,
    storage: FakeStorage | None = None,
) -> tuple[Dependencies, FakeDatasets, FakeAudit, FakePrefilter]:
    datasets = FakeDatasets(
        files={
            "data/raw/mx/femsa/part-00000.parquet",
            "data/raw/mx/femsa/territorio.geojson",
            "data/raw/mx/femsa/clientes.csv",
            DATAMATCH_FILE,
            FRONT_RESULT,
            FRONT_JSON,
        },
        inputs={FRONT_RESULT: sample_df()},
    )
    audit = FakeAudit()
    prefilter = FakePrefilter(datasets, error=prefilter_error)
    deps = Dependencies(
        prefilters={
            CleaningMode.GEOJSON: prefilter,
            CleaningMode.CLIENTES_BOTTLER: prefilter,
        },
        datasets=datasets,
        audit=audit,
        qa=qa or FakeQA(),
        storage=storage or FakeStorage(),
        lineage=FakeLineage(),
        executive_report=FakeExecutiveReport(),
        priorizacion=FakePriorizacion(),
        staging=FakeStaging(),
        patterns=FakePatterns(),
        defaults={
            CleaningMode.GEOJSON: GEO,
            CleaningMode.CLIENTES_BOTTLER: CLIENTS,
            CleaningMode.NINGUNO: PATHS,
        },
        default_modules=[1, 2],
        items_to_track=["TIENDA A"],
        max_attempts=2,
        modules_for=lambda country: FAKE_MODULES,
        supported_countries=lambda: ["mx", "pe"],
        front_url="https://front.example/home",
        datamatch_defaults={
            "clients_file": CLIENTS_FILE,
            "thresholds": {"match": 0.71, "super_match": 0.8},
        },
        upload_defaults={
            "container": "prospeccion",
            "blob_prefix": "p/{country}/{bottler}",
        },
    )
    return deps, datasets, audit, prefilter


def begin(app: Any, thread_id: str, mode: str) -> dict[str, Any]:
    """Starts a run and answers the intake and '¿Va a limpiar el Dataplor?'."""
    from cleaning_agent.entrypoints.cli import run_resume, run_start

    run_start(app, thread_id)
    view = run_resume(app, thread_id, dict(INTAKE))
    assert (view.get("interrupt") or {}).get("kind") == "choose_cleaning", view
    return run_resume(app, thread_id, dict(CLEANING[mode]))


def answer_layer_and_front(
    resume: Any, app: Any, thread_id: str, view: dict[str, Any]
) -> dict[str, Any]:
    """Approves bronze and answers the Front step, for tests about later steps."""
    kind = (view.get("interrupt") or {}).get("kind")
    if kind == "confirm_layer_upload":
        view = resume(app, thread_id, {"approved": True})
        kind = (view.get("interrupt") or {}).get("kind")
    if kind == "front_dataplor":
        view = resume(
            app, thread_id, {"result_file": FRONT_RESULT, "metadata_json": FRONT_JSON}
        )
    return view

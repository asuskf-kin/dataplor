"""In-memory adapters for the ports: the graph runs end to end without real data."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl

from cleaning_agent.application.cleaning_catalog import CleaningModule
from cleaning_agent.application.graph.nodes import Dependencies
from cleaning_agent.domain.cleaning.lodging_filter import remove_lodging_rentals
from cleaning_agent.domain.datamatch_steps import LODGING_FILE_SUFFIX
from cleaning_agent.domain.lineage import ArtifactRef, StageRecord
from cleaning_agent.domain.models import (
    CleaningMode,
    DatamatchInputs,
    DatamatchStepResult,
    ExecutiveReportOutcome,
    GeojsonInputs,
    GoldPackageRequest,
    GoldPackageResult,
    OutputPaths,
    PrefilterResult,
    PriorizacionResult,
    ProspectionQaPrepared,
    ProspectionQaResult,
    ProspectionQaReview,
    ProspectsResult,
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

    def html_report(self, metrics: list[StepMetric], out_dir: Path) -> Path | None:
        return out_dir / "report.html" if metrics else None


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

    def explore(
        self, inputs: DatamatchInputs, run_id: str, output_dir: Path
    ) -> QAExploreResult:
        if self.error:
            raise self.error
        return QAExploreResult(
            report_html=str(output_dir / "threshold_report.html"),
            output_dir=str(output_dir),
        )

    def run(
        self,
        inputs: DatamatchInputs,
        run_id: str,
        match: float,
        super_match: float,
        output_dir: Path,
    ) -> QARunResult:
        self.runs.append((match, super_match))
        return QARunResult(
            files=[str(output_dir / f"Datamatch_Final_{inputs.client_name}.csv")],
            output_dir=str(output_dir),
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

    existing: list[str] = field(default_factory=list)

    def upload(
        self, files: list[str], container: str, prefix: str, replace: bool = False
    ) -> UploadResult:
        from cleaning_agent.domain.storage_errors import BlobExistsError

        clash = [f for f in files if Path(f).name in self.existing]
        if clash and not replace:
            raise BlobExistsError(f"{container}/{prefix}/{Path(clash[0]).name}")
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

    def read_decisions(self, path: Path) -> list[dict[str, Any]]:
        return []


@dataclass
class FakeExecutiveReport:
    error: Exception | None = None
    with_xlsx: bool = False
    # The real report also writes the channel CSV without franchises (silver)
    with_csv: bool = False
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def generate(
        self,
        raw_csv: str,
        output_csv: str,
        country: str,
        bottler: str,
        premise: str,
        correlation_id: str,
        out_dir: Path,
        xlsx_dir: Path,
        known_clients: dict[str, str] | None = None,
        known_step: str | None = None,
        lodging_rentals: dict[str, str] | None = None,
        upstream: list[tuple[str, int]] | None = None,
    ) -> ExecutiveReportOutcome:
        self.upstream = upstream
        if self.error:
            raise self.error
        self.calls.append(
            (raw_csv, output_csv, country, bottler, premise, correlation_id)
        )
        csv = out_dir / f"dataplor_{country}_{bottler}_sin_franquicias.csv"
        if self.with_csv:
            csv.parent.mkdir(parents=True, exist_ok=True)
            csv.write_text("id,name\n1,a\n", encoding="utf-8")
        return ExecutiveReportOutcome(
            files=([str(csv)] if self.with_csv else [])
            + [str(out_dir / f"reporte_{country}_{bottler}.html")]
            + (
                [str(xlsx_dir / f"reporte_{country}_{bottler}.xlsx")]
                if self.with_xlsx
                else []
            ),
            summary={"final_rows": 2},
        )


@dataclass
class FakePriorizacion:
    storage: Any = None  # outputs land "in Azure" so the staging step can mirror them
    runs: list[Any] = field(default_factory=list)
    configs: list[str] = field(
        default_factory=lambda: ["mexico_cdf.yaml", "mexico_golfo.yaml"]
    )

    def list_configs(self) -> list[str]:
        return list(self.configs)

    def build_config(self, base_config: str, run: Any) -> dict[str, Any]:
        self.runs.append(run)
        return {"run": {"name": run.run_name}, "agent_run": run}

    def run(self, config: dict[str, Any], run_id: str) -> PriorizacionResult:
        run = config["agent_run"]
        blobs = [f"{run.output_dir}/{n}.csv" for n in (run.step1_name, run.step2_name)]
        if self.storage is not None:
            self.storage.blobs.extend(blobs)
        return PriorizacionResult(
            config_path="cfg.yaml",
            outputs=[f"{run.output_container}/{b}" for b in blobs],
        )


@dataclass
class FakeStaging:
    rows: int | None = None
    mirrored: list[str] = field(default_factory=list)
    metadata: list[dict[str, Any]] = field(default_factory=list)

    written: dict[str, int] = field(default_factory=dict)

    def count_rows(self, path: str) -> int:
        if self.rows is not None:
            return self.rows
        return self.written.get(path, 4)

    # Files "on disk" per layer folder name ("silver", "gold"), for list_files
    on_disk: dict[str, list[str]] = field(default_factory=dict)

    def list_files(self, directory: Path) -> list[str]:
        layer = directory.parts[len(Path("data").parts)] if directory.parts else ""
        return list(self.on_disk.get(layer, []))

    copied: list[str] = field(default_factory=list)

    def copy(self, source: str, target_dir: Path) -> str:
        target = str(target_dir / Path(source).name)
        self.copied.append(target)
        return target

    def columns(self, path: str) -> list[str]:
        from cleaning_agent.domain.priorizacion import GEO_COLUMNS

        return ["dataplor_id", *GEO_COLUMNS]

    def write_parquet(self, df: pl.DataFrame, target: Path) -> str:
        self.written[str(target)] = df.height
        return str(target)

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
    # The real module 7: it always runs (Airbnb / rented flats)
    7: CleaningModule(7, "Module 7: Airbnb", "07_fake", remove_lodging_rentals),
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
    storage = storage or FakeStorage()
    deps = Dependencies(
        prefilters={
            CleaningMode.GEOJSON: prefilter,
            CleaningMode.CLIENTES_BOTTLER: prefilter,
        },
        datasets=datasets,
        audit=audit,
        qa=qa or FakeQA(),
        storage=storage,
        lineage=FakeLineage(),
        executive_report=FakeExecutiveReport(),
        priorizacion=FakePriorizacion(storage=storage),
        staging=FakeStaging(),
        patterns=FakePatterns(),
        datamatch_steps=FakeDatamatchSteps(),
        gold_package=FakeGoldPackage(),
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
        kind = (view.get("interrupt") or {}).get("kind")
    if kind == "franchise_review":
        # Tests about later steps: Claude found no franchise left
        view = resume(app, thread_id, {"flagged": []})
        kind = (view.get("interrupt") or {}).get("kind")
    if kind == "datamatch_loop":
        # Tests about later steps: one Datamatch step is enough, prospecting continues
        view = resume(app, thread_id, {"done": True})
    return view


@dataclass
class FakeGoldPackage:
    requests: list[GoldPackageRequest] = field(default_factory=list)
    leak_name: bool = False  # the KO file wrongly carries the name column

    def build_maps(self, request: GoldPackageRequest) -> list[str]:
        self.requests.append(request)
        names = request.names()
        return [
            str(request.out_dir / "results_ko" / names["ko_map"]),
            str(request.out_dir / "results_bottler" / names["bottler_map"]),
        ]

    def build(self, request: GoldPackageRequest) -> GoldPackageResult:
        self.requests.append(request)
        out, names = request.out_dir, request.names()
        ko_columns = ["poi_ref", "prioridad", *(["name"] if self.leak_name else [])]
        return GoldPackageResult(
            root=[str(out / names["xlsx"]), str(out / names["deck"])],
            ko=[
                str(out / "results_ko" / names["ko_csv"]),
                str(out / "results_ko" / names["ko_map"]),
            ],
            bottler=[
                str(out / "results_bottler" / names["bottler_csv"]),
                str(out / "results_bottler" / names["bottler_map"]),
            ],
            rows=4,
            ko_rows=4,
            bottler_rows=4,
            ko_column_names=ko_columns,
            bottler_columns=47,
            prioritized=4,
            figures={"hm_total": 3},
        )


@dataclass
class FakeDatamatchSteps:
    error: Exception | None = None
    calls: list[tuple[str, str, float, int]] = field(default_factory=list)
    prospects: list[tuple[str, list[str], str]] = field(default_factory=list)
    known_in_file: int | None = None
    false_negatives: dict[str, str] = field(default_factory=dict)

    def build_prospects(
        self,
        cleaned_file: str,
        match_files: list[str],
        target: Path,
        excluded_states: list[str] | None = None,
        false_negatives: Mapping[str, str] | None = None,
    ) -> ProspectsResult:
        self.prospects.append((cleaned_file, match_files, str(target)))
        self.false_negatives = dict(false_negatives or {})
        known = 10 * len(match_files)
        removed = len(self.false_negatives)
        # One rented flat removed, with its CSV next to the prospects (uploaded after
        # them: priorización must still read the prospects)
        lodging = target.with_name(f"{target.stem}{LODGING_FILE_SUFFIX}.csv")
        return ProspectsResult(
            file=str(target),
            known_ids=known,
            known_in_file=known if self.known_in_file is None else self.known_in_file,
            rows_in=100,
            rows_out=100 - known - 1 - removed,
            false_negatives=self.false_negatives,
            lodging_rentals={"dp-depto": "depto"},
            lodging_file=str(lodging),
        )

    def close_cycle_report(
        self,
        report_dir: Path,
        client_name: str,
        history: list[dict[str, Any]],
        lodging_removed: int,
        prospects_left: int,
    ) -> list[str]:
        return []

    def run(
        self,
        inputs: DatamatchInputs,
        out_dir: Path,
        report_dir: Path,
        folder: str,
        threshold: float,
        history: list[dict[str, Any]],
        correlation_id: str,
    ) -> DatamatchStepResult:
        if self.error:
            raise self.error
        self.calls.append((str(out_dir), folder, threshold, len(history)))
        clients = out_dir / f"clients_bottler_{inputs.client_name.lower()}_{folder}.csv"
        start = int(history[-1]["clientes_restantes"]) if history else 100
        return DatamatchStepResult(
            files=[str(clients), str(report_dir / "qa_process_report.xlsx")],
            clients_file=str(clients),
            summary={
                "paso": folder,
                "clientes_inicio": start,
                "clientes_con_match": 10,
                "clientes_restantes": start - 10,
                "pct_encontrado": 10.0,
                "umbral_limpieza": threshold,
                "cuadra": True,
                "nuevo_client_bottler": clients.name,
                "datamatch_file": inputs.datamatch_file,
                "clients_file": inputs.clients_file,
            },
        )


@dataclass
class FakeProspectionQa:
    """Two false negatives (one Dataplor id per reason) unless ``mistakes`` says otherwise."""

    mistakes: dict[str, str] = field(
        default_factory=lambda: {"dp-fn1": "both_strong", "dp-fn2": "name_dominant"}
    )
    error: Exception | None = None
    reviews: list[ProspectionQaReview] = field(default_factory=list)
    prepared_with: list[dict[str, Any]] = field(default_factory=list)

    def prepare(
        self,
        cleaned_file: str,
        match_files: list[str],
        excluded_states: list[str],
        clients_file: str,
        client_cols: Mapping[str, str],
        dataplor_cols: Mapping[str, str],
        out_dir: Path,
    ) -> ProspectionQaPrepared:
        if self.error:
            raise self.error
        self.prepared_with.append(
            {"clients_file": clients_file, "match_files": match_files, "client_cols": dict(client_cols)}
        )
        return ProspectionQaPrepared(
            out_dir=str(out_dir),
            match=20,
            no_match=79,
            clients=30,
            mistakes=len(self.mistakes),
            by_reason={"both_strong": 1, "name_dominant": 1, "proximity_dominant": 0},
            categories_file=str(out_dir / "categories_for_review.json"),
            mistakes_file=str(out_dir / "mistakes_report.csv"),
            mistake_ids=dict(self.mistakes),
        )

    def build(
        self,
        prepared: ProspectionQaPrepared,
        review: ProspectionQaReview,
        client: str,
        country: str,
        dataplor_cols: Mapping[str, str],
    ) -> ProspectionQaResult:
        self.reviews.append(review)
        out = Path(prepared.out_dir)
        return ProspectionQaResult(
            report=str(out / f"prospection_qa_report_{client}.html"),
            local_files=[str(out / "no_match_enriched.xlsx")],
            summary={"falsos_negativos": prepared.mistakes, "veredicto": "insufficient"},
        )

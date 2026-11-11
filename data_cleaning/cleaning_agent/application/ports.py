"""Ports: what the graph needs from the outside world, as Protocols.

The graph depends only on these. ``adapters/`` implements them against the file
system; tests swap in in-memory fakes, so the whole flow runs without real data.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import polars as pl

from cleaning_agent.domain.lineage import ArtifactRef, StageRecord
from cleaning_agent.domain.models import (
    DatamatchInputs,
    DatamatchStepResult,
    ExecutiveReportOutcome,
    GoldPackageRequest,
    GoldPackageResult,
    OutputPaths,
    PrefilterResult,
    PriorizacionResult,
    PriorizacionRun,
    ProspectsResult,
    QAExploreResult,
    QARunResult,
    StepMetric,
    UploadResult,
)
from cleaning_agent.domain.patterns_policy import PatternsStatus


class PrefilterPort(Protocol):
    """Narrows the raw Dataplor export into the CSV the cleaning modules read."""

    def run(self, inputs: OutputPaths, correlation_id: str) -> PrefilterResult: ...


class DatasetPort(Protocol):
    """Reads and writes the datasets of one run."""

    def exists(self, path: str) -> bool: ...

    def matches(self, pattern: str) -> list[str]: ...

    def load_input(self, raw_csv: str) -> pl.DataFrame: ...

    def save_step(self, run_id: str, file_stem: str, df: pl.DataFrame) -> str: ...

    def load_step(self, path: str) -> pl.DataFrame: ...

    def save_dropped(
        self,
        before: pl.DataFrame,
        after: pl.DataFrame,
        file_stem: str,
        dropped: pl.DataFrame | None,
    ) -> None: ...

    def clear_previous_drops(self) -> None: ...

    def publish(self, df: pl.DataFrame, output_csv: str) -> str: ...


class AuditPort(Protocol):
    """Audit trail of a run: tracked-items text file and the HTML drop report."""

    def start(self, items_to_track: list[str]) -> str | None: ...

    def write_step(self, audit_file: str | None, title: str, text: str) -> None: ...

    def finish(
        self, audit_file: str | None, final_df: pl.DataFrame, items_to_track: list[str]
    ) -> None: ...

    def html_report(self, metrics: list[StepMetric], out_dir: Path) -> Path | None: ...


class DatamatchQAPort(Protocol):
    """QA of the Datamatch done in the Front (today: the QA_datamatch project)."""

    def explore(
        self, inputs: DatamatchInputs, run_id: str, output_dir: Path
    ) -> QAExploreResult: ...

    def run(
        self,
        inputs: DatamatchInputs,
        run_id: str,
        match: float,
        super_match: float,
        output_dir: Path,
    ) -> QARunResult: ...


class StoragePort(Protocol):
    """Remote storage for the deliverables (today: Azure Blob Storage)."""

    def is_configured(self) -> bool: ...

    def upload(
        self, files: list[str], container: str, prefix: str, replace: bool = False
    ) -> UploadResult: ...

    def list_blobs(self, container: str, pattern: str) -> list[str]: ...

    def download(
        self,
        container: str,
        pattern: str,
        local_dir: Path,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> list[str]: ...


class LineagePort(Protocol):
    """Describes artifacts (hash, size) and persists the lineage JSON files."""

    def code_version(self) -> str: ...

    def describe(self, path: str, rows: int | None = None) -> ArtifactRef: ...

    def write_sidecars(self, record: StageRecord) -> list[str]: ...

    def write_document(self, document: dict[str, Any], path: Path) -> str: ...


class ExecutiveReportPort(Protocol):
    """Executive report of the cleaning (HTML, PDF, Excel), formerly report.ipynb."""

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
    ) -> ExecutiveReportOutcome: ...


class PriorizacionPort(Protocol):
    """On-premise prioritisation (today: the Priorizacion_On_Premise_code repo)."""

    def list_configs(self) -> list[str]: ...

    def build_config(
        self, base_config: str, run: PriorizacionRun
    ) -> dict[str, Any]: ...

    def run(self, config: dict[str, Any], run_id: str) -> PriorizacionResult: ...


class LayerStagingPort(Protocol):
    """Local mirror of the DWH and the QA sidecars of each layer file."""

    def count_rows(self, path: str) -> int: ...

    def columns(self, path: str) -> list[str]: ...

    def mirror(self, source: str, target: Path) -> str: ...

    def write_parquet(self, df: pl.DataFrame, target: Path) -> str: ...

    def list_files(self, directory: Path) -> list[str]: ...

    def copy(self, source: str, target_dir: Path) -> str: ...

    def write_sidecars(
        self, metadata: dict[str, Any], json_path: Path, html_path: Path
    ) -> list[str]: ...


class DatamatchStepPort(Protocol):
    """One step of the Datamatch loop: drop the matched clients, report, stage files."""

    def run(
        self,
        inputs: DatamatchInputs,
        out_dir: Path,
        report_dir: Path,
        folder: str,
        threshold: float,
        history: list[dict[str, Any]],
        correlation_id: str,
    ) -> DatamatchStepResult: ...

    def build_prospects(
        self, cleaned_file: str, match_files: list[str], target: Path
    ) -> ProspectsResult: ...


class GoldPackagePort(Protocol):
    """Gold delivery package: KO / BOTTLER results, opportunity Excel, maps, deck."""

    def build(self, request: GoldPackageRequest) -> GoldPackageResult: ...


class PatternsPort(Protocol):
    """Country chain-pattern files and when they were last updated."""

    def path(self, country: str) -> Path: ...

    def status(self, country: str) -> PatternsStatus: ...

    def reload(self, country: str) -> int: ...

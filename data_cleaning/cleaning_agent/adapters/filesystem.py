"""File-system adapters for DatasetPort and AuditPort.

Intermediate steps are Parquet files under ``data/runs/<run_id>/``: they keep the
column types between modules and let a crashed run resume from the last step.
"""

import logging
from glob import glob
from pathlib import Path

import pandas as pd
import polars as pl

from cleaning_agent.adapters.audit_file import (
    finalize_audit_report,
    init_audit_file,
    write_audit_step,
)
from cleaning_agent.adapters.drop_report import generate_html_report
from cleaning_agent.adapters.drop_tracker import save_dropped_records
from cleaning_agent.domain.models import StepMetric

logger = logging.getLogger(__name__)


def resolve(project_root: Path, path: str) -> Path:
    """Relative paths are relative to the project root (as in config.yaml)."""
    candidate = Path(path)
    return candidate if candidate.is_absolute() else project_root / candidate


class FileSystemDatasets:
    def __init__(self, project_root: Path, data_dir: Path, runs_dir: Path) -> None:
        self.project_root = project_root
        self.data_dir = data_dir
        self.runs_dir = runs_dir

    def exists(self, path: str) -> bool:
        return resolve(self.project_root, path).is_file()

    def matches(self, pattern: str) -> list[str]:
        resolved = resolve(self.project_root, pattern)
        return sorted(match for match in glob(str(resolved)) if Path(match).is_file())

    def load_input(self, raw_csv: str) -> pl.DataFrame:
        path = resolve(self.project_root, raw_csv)
        if path.suffix.lower() == ".parquet":
            # Raw Dataplor exports store every column as text; the spatial modules
            # need numeric coordinates, as the CSV reader below infers them
            df = pl.read_parquet(self.matches(raw_csv) or [str(path)])
            return df.with_columns(
                pl.col(c).cast(pl.Float64, strict=False)
                for c in ("latitude", "longitude")
                if c in df.columns
            )
        # Same reader the legacy main.py used, so module behaviour (type inference)
        # does not change with the new orchestration
        return pl.from_pandas(pd.read_csv(path, low_memory=False, encoding="utf-8"))

    def save_step(self, run_id: str, file_stem: str, df: pl.DataFrame) -> str:
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{file_stem}.parquet"
        df.write_parquet(path)
        return str(path)

    def load_step(self, path: str) -> pl.DataFrame:
        return pl.read_parquet(path)

    def save_dropped(
        self,
        before: pl.DataFrame,
        after: pl.DataFrame,
        file_stem: str,
        dropped: pl.DataFrame | None,
    ) -> None:
        save_dropped_records(
            before, after, self.data_dir, f"{file_stem}.csv", True, dropped_df=dropped
        )

    def clear_previous_drops(self) -> None:
        # A step that drops nothing does not rewrite its CSV, so a file left by a
        # previous run (another bottler) would be read as if it belonged to this one
        for stale in (self.data_dir / "dropped").glob("[0-9][0-9]_*.csv"):
            stale.unlink()
            logger.info("Removed drops from a previous run: %s", stale.name)

    def publish(self, df: pl.DataFrame, output_csv: str) -> str:
        path = resolve(self.project_root, output_csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_csv(path, include_bom=True)
        return str(path)


class FileSystemAudit:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def start(self, items_to_track: list[str]) -> str | None:
        audit_file = init_audit_file(self.data_dir, items_to_track)
        return str(audit_file) if audit_file else None

    def write_step(self, audit_file: str | None, title: str, text: str) -> None:
        if audit_file:
            write_audit_step(Path(audit_file), title, text)

    def finish(
        self, audit_file: str | None, final_df: pl.DataFrame, items_to_track: list[str]
    ) -> None:
        if audit_file:
            finalize_audit_report(Path(audit_file), final_df, items_to_track)

    def html_report(self, metrics: list[StepMetric]) -> Path | None:
        if not metrics:
            return None
        return generate_html_report(
            [
                {
                    "step_name": metric.step_name,
                    "dropped_count": metric.dropped,
                    "remaining_count": metric.rows_after,
                    "top_dropped": metric.top_dropped,
                }
                for metric in metrics
            ],
            self.data_dir,
        )

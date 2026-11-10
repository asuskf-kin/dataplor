"""DatamatchQAPort adapter: runs the separate QA_datamatch project through its CLI.

QA_datamatch has its own virtualenv and dependencies (scipy, matplotlib, jinja2),
so it is called as a subprocess with ``uv run --project`` instead of being
imported. Each run gets its own generated config and output folder under
``data/runs/<thread>/datamatch_qa/``, so the QA project's config.yaml is never edited.
"""

import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from cleaning_agent.adapters.filesystem import resolve
from cleaning_agent.domain.models import DatamatchInputs, QAExploreResult, QARunResult

logger = logging.getLogger(__name__)

MAX_ERROR_CHARS = 1500
REVIEW_SAMPLE_PREFIX = "review_sample_"


class QADatamatchError(RuntimeError):
    """The QA CLI failed or produced no output."""


class QADatamatchSubprocess:
    def __init__(
        self,
        project_root: Path,
        qa_project_dir: Path,
        runs_dir: Path,
        timeout_s: float = 1800,
    ) -> None:
        self.project_root = project_root
        self.qa_project_dir = qa_project_dir
        self.runs_dir = runs_dir
        self.timeout_s = timeout_s

    def _work_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id / "datamatch_qa"

    def _write_config(
        self,
        inputs: DatamatchInputs,
        run_id: str,
        thresholds: tuple[float, float] | None,
    ) -> tuple[Path, Path, str]:
        base_config = self.qa_project_dir / "config" / "config.yaml"
        if not base_config.is_file():
            raise QADatamatchError(f"QA_datamatch config not found: {base_config}")
        config: dict[str, Any] = yaml.safe_load(base_config.read_text(encoding="utf-8"))

        work_dir = self._work_dir(run_id)
        output_dir = work_dir / "output"
        run_date = f"{datetime.now():%Y%m%d}"
        config["project"] = {
            **config.get("project", {}),
            "client": inputs.client_name,
            "run_date": run_date,
            **({"country": inputs.country} if inputs.country else {}),
        }
        config["paths"] = {
            **config.get("paths", {}),
            "datamatch": str(resolve(self.project_root, inputs.datamatch_file)),
            "clients": str(resolve(self.project_root, inputs.clients_file)),
            "output_dir": str(output_dir),
        }
        if thresholds is not None:
            config["thresholds"] = {
                **config.get("thresholds", {}),
                "match": thresholds[0],
                "super_match": thresholds[1],
            }
        work_dir.mkdir(parents=True, exist_ok=True)
        config_path = work_dir / "qa_config.yaml"
        config_path.write_text(
            yaml.safe_dump(config, allow_unicode=True), encoding="utf-8"
        )
        return config_path, output_dir, f"{inputs.client_name}_{run_date}"

    def _run_cli(self, command: str, config_path: Path) -> None:
        uv = shutil.which("uv")
        if uv is None:
            raise QADatamatchError(
                "'uv' is not on PATH: it is needed to run QA_datamatch"
            )
        args = [
            uv,
            "run",
            "--project",
            str(self.qa_project_dir),
            "datamatch-qa",
            command,
        ]
        logger.info("Running QA_datamatch '%s'", command)
        try:
            completed = subprocess.run(
                [*args, "-c", str(config_path)],
                cwd=self.qa_project_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_s,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise QADatamatchError(
                f"QA_datamatch '{command}' exceeded {self.timeout_s:.0f} s"
            ) from exc
        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout)[-MAX_ERROR_CHARS:]
            raise QADatamatchError(f"QA_datamatch '{command}' failed:\n{tail}")

    def explore(self, inputs: DatamatchInputs, run_id: str) -> QAExploreResult:
        config_path, output_dir, tag = self._write_config(inputs, run_id, None)
        self._run_cli("explore", config_path)
        report = output_dir / f"threshold_report_{tag}.html"
        if not report.is_file():
            raise QADatamatchError(f"QA_datamatch did not write {report.name}")
        return QAExploreResult(report_html=str(report), output_dir=str(output_dir))

    def run(
        self, inputs: DatamatchInputs, run_id: str, match: float, super_match: float
    ) -> QARunResult:
        config_path, output_dir, tag = self._write_config(
            inputs, run_id, (match, super_match)
        )
        self._run_cli("run", config_path)
        # review_sample_* is the labelling sample written by explore, not a deliverable
        files = sorted(
            str(path)
            for path in output_dir.glob(f"*{tag}.csv")
            if not path.name.startswith(REVIEW_SAMPLE_PREFIX)
        )
        if not files:
            raise QADatamatchError(
                f"QA_datamatch wrote no CSV for {tag} in {output_dir}"
            )
        return QARunResult(files=files, output_dir=str(output_dir))

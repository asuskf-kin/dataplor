"""DatamatchQAPort adapter: runs the separate QA_datamatch project through its CLI.

QA_datamatch has its own virtualenv and dependencies (scipy, matplotlib, jinja2),
so it is called as a subprocess with ``uv run --project`` instead of being
imported. Each run gets its own generated config under
``data/runs/<thread>/datamatch_qa/`` (the QA project's config.yaml is never edited);
the outputs go to the folder the caller gives (the DWH gold mirror). The CLI runs
through ``qa_datamatch_brand.py`` so charts, tables and the HTML follow the Kin brand.
"""

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from cleaning_agent.adapters.brand import PAGE_CSS, KinBrand
from cleaning_agent.adapters.filesystem import resolve
from cleaning_agent.domain.models import DatamatchInputs, QAExploreResult, QARunResult

logger = logging.getLogger(__name__)

MAX_ERROR_CHARS = 1500
NEWLINE = "\n"
REVIEW_SAMPLE_PREFIX = "review_sample_"
BRAND_RUNNER = Path(__file__).with_name("qa_datamatch_brand.py")

# QA_datamatch's HTML uses bare h1/h2/h3/pre/table tags: map them onto the brand page
QA_REPORT_CSS = """
.page>h1{background:var(--ka-color-black);color:var(--ka-color-white);border-radius:var(--ka-radius-box);
font-family:var(--ka-font-display);font-size:var(--ka-size-h2);font-weight:var(--ka-weight-bold);
line-height:var(--ka-lh-tight);padding:2rem 2.25rem;margin:0 0 1.75rem;overflow-wrap:anywhere}
h2,h3{font-family:var(--ka-font-display);font-weight:var(--ka-weight-medium);margin:2rem 0 1rem;
padding-left:.75rem;border-left:.25rem solid var(--ka-color-yellow)}
h2{font-size:var(--ka-size-h3)}
pre{background:var(--ka-color-surface);border-radius:var(--ka-radius-box);padding:1rem 1.25rem;
font-family:var(--ka-font-body);font-size:var(--ka-size-caption);overflow-x:auto}
.warn{background:var(--ka-color-surface);border-left:.25rem solid var(--ka-color-yellow);
border-radius:var(--ka-radius-box);padding:.75rem 1rem}
img{display:block;max-width:100%;border-radius:var(--ka-radius-box);margin:.75rem 0}
th,td{font-size:var(--ka-size-caption)}
"""


class QADatamatchError(RuntimeError):
    """The QA CLI failed or produced no output."""


class QADatamatchSubprocess:
    def __init__(
        self,
        project_root: Path,
        qa_project_dir: Path,
        runs_dir: Path,
        brand: KinBrand,
        timeout_s: float = 1800,
    ) -> None:
        self.project_root = project_root
        self.qa_project_dir = qa_project_dir
        self.runs_dir = runs_dir
        self.timeout_s = timeout_s
        self.brand = brand

    def _work_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id / "datamatch_qa"

    def _write_config(
        self,
        inputs: DatamatchInputs,
        run_id: str,
        thresholds: tuple[float, float] | None,
        output_dir: Path,
    ) -> tuple[Path, Path, str]:
        base_config = self.qa_project_dir / "config" / "config.yaml"
        if not base_config.is_file():
            raise QADatamatchError(f"QA_datamatch config not found: {base_config}")
        config: dict[str, Any] = yaml.safe_load(base_config.read_text(encoding="utf-8"))

        work_dir = self._work_dir(run_id)
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

    def _theme(self, work_dir: Path) -> Path:
        """Brand values for the runner: token colors and the static font files."""
        theme = {
            "font_body": "Albert Sans",
            "font_files": self.brand.font_files(),
            "colors": {
                "surface": self.brand.color("ka-color-gray-4"),
                "ink": self.brand.color("ka-color-white"),
                "muted": self.brand.color("ka-color-gray-3"),
                "grid": self.brand.color("ka-color-black"),
                "series_1": self.brand.color("ka-color-yellow"),
                "series_2": self.brand.color("ka-color-white"),
                "series_3": self.brand.color("ka-color-gray-3"),
                "series_4": self.brand.color("ka-color-gray-2"),
                "scale_low": self.brand.color("ka-color-gray-1"),
                "scale_high": self.brand.color("ka-color-yellow"),
            },
        }
        work_dir.mkdir(parents=True, exist_ok=True)
        path = work_dir / "brand_theme.json"
        path.write_text(json.dumps(theme), encoding="utf-8")
        return path

    def _brand_page(self, report: Path) -> None:
        """Wraps QA_datamatch's HTML with the brand page (fonts, tokens, logo, footer)."""
        page = report.read_text(encoding="utf-8")
        bar = f'{self.brand.logo()}<span class="ka-site">kinanalytics.com</span>'
        css = NEWLINE.join((self.brand.head_css, PAGE_CSS, QA_REPORT_CSS))
        page = page.replace("<style></style>", f"<style>{css}</style>", 1)
        page = page.replace(
            "<body>", f'<body><div class="page"><div class="top">{bar}</div>', 1
        )
        page = page.replace("</body>", f'<div class="foot">{bar}</div></div></body>', 1)
        report.write_text(page, encoding="utf-8")

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
            "python",
            str(BRAND_RUNNER),
            str(self._theme(config_path.parent)),
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

    def explore(
        self, inputs: DatamatchInputs, run_id: str, output_dir: Path
    ) -> QAExploreResult:
        config_path, output_dir, tag = self._write_config(
            inputs, run_id, None, output_dir
        )
        self._run_cli("explore", config_path)
        report = output_dir / f"threshold_report_{tag}.html"
        if not report.is_file():
            raise QADatamatchError(f"QA_datamatch did not write {report.name}")
        self._brand_page(report)
        return QAExploreResult(report_html=str(report), output_dir=str(output_dir))

    def run(
        self,
        inputs: DatamatchInputs,
        run_id: str,
        match: float,
        super_match: float,
        output_dir: Path,
    ) -> QARunResult:
        config_path, output_dir, tag = self._write_config(
            inputs, run_id, (match, super_match), output_dir
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

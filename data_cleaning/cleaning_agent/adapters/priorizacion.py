"""PriorizacionPort adapter: runs Priorizacion_On_Premise_code through its CLI.

That repo pins Python 3.12 and heavy geo dependencies (h3, rasterio), so it runs in
its own environment (``uv run --project``) with cwd = its root, where its own
``.env`` (Azure credentials) is loaded by its code; this process never reads it.

Each run gets a generated YAML based on one of the repo's run configs, with the
input pointed at the cleaned CSV in silver and both outputs in gold/priorizacion.
The repo's own YAMLs are never edited.
"""

import logging
import os
import posixpath
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from cleaning_agent.domain.models import PriorizacionResult

logger = logging.getLogger(__name__)

MAX_ERROR_CHARS = 1500


class PriorizacionError(RuntimeError):
    pass


class PriorizacionSubprocess:
    def __init__(self, repo_dir: Path, runs_dir: Path, timeout_s: float = 3600) -> None:
        self.repo_dir = repo_dir
        self.runs_dir = runs_dir
        self.timeout_s = timeout_s

    def list_configs(self) -> list[str]:
        if not self.repo_dir.is_dir():
            return []
        return sorted(p.name for p in self.repo_dir.glob("*.yaml"))

    def build_config(
        self,
        base_config: str,
        input_blob: str,
        container: str,
        output_dir: str,
        bottler: str,
        country: str,
        period: str,
    ) -> dict[str, Any]:
        base = self.repo_dir / base_config
        if base_config not in self.list_configs():
            raise PriorizacionError(f"Unknown priorización config: {base_config}")
        config: dict[str, Any] = yaml.safe_load(base.read_text(encoding="utf-8"))
        step1, step2 = config["step1_priority"], config["step2_geo"]
        # Single base: the cleaned Dataplor in silver (the agent's QA output is separate)
        step1["inputs"] = {
            "dataplor": {"file_path": input_blob, "container_name": container}
        }
        step1["output"] = {
            "file_path": f"{output_dir}/",
            "container_name": container,
            "file_name": f"1_priority_{bottler}_{country}_{period}",
        }
        step2["inputs"] = {"priority": None}  # step 2 reads step 1's output
        step2["output"] = {
            "file_path": f"{output_dir}/",
            "container_name": container,
            "file_name": f"Dataplor_on_premise_priority_{bottler}_{country}_{period}",
        }
        config["run"] = {"name": f"{bottler}_{country}_{period}"}
        return config

    def run(self, config: dict[str, Any], run_id: str) -> PriorizacionResult:
        uv = shutil.which("uv")
        if uv is None:
            raise PriorizacionError(
                "'uv' is not on PATH: it is needed to run priorización"
            )
        work_dir = self.runs_dir / run_id
        work_dir.mkdir(parents=True, exist_ok=True)
        config_path = work_dir / "priorizacion_config.yaml"
        config_path.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        args = [uv, "run", "--project", str(self.repo_dir), "python", "-m", "pipeline"]
        logger.info("Running priorización (%s)", config["run"]["name"])
        try:
            completed = subprocess.run(
                [*args, "--config", str(config_path.resolve()), "--step", "all"],
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_s,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PriorizacionError(
                f"Priorización exceeded {self.timeout_s:.0f} s"
            ) from exc
        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout)[-MAX_ERROR_CHARS:]
            raise PriorizacionError(f"Priorización failed:\n{tail}")

        outputs = []
        for step in ("step1_priority", "step2_geo"):
            out = config[step]["output"]
            blob = posixpath.join(
                out["file_path"].rstrip("/"), f"{out['file_name']}.csv"
            )
            outputs.append(f"{out['container_name']}/{blob}")
        return PriorizacionResult(config_path=str(config_path), outputs=outputs)

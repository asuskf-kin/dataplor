"""LineagePort adapter: hashes files, reads the git commit and writes the JSON files."""

import hashlib
import json
import logging
import shutil
import subprocess
from functools import cache
from pathlib import Path
from typing import Any

from cleaning_agent.adapters.dwh_paths import DOWNLOAD_STAGES, DwhPathResolver
from cleaning_agent.domain.lineage import ArtifactRef, StageRecord

logger = logging.getLogger(__name__)

HASH_CHUNK = 8 * 1024 * 1024
SIDECAR_SUFFIX = "_metadata.json"
# Key that marks a layer sidecar (written by LayerStagingPort, with QA, destinations, vtm)
LAYER_SIDECAR_KEY = "capa"
# Where the stage record goes inside a layer sidecar
STAGE_KEY = "etapa_linaje"


def sidecar_path(path: str) -> Path:
    file = Path(path)
    return file.with_name(f"{file.stem}{SIDECAR_SUFFIX}")


@cache
def _git_version(project_root: Path) -> str:
    git = shutil.which("git")
    if git is None:
        return "unknown"
    try:
        sha = subprocess.run(
            [git, "rev-parse", "--short", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            [git, "status", "--porcelain", "--untracked-files=no"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except subprocess.SubprocessError, OSError:
        return "unknown"
    # Uncommitted changes mean the commit alone does not reproduce the run
    return f"{sha}-dirty" if dirty else sha


def _layer_sidecar(path: Path) -> dict[str, Any] | None:
    """The existing sidecar when a layer writer made it, else None."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and LAYER_SIDECAR_KEY in data else None


class FileLineage:
    def __init__(
        self, project_root: Path, resolver: DwhPathResolver | None = None
    ) -> None:
        self.project_root = project_root
        # Written files name warehouse addresses, never this machine's paths
        self.resolver = resolver

    def _portable(self, value: Any, known: dict[str, str] | None = None) -> Any:
        return value if self.resolver is None else self.resolver.portable(value, known)

    def code_version(self) -> str:
        return _git_version(self.project_root)

    def describe(self, path: str, rows: int | None = None) -> ArtifactRef:
        file = Path(path)
        if not file.is_file():
            # Remote-only or missing artifacts are still listed, without hash
            return ArtifactRef(path=path, rows=rows)
        digest = hashlib.sha256()
        with file.open("rb") as handle:
            while chunk := handle.read(HASH_CHUNK):
                digest.update(chunk)
        return ArtifactRef(
            path=str(file),
            rows=rows,
            bytes=file.stat().st_size,
            sha256=digest.hexdigest(),
        )

    def write_sidecars(self, record: StageRecord) -> list[str]:
        """One ``<file>_metadata.json`` next to each local output of the stage."""
        written: list[str] = []
        for output in record.outputs:
            if output.sha256 is None:
                continue
            target = sidecar_path(output.path)
            payload = {
                **record.model_dump(),
                "archivo": output.model_dump(exclude_none=True),
            }
            # A download names its files by the blob they came from
            known = (
                {i.blob.rsplit("/", 1)[-1]: i.blob for i in record.inputs if i.blob}
                if record.stage in DOWNLOAD_STAGES
                else None
            )
            portable = self._portable(payload, known)
            layer = _layer_sidecar(target)
            if layer is not None:
                # The layer sidecar (QA, destinations, vtm) was written first and is what gets
                # uploaded: overwriting it left the gold package with lineage only (2026-11-23)
                portable = {**layer, STAGE_KEY: portable}
            target.write_text(
                json.dumps(portable, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            written.append(str(target))
        return written

    def write_document(self, document: dict[str, Any], path: Path) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self._portable(document), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Lineage written: %s", path)
        return str(path)

    def read_decisions(self, path: Path) -> list[dict[str, Any]]:
        """The run's decision log; no file means no recorded decisions."""
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise TypeError(f"{path.name} must be a JSON list of decisions")
        return [d for d in data if isinstance(d, dict)]

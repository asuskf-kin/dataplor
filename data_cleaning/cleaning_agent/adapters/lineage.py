"""LineagePort adapter: hashes files, reads the git commit and writes the JSON files."""

import hashlib
import json
import logging
import shutil
import subprocess
from functools import cache
from pathlib import Path
from typing import Any

from cleaning_agent.domain.lineage import ArtifactRef, StageRecord

logger = logging.getLogger(__name__)

HASH_CHUNK = 8 * 1024 * 1024
SIDECAR_SUFFIX = "_metadata.json"


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


class FileLineage:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

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
            target.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            written.append(str(target))
        return written

    def write_document(self, document: dict[str, Any], path: Path) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Lineage written: %s", path)
        return str(path)

"""Turns local paths in metadata into warehouse addresses before anything is written.

Mirror files map by their place in the mirror (domain/dwh_paths.py). A downloaded file
(raw Dataplor, GeoJSON, client base) maps to the blob it came from, read from the
sidecar its download stage left next to it. A working file that never goes to the
warehouse (pipeline steps, reports) keeps a path relative to the project, so it names
the same file on anybody's checkout; nothing keeps the person's home folder.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cleaning_agent.domain.dwh_paths import (
    LOCAL_ONLY_KEYS,
    is_local_path,
    mirror_address,
)

DOWNLOAD_STAGES = frozenset({"fetch_raw", "fetch_inputs"})
SIDECAR_SUFFIX = "_metadata.json"


class DwhPathResolver:
    def __init__(
        self,
        project_root: Path,
        mirror_dir: Path,
        dwh_container: str,
        mirrored_containers: tuple[str, ...] = (),
    ) -> None:
        self.project_root = project_root.resolve()
        self.mirror_dir = mirror_dir.resolve()
        self.dwh_container = dwh_container
        self.mirrored_containers = mirrored_containers

    def _downloaded_from(self, file: Path) -> str | None:
        """The blob a downloaded file came from, as its download stage recorded it."""
        sidecar = file.with_name(f"{file.stem}{SIDECAR_SUFFIX}")
        if not sidecar.is_file():
            return None
        try:
            record = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(record, dict) or record.get("stage") not in DOWNLOAD_STAGES:
            return None
        for source in record.get("inputs") or []:
            blob = source.get("blob") if isinstance(source, dict) else None
            if isinstance(blob, str) and blob.rsplit("/", 1)[-1] == file.name:
                return blob
        return None

    def address(self, path: str, known: Mapping[str, str] | None = None) -> str:
        """Warehouse address of a local path; anything else is returned unchanged.

        ``known`` maps a file name to its blob when the caller already knows it (the
        download stage writing its own sidecar).
        """
        if not is_local_path(path):
            return path
        file = Path(path).resolve()
        if known and file.name in known:
            return known[file.name]
        if file.is_relative_to(self.mirror_dir):
            mapped = mirror_address(
                file.relative_to(self.mirror_dir).as_posix(),
                self.dwh_container,
                self.mirrored_containers,
            )
            if mapped is not None:
                return mapped
        downloaded = self._downloaded_from(file)
        if downloaded is not None:
            return downloaded
        if file.is_relative_to(self.project_root):
            return file.relative_to(self.project_root).as_posix()
        # Outside the project (e.g. a JSON picked from Downloads): the name only
        return file.name

    def portable(self, value: Any, known: Mapping[str, str] | None = None) -> Any:
        """Same structure, every local path replaced by its warehouse address."""
        if isinstance(value, dict):
            return {
                k: self.portable(v, known)
                for k, v in value.items()
                if k not in LOCAL_ONLY_KEYS
            }
        if isinstance(value, list | tuple):
            return [self.portable(v, known) for v in value]
        if isinstance(value, str):
            return self.address(value, known)
        return value

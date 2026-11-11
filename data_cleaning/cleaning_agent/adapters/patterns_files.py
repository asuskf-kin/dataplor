"""PatternsPort adapter: reads country pattern files and when they were last updated.

The date comes from ``PATTERNS_UPDATED = "yyyy-mm-dd"`` in the file; files that do
not declare it fall back to the last git commit (also under their pre-refactor
path ``config/patterns_<code>.py``).
"""

import importlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

from cleaning_agent.application.cleaning_catalog import COUNTRY_ALIASES
from cleaning_agent.domain.patterns_policy import PatternsStatus

PACKAGE = "cleaning_agent.domain.patterns"
UPDATED_RE = re.compile(
    r'^PATTERNS_UPDATED\s*=\s*["\'](\d{4}-\d{2}-\d{2})["\']', re.MULTILINE
)


class FilePatterns:
    def __init__(self, project_root: Path, patterns_dir: Path) -> None:
        self.project_root = project_root
        self.patterns_dir = patterns_dir

    def _code(self, country: str) -> str:
        return COUNTRY_ALIASES.get(country.lower(), country.lower())

    def path(self, country: str) -> Path:
        return self.patterns_dir / f"patterns_{self._code(country)}.py"

    def _git_date(self, *paths: Path) -> str | None:
        git = shutil.which("git")
        if git is None:
            return None
        for path in paths:
            try:
                out = subprocess.run(
                    [git, "log", "-1", "--format=%cs", "--", str(path)],
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                ).stdout.strip()
            except subprocess.SubprocessError, OSError:
                return None
            if out:
                return out
        return None

    def status(self, country: str) -> PatternsStatus:
        path = self.path(country)
        if not path.is_file():
            return PatternsStatus(country=country, path=str(path), exists=False)
        match = UPDATED_RE.search(path.read_text(encoding="utf-8"))
        if match:
            return PatternsStatus(
                country=country,
                path=str(path),
                exists=True,
                updated=match.group(1),
                source="PATTERNS_UPDATED",
            )
        legacy = self.project_root / "config" / path.name
        return PatternsStatus(
            country=country,
            path=str(path),
            exists=True,
            updated=self._git_date(path, legacy),
            source="git",
        )

    def reload(self, country: str) -> int:
        """Re-imports the file after an update; returns how many chain patterns it has."""
        name = f"{PACKAGE}.patterns_{self._code(country)}"
        importlib.invalidate_caches()
        module = (
            importlib.reload(sys.modules[name])
            if name in sys.modules
            else importlib.import_module(name)
        )
        return len(list(getattr(module, "CHAIN_REGEX", [])))

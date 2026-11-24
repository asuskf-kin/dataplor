"""Where a file lives in the data warehouse, from where it sits in the local mirror.

User, 2026-11-23: "el metadata no debe estar ligado a mi local, siempre y únicamente al
DWH, porque si no otra persona no va a poder". Every ``_metadata.json`` / lineage file
names files by their warehouse address (``<container>/<blob>``), never by a path on one
person's disk. The local mirror copies the blob layout (``data/<layer>/...`` for the
DWH container, ``data/<container>/...`` for other mirrored containers), so the address
follows from the path; the adapter resolves the cases this module cannot (downloads).
"""

import re
from pathlib import PurePosixPath

DWH_LAYERS = ("drop_zone", "bronze", "silver", "gold")
# Keys that only ever describe the local copy: dropped from what is shared
LOCAL_ONLY_KEYS = frozenset({"espejo_local"})

_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")


def is_local_path(value: str) -> bool:
    """An absolute filesystem path (Windows drive, UNC or POSIX root)."""
    return bool(_ABSOLUTE.match(value))


def mirror_address(
    relative: str, dwh_container: str, mirrored_containers: tuple[str, ...]
) -> str | None:
    """``<layer>/...`` -> ``<dwh_container>/<layer>/...``; ``<container>/...`` as is.

    ``relative`` is the path inside the mirror folder, with ``/`` separators.
    """
    parts = PurePosixPath(relative.replace("\\", "/")).parts
    if not parts:
        return None
    if parts[0] in DWH_LAYERS:
        return "/".join((dwh_container, *parts))
    if parts[0] in mirrored_containers:
        return "/".join(parts)
    return None

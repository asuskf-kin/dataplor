"""Registro de prospección: the final metadata a run must answer.

User, 2026-11-23: "la metadata final debe responder" these 16 fields, in this order and
with these exact names (the columns of the team's prospection log). Paths are given as
the run knows them; the metadata writers turn them into DWH addresses
(adapters/dwh_paths.py), so nothing points at one person's disk.
"""

import re
from collections.abc import Sequence
from typing import Any

REGISTRY_FIELDS = (
    "Fecha Corrida (Prosp.)",
    "Iteración (Prosp.)",
    "Total Prospectar",
    "High & Moderate No Match",
    "Top Categorías Negocio (Prosp.)",
    "Fecha Maestra Clientes (Prosp.)",
    "Responsable Prospección",
    "Canal de Clientes",
    "Path Dataplor Clean",
    "Path DataMatch",
    "Path Dataplor Utilizado",
    "Path Info Cruda Clientes",
    "Path Resultados Azure (Prosp.)",
    "Comentarios (Prosp.)",
    "Registrado por (Prosp.)",
    "Fecha de Registro (Prosp.)",
)
# A field the run cannot know (who is responsible, a missing path) says so explicitly
TO_COMPLETE = "POR COMPLETAR"
TOP_CATEGORIES = 5

_DATE = re.compile(r"(?<!\d)(20\d{6})(?!\d)")


def date_in_path(path: str) -> str:
    """The ``yyyymmdd`` folder of a DWH path (the client master's date), or ''."""
    found = _DATE.findall(path.replace("\\", "/"))
    return found[0] if found else ""


def top_categories(categories: Sequence[tuple[str, int]], top: int = TOP_CATEGORIES) -> str:
    """``restaurant (3.212), hotel (2.118), …``: the High & Moderate categories."""
    return ", ".join(f"{name} ({count:,})".replace(",", ".") for name, count in categories[:top])


def prospection_registry(
    *,
    run_date: str,
    iteration: int,
    total_prospects: int,
    high_moderate: int,
    categories: Sequence[tuple[str, int]],
    clients_master_date: str,
    responsible: str,
    client_channel: str,
    dataplor_clean: str,
    datamatch: Sequence[str],
    dataplor_used: str,
    raw_clients: str,
    azure_results: str,
    comments: Sequence[str],
    registered_by: str,
    registered_at: str,
) -> dict[str, Any]:
    """The 16 fields, in order. ``iteration`` = Datamatch steps run in the cycle."""
    values: list[Any] = [
        run_date,
        iteration,
        total_prospects,
        high_moderate,
        top_categories(categories),
        clients_master_date,
        responsible,
        client_channel,
        dataplor_clean,
        list(datamatch),
        dataplor_used,
        raw_clients,
        azure_results,
        " | ".join(c for c in comments if c),
        registered_by,
        registered_at,
    ]
    optional = {"Comentarios (Prosp.)"}
    return {
        name: (TO_COMPLETE if value in ("", [], None) and name not in optional else value)
        for name, value in zip(REGISTRY_FIELDS, values, strict=True)
    }

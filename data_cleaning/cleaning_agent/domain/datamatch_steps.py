"""Datamatch steps: an iterative loop between the Front and the agent (user, 2026-11-11).

Each step the person runs Datamatch in the Front (client base vs cleaned Dataplor) with
a JSON of parameters. The clients that already found their Dataplor point
(``total_score`` above the cleanup threshold) leave the client base, and the reduced
base is uploaded so the next step only matches the clients still missing. The loop
ends when the person says so; then the run continues with the prospecting steps.

Pure functions: DataFrames in, DataFrames and plain dicts out.
"""

import re
from typing import Any

import polars as pl

SAFE_FOLDER = re.compile(r"[^a-z0-9_-]+")
SCORE_BIN_WIDTH = 0.05


def step_folder(step_json: str, step_number: int) -> str:
    """Folder of one step: the JSON's file name (``paso1.json`` -> ``paso1``)."""
    stem = step_json.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    cleaned = SAFE_FOLDER.sub("_", stem.lower()).strip("_")
    return cleaned or f"paso{step_number}"


def matched_rows(
    datamatch: pl.DataFrame, score_col: str, threshold: float
) -> pl.DataFrame:
    """Datamatch rows whose score is strictly above the threshold (null = no match)."""
    score = pl.col(score_col).cast(pl.Float64, strict=False)
    return datamatch.filter(score.is_not_null() & (score > threshold))


def remaining_clients(
    clients: pl.DataFrame, client_id_col: str, matched_ids: pl.Series
) -> pl.DataFrame:
    """The client base without the clients that already have their match."""
    return clients.filter(~pl.col(client_id_col).is_in(matched_ids.implode()))


def score_bins(
    scores: pl.Series, width: float = SCORE_BIN_WIDTH
) -> list[dict[str, Any]]:
    """How many matches fall in each score band (lower bound, inclusive)."""
    values = scores.cast(pl.Float64, strict=False).drop_nulls()
    if values.is_empty():
        return []
    bands = (values / width).floor() * width
    counts = (
        pl.DataFrame({"desde": bands.round(2)}).group_by("desde").len().sort("desde")
    )
    return [
        {
            "desde": float(row["desde"]),
            "hasta": round(float(row["desde"]) + width, 2),
            "matches": int(row["len"]),
        }
        for row in counts.iter_rows(named=True)
    ]


def step_summary(
    clients_in: int,
    matched: pl.DataFrame,
    clients_out: int,
    score_col: str,
    threshold: float,
) -> dict[str, Any]:
    """Counts of one step, and the check that they add up."""
    found = matched.height
    scores: list[float] = (
        matched.get_column(score_col)
        .cast(pl.Float64, strict=False)
        .drop_nulls()
        .to_list()
    )
    return {
        "clientes_inicio": clients_in,
        "clientes_con_match": found,
        "clientes_restantes": clients_out,
        "pct_encontrado": round(found / clients_in * 100, 2) if clients_in else 0.0,
        "umbral_limpieza": threshold,
        "score_min": min(scores) if scores else None,
        "score_max": max(scores) if scores else None,
        "cuadra": clients_in == found + clients_out,
    }


KNOWN_CLIENT_REASON = "Ya es cliente del bottler (Datamatch)"


def drop_known_points(
    dataplor: pl.DataFrame, id_col: str, known_ids: pl.Series
) -> pl.DataFrame:
    """Dataplor points not matched to any bottler client: the prospects."""
    return dataplor.filter(~pl.col(id_col).is_in(known_ids.implode()))


def prospects_qa(
    rows_in: int, known_ids: int, known_in_file: int, rows_out: int
) -> dict[str, Any]:
    """Counts of the prospects file and the checks a reviewer needs before gold."""
    removed = rows_in - rows_out
    checks = [
        {
            "check": "Los conteos cuadran (entrada = clientes conocidos + prospectos)",
            "ok": rows_in == removed + rows_out and removed == known_in_file,
            "detail": f"{rows_in:,} = {removed:,} + {rows_out:,}",
        },
        {
            "check": "Todos los puntos con match están en el archivo limpio",
            "ok": known_in_file == known_ids,
            "detail": f"{known_in_file:,} de {known_ids:,} ids con match",
        },
        {
            "check": "Quedó al menos un prospecto",
            "ok": rows_out > 0,
            "detail": f"{rows_out:,} prospectos",
        },
    ]
    return {
        "filas_leidas": rows_in,
        "filas_conservadas": rows_out,
        "filas_eliminadas": removed,
        "pct_eliminado": round(removed / rows_in * 100, 2) if rows_in else 0.0,
        "eliminadas_por_motivo": {KNOWN_CLIENT_REASON: removed} if removed else {},
        "checks": checks,
        "qa_ok": all(c["ok"] for c in checks),
    }

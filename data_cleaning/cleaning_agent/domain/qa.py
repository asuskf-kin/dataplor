"""QA of a layer file: how many records were removed, why, and whether counts add up."""

from typing import Any

# Pre-filter counters: reason label shown in the QA, per counter key
PREFILTER_REASONS = {
    "invalid_coordinates": "Coordenadas inválidas o vacías",
    "dropped_by_status": "No activo o no abierto (dataplor_status / open_closed_status)",
    "outside_territory": "Fuera del territorio (GeoJSON)",
    "far_from_client": "Lejos de los clientes del bottler (radio)",
}
KEPT_KEYS = ("inside_territory", "near_client")


def prefilter_qa(counts: dict[str, int], rows_written: int | None) -> dict[str, Any]:
    """Removed records by reason and the checks a reviewer needs before uploading."""
    rows_read = int(counts.get("rows_read", 0))
    kept = next((int(counts[k]) for k in KEPT_KEYS if k in counts), 0)
    removed = {
        label: int(counts[key])
        for key, label in PREFILTER_REASONS.items()
        if counts.get(key)
    }
    total_removed = sum(removed.values())
    checks = [
        {
            "check": "Los conteos cuadran (leídos = eliminados + conservados)",
            "ok": rows_read == total_removed + kept,
            "detail": f"{rows_read:,} = {total_removed:,} + {kept:,}",
        },
        {
            "check": "Quedó al menos un registro",
            "ok": kept > 0,
            "detail": f"{kept:,} conservados",
        },
    ]
    if rows_written is not None:
        checks.append(
            {
                "check": "El archivo tiene las filas conservadas",
                "ok": rows_written == kept,
                "detail": f"archivo {rows_written:,} vs conservados {kept:,}",
            }
        )
    return {
        "filas_leidas": rows_read,
        "filas_conservadas": kept,
        "filas_eliminadas": total_removed,
        "pct_eliminado": round(total_removed / rows_read * 100, 2)
        if rows_read
        else 0.0,
        "eliminadas_por_motivo": removed,
        "checks": checks,
        "qa_ok": all(c["ok"] for c in checks),
    }


FRANCHISE_REASON = "Franquicia (review Claude)"


def pipeline_qa(
    input_rows: int,
    steps: list[dict[str, Any]],
    franchises_removed: int,
    rows_written: int | None,
) -> dict[str, Any]:
    """QA of the cleaned result: drops per module (+ franchises) and the checks."""
    removed = {str(s["module"]): int(s["dropped"]) for s in steps if int(s["dropped"])}
    if franchises_removed:
        removed[FRANCHISE_REASON] = franchises_removed
    total_removed = sum(removed.values())
    kept = input_rows - total_removed
    checks = [
        {
            "check": "Los conteos cuadran (entrada = eliminados + conservados)",
            "ok": kept >= 0 and (rows_written is None or rows_written == kept),
            "detail": f"{input_rows:,} = {total_removed:,} + {kept:,}",
        },
        {
            "check": "Quedó al menos un registro",
            "ok": kept > 0,
            "detail": f"{kept:,} conservados",
        },
    ]
    if rows_written is not None:
        checks.append(
            {
                "check": "El archivo tiene las filas conservadas",
                "ok": rows_written == kept,
                "detail": f"archivo {rows_written:,} vs conservados {kept:,}",
            }
        )
    return {
        "filas_leidas": input_rows,
        "filas_conservadas": kept,
        "filas_eliminadas": total_removed,
        "pct_eliminado": round(total_removed / input_rows * 100, 2)
        if input_rows
        else 0.0,
        "eliminadas_por_motivo": removed,
        "checks": checks,
        "qa_ok": all(c["ok"] for c in checks),
    }

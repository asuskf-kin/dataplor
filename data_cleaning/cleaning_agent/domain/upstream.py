"""Paso 0: what happened before the cleaning pipeline's universe.

User, 2026-11-23: "agrega en el paso 0 cuántos vienen de raw y cuántos se eliminaron en el
front". The executive report's funnel starts at the Front's result; this block shows the
raw Dataplor rows, what the bronze prefilter took out, what went to the Front and what the
Front removed, so the whole path from raw to the pipeline reads as one.
"""

from collections.abc import Mapping

# Prefilter counts that mean "sent on to bronze / the Front", by mode
_KEPT_KEYS = ("inside_territory", "near_client")


def paso0_counts(
    prefilter_counts: Mapping[str, int] | None, front_rows: int | None
) -> list[tuple[str, int]]:
    """Rows of paso 0 as (label, rows); empty when nothing upstream is known.

    ``prefilter_counts`` are the bronze prefilter's (``rows_read`` plus the kept count of
    its mode); without a prefilter the raw Dataplor goes to the Front as it is.
    """
    counts = dict(prefilter_counts or {})
    raw = counts.get("rows_read")
    sent = next((counts[k] for k in _KEPT_KEYS if k in counts), raw)
    rows: list[tuple[str, int]] = []
    if raw is not None:
        rows.append(("Dataplor raw (filas leídas)", int(raw)))
        if sent is not None and sent != raw:
            rows.append(
                (
                    "Quitados antes del Front (estado, coordenadas, fuera del territorio)",
                    int(raw - sent),
                )
            )
    if sent is not None:
        rows.append(("Enviados al Front (bronze)", int(sent)))
    if front_rows is not None:
        if sent is not None:
            rows.append(("Eliminados en el Front", int(sent - front_rows)))
        rows.append(("Recibidos del Front (universo del pipeline)", int(front_rows)))
    return rows

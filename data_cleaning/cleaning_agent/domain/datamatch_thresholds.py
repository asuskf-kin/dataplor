"""Which threshold to use in a Datamatch step: scenarios to decide with (user, 2026-11-23).

Ported from the threshold report of QA_datamatch (``analysis.py`` / ``thresholds.py``)
so every step of the loop gets it without a second project: score distribution with
its natural cuts (KDE valleys), the sensitivity curve and its elbow, the component
scores per band, and the most marginal pairs that still pass each threshold.

A match is ``total_score > threshold`` (strictly above), the same rule the step uses
to drop clients. Pure functions: numpy arrays and polars frames in, plain values out.
"""

from typing import Any

import numpy as np
import polars as pl
from numpy.typing import NDArray

COMPONENTS = ("distance_score", "name_score", "address_score", "phonetic_score")
GRID_STEP = 0.01
BUCKET_WIDTH = 0.05
# A valley must be at least this share of the highest density deep to count as a cut
VALLEY_PROMINENCE = 0.05
MARGINAL_START = 0.95
MARGINAL_STEP = 0.05

Floats = NDArray[np.float64]


def score_grid(scores: Floats, step: float = GRID_STEP) -> Floats:
    """Thresholds every ``step`` from just below the lowest score to the highest."""
    lo = max(0.0, float(np.floor(scores.min() / step) * step))
    hi = min(1.0, float(np.ceil(scores.max() / step) * step))
    return np.round(np.arange(lo, hi + step / 2, step), 4)


def kde(scores: Floats, grid: Floats) -> Floats:
    """Gaussian kernel density with Scott's bandwidth (same rule as scipy's default)."""
    n = scores.size
    spread = float(scores.std(ddof=1)) if n > 1 else 0.0
    if n < 3 or spread == 0.0:
        return np.zeros_like(grid)
    bandwidth = spread * n ** (-1 / 5)
    density = np.zeros_like(grid)
    # Chunks keep the n x grid matrix small on bases with tens of thousands of scores
    for start in range(0, n, 20_000):
        z = (grid[None, :] - scores[start : start + 20_000, None]) / bandwidth
        density += np.exp(-0.5 * z**2).sum(axis=0)
    result: Floats = density / (n * bandwidth * np.sqrt(2 * np.pi))
    return result


def valleys(grid: Floats, density: Floats) -> list[float]:
    """Local minima of the density deep enough to separate two populations."""
    if density.max() <= 0:
        return []
    cuts: list[float] = []
    floor = density.max() * VALLEY_PROMINENCE
    for i in range(1, density.size - 1):
        if density[i] < density[i - 1] and density[i] <= density[i + 1]:
            left, right = density[:i].max(), density[i + 1 :].max()
            if min(left, right) - density[i] >= floor:
                cuts.append(float(grid[i]))
    return cuts


def matches_above(scores: Floats, grid: Floats) -> NDArray[np.int64]:
    """How many scores are strictly above each threshold of the grid."""
    ordered = np.sort(scores)
    counts: NDArray[np.int64] = (
        ordered.size - np.searchsorted(ordered, grid, side="right")
    ).astype(np.int64)
    return counts


def elbow(grid: Floats, counts: NDArray[np.int64]) -> float | None:
    """Kneedle: the point of the curve farthest from the line between its ends."""
    if grid.size < 3:
        return None
    x = (grid - grid.min()) / (np.ptp(grid) or 1)
    y = (counts - counts.min()) / (np.ptp(counts) or 1)
    return float(grid[int(np.argmax(np.abs(y - (1 - x))))])


def component_means(frame: pl.DataFrame, score_col: str) -> list[dict[str, Any]]:
    """Mean of each component score per total_score band (lower bound)."""
    present = [c for c in COMPONENTS if c in frame.columns]
    if not present or frame.is_empty():
        return []
    banded = frame.with_columns(
        ((pl.col(score_col) / BUCKET_WIDTH + 1e-9).floor() * BUCKET_WIDTH)
        .round(2)
        .alias("banda"),
        *[pl.col(c).cast(pl.Float64, strict=False) for c in present],
    )
    grouped = banded.group_by("banda").agg(pl.col(c).mean() for c in present)
    return list(grouped.sort("banda").iter_rows(named=True))


def flat_components(frame: pl.DataFrame) -> list[str]:
    """Components with a single value: they do not discriminate between pairs."""
    flat = []
    for c in COMPONENTS:
        if c in frame.columns:
            values = frame.get_column(c).cast(pl.Float64, strict=False).drop_nulls()
            if values.is_empty() or values.n_unique() == 1:
                shown = "vacío" if values.is_empty() else f"siempre {values[0]:.2f}"
                flat.append(
                    f"{c} {shown}: no discrimina y el total_score queda acotado por su peso."
                )
    return flat


def marginal_thresholds(front_threshold: float | None) -> list[float]:
    """0.95, 0.90, … down to the Front threshold (or 0.40 without one)."""
    stop = front_threshold if front_threshold is not None else 0.40
    count = round((MARGINAL_START - stop) / MARGINAL_STEP) + 1
    return [
        t
        for t in (round(MARGINAL_START - i * MARGINAL_STEP, 2) for i in range(count))
        if t >= stop
    ]


def scenarios(
    scores: Floats,
    n_total: int,
    candidates: list[tuple[str, float | None, str]],
    current: float,
    distance_m: Floats | None = None,
    proximity_only: NDArray[np.bool_] | None = None,
) -> list[dict[str, Any]]:
    """One row per candidate threshold: matches, shares and what each one would cost.

    ``distance_m`` and ``proximity_only`` align with ``scores`` and add the median
    distance and the share of matches backed only by proximity at each threshold.
    """
    base = int((scores > current).sum())
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    for name, threshold, why in candidates:
        if threshold is None or (name, round(threshold, 2)) in seen:
            continue
        seen.add((name, round(threshold, 2)))
        above = scores > threshold
        n = int(above.sum())
        row: dict[str, Any] = {
            "escenario": name,
            "umbral": round(threshold, 2),
            "matches": n,
            "pct_base": round(n / n_total * 100, 2) if n_total else 0.0,
            "pct_con_candidato": round(n / scores.size * 100, 2) if scores.size else 0.0,
            "delta_vs_actual": n - base,
            "criterio": why,
        }
        if distance_m is not None:
            near = distance_m[above]
            near = near[~np.isnan(near)]
            row["distancia_mediana_m"] = round(float(np.median(near)), 1) if near.size else None
        if proximity_only is not None:
            row["pct_solo_cercania"] = (
                round(float(proximity_only[above].mean()) * 100, 1) if n else 0.0
            )
        rows.append(row)
    return sorted(rows, key=lambda r: -float(r["umbral"]))

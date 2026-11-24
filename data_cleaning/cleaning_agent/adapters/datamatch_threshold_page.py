"""On-brand threshold decision page of one Datamatch step (``..._umbral.html``).

Kin version of QA_datamatch's ``threshold_report_*.html`` (user, 2026-11-23: "un html
donde puedo tomar decisiones, pásalo al brand y créalo también"), built inside the step
instead of running the other project. Charts are matplotlib PNGs embedded in the page:
offline, no script, brand fonts and the dark chart panel of the brand's QA reports.

The marginal pairs show the Dataplor and client names and addresses side by side,
because the decision is whether they look like the same place. That makes the page
client data: it stays in the local mirror for internal review and is never listed
among the step's upload files.
"""

import base64
import io
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.figure import Figure

from cleaning_agent.adapters.brand import LOGO_FORMAL_LIGHT, PAGE_CSS, KinBrand
from cleaning_agent.adapters.qa_html import QA_CSS, esc, table
from cleaning_agent.domain.datamatch_thresholds import (
    COMPONENTS,
    Floats,
    component_means,
    elbow,
    flat_components,
    kde,
    marginal_thresholds,
    matches_above,
    scenarios,
    score_grid,
    valleys,
)

MARGINAL_ROWS = 10
# Front output: ".o" = Dataplor option, ".c" = bottler client
PAIR_COLUMNS = (
    ("name.o", "nombre Dataplor"),
    ("name.c", "nombre cliente"),
    ("address.o", "dirección Dataplor"),
    ("address.c", "dirección cliente"),
)
PAGE_EXTRA_CSS = """
.charts img{display:block;width:100%;height:auto;border-radius:var(--ka-radius-box);margin:0 0 1rem}
.marginal table{font-size:var(--ka-size-caption)}
.marginal td.s{font-variant-numeric:tabular-nums;white-space:nowrap}
.marginal details{margin:.75rem 0}
.wrap{overflow-x:auto}
"""


def _theme(brand: KinBrand) -> dict[str, str]:
    return {
        "surface": brand.color("ka-color-gray-4"),
        "ink": brand.color("ka-color-white"),
        "muted": brand.color("ka-color-gray-3"),
        "grid": brand.color("ka-color-black"),
        "accent": brand.color("ka-color-yellow"),
        "second": brand.color("ka-color-white"),
        "third": brand.color("ka-color-gray-3"),
        "fourth": brand.color("ka-color-gray-2"),
        "low": brand.color("ka-color-gray-1"),
    }


def _style(brand: KinBrand) -> dict[str, str]:
    _, body = brand.matplotlib_fonts()
    c = _theme(brand)
    plt.rcParams.update(
        {
            "font.family": body,
            "font.size": 9,
            "axes.edgecolor": c["muted"],
            "axes.labelcolor": c["ink"],
            "text.color": c["ink"],
            "xtick.color": c["muted"],
            "ytick.color": c["muted"],
            "axes.grid": True,
            "grid.color": c["grid"],
            "grid.linewidth": 0.6,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": c["surface"],
            "axes.facecolor": c["surface"],
            "savefig.facecolor": c["surface"],
            "legend.frameon": False,
            "legend.labelcolor": c["ink"],
        }
    )
    return c


def _png(fig: Figure) -> str:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f'<img src="data:image/png;base64,{encoded}" alt="">'


def _marks(ax: Any, marks: dict[str, float | None], c: dict[str, str]) -> None:
    for label, x in marks.items():
        if x is None:
            continue
        ax.axvline(x, color=c["accent"] if label == "actual" else c["second"], lw=1.4, ls="--")
        ax.annotate(
            f"{label} {x:.2f}",
            (x, 1),
            xycoords=("data", "axes fraction"),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
        )


def _distribution(
    scores: Floats,
    grid: Floats,
    density: Floats,
    cuts: list[float],
    marks: dict[str, float | None],
    c: dict[str, str],
) -> str:
    fig, ax = plt.subplots(figsize=(9, 3.6))
    bins = [float(b) for b in np.arange(grid.min(), grid.max() + 0.0101, 0.01)]
    ax.hist(scores, bins=bins, density=True, color=c["third"], edgecolor=c["surface"], lw=0.6)
    ax.plot(grid, density, color=c["accent"], lw=2, label="densidad (KDE)")
    for cut in cuts:
        ax.axvline(cut, color=c["muted"], lw=1, ls=":")
        ax.annotate(
            f"valle {cut:.2f}",
            (cut, 0.97),
            xycoords=("data", "axes fraction"),
            xytext=(4, 0),
            textcoords="offset points",
            va="top",
            fontsize=8,
            color=c["muted"],
        )
    _marks(ax, marks, c)
    ax.set_title("Distribución de total_score (valles = cortes naturales)", pad=18)
    ax.set(xlabel="total_score", ylabel="densidad")
    ax.legend(loc="upper right")
    return _png(fig)


def _sensitivity(
    grid: Floats,
    counts: np.ndarray[Any, np.dtype[np.int64]],
    knee: float | None,
    marks: dict[str, float | None],
    c: dict[str, str],
) -> str:
    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(9, 5.2), sharex=True, gridspec_kw={"height_ratios": [2, 1]}
    )
    top.plot(grid, counts, color=c["accent"], lw=2)
    if knee is not None:
        y = counts[int(np.argmin(np.abs(grid - knee)))]
        top.plot([knee], [y], "o", ms=8, color=c["accent"], mec=c["surface"], mew=2)
        top.annotate(f"codo {knee:.2f}", (knee, y), xytext=(8, 8), textcoords="offset points")
    _marks(top, marks, c)
    top.set_title("Matches que quedan con cada umbral", pad=18)
    top.set(ylabel="matches")
    lost = -np.diff(counts, prepend=counts[0])
    bottom.bar(grid, lost, width=0.008, color=c["third"])
    bottom.set(xlabel="umbral", ylabel="se pierden por +0.01")
    fig.tight_layout()
    return _png(fig)


def _components(rows: list[dict[str, Any]], c: dict[str, str]) -> str:
    if not rows:
        return ""
    fig, ax = plt.subplots(figsize=(9, 3.6))
    x = [r["banda"] for r in rows]
    colors = (c["accent"], c["second"], c["third"], c["fourth"])
    for name, color in zip(COMPONENTS, colors, strict=True):
        if name in rows[0]:
            ax.plot(x, [r[name] for r in rows], color=color, lw=2, marker="o", ms=5, label=name)
    ax.set(
        title="Promedio de cada score por banda de total_score",
        xlabel="banda de total_score (límite inferior)",
        ylabel="score medio",
        ylim=(0, 1.02),
    )
    ax.legend(ncol=4, loc="lower right")
    return _png(fig)


def _score_cell(value: Any, c: dict[str, str]) -> str:
    """Score cell tinted from Gray 1 (0) to Yellow (1), black text for contrast."""
    try:
        v = min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return '<td class="s">—</td>'
    low = np.array([int(c["low"][i : i + 2], 16) for i in (1, 3, 5)])
    high = np.array([int(c["accent"][i : i + 2], 16) for i in (1, 3, 5)])
    r, g, b = (low + (high - low) * v).round().astype(int)
    return f'<td class="s" style="background:rgb({r},{g},{b});color:#000">{v:.3f}</td>'


def _marginal(
    frame: pl.DataFrame, score_col: str, threshold: float, c: dict[str, str]
) -> str:
    rows = frame.filter(pl.col(score_col) > threshold).sort(score_col).head(MARGINAL_ROWS)
    if rows.is_empty():
        return "<p>Sin registros.</p>"
    pairs = [(col, label) for col, label in PAIR_COLUMNS if col in rows.columns]
    scores = [col for col in (*COMPONENTS, score_col) if col in rows.columns]
    head = "".join(f"<th>{esc(label)}</th>" for _, label in pairs)
    head += "<th>distancia m</th>" + "".join(f"<th>{esc(s)}</th>" for s in scores)
    body = []
    for row in rows.iter_rows(named=True):
        cells = "".join(f"<td>{esc(row[col] or '—')}</td>" for col, _ in pairs)
        distance = row.get("distancia_m")
        cells += f'<td class="s">{"—" if distance is None else f"{distance:,.0f}"}</td>'
        cells += "".join(_score_cell(row[s], c) for s in scores)
        body.append(f"<tr>{cells}</tr>")
    return (
        f'<div class="wrap"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def threshold_page(
    brand: KinBrand,
    client: str,
    folder: str,
    datamatch: pl.DataFrame,
    score_col: str,
    current: float,
    front_threshold: float | None,
    distance_m: pl.Series | None,
    apply_hint: str,
    max_distance_m: float | None = None,
    distance_only: bool = False,
) -> str:
    """HTML of the threshold decision page of one step (Front output in, page out)."""
    c = _style(brand)
    frame = datamatch.with_columns(
        pl.col(score_col).cast(pl.Float64, strict=False),
        *([distance_m.alias("distancia_m")] if distance_m is not None else []),
    )
    scored = frame.filter(pl.col(score_col).is_not_null() & pl.col(score_col).is_finite())
    n_total = frame.height
    if scored.is_empty():
        body = "<section class='card'><p>El resultado del Front no trae ningún score.</p></section>"
        return _page(brand, client, folder, n_total, 0, current, body)

    scores = scored.get_column(score_col).to_numpy().astype(np.float64)
    grid = score_grid(scores)
    density = kde(scores, grid)
    cuts = valleys(grid, density)
    counts = matches_above(scores, grid)
    knee = elbow(grid, counts)
    near = (
        scored.get_column("distancia_m").to_numpy().astype(np.float64)
        if "distancia_m" in scored.columns
        else None
    )
    proximity = None
    if {"name_score", "address_score"} <= set(scored.columns):
        name = scored.get_column("name_score").cast(pl.Float64, strict=False).fill_null(0)
        address = scored.get_column("address_score").cast(pl.Float64, strict=False).fill_null(0)
        proximity = ((name < 0.5) & (address < 0.5)).to_numpy()
    candidates: list[tuple[str, float | None, str]] = [
        ("Actual (limpieza del paso)", current, "datamatch.step_cleanup_threshold"),
        ("Umbral del Front", front_threshold, "parameters.threshold del JSON del paso"),
        ("Codo de la curva", knee, "máxima curvatura matches vs umbral"),
        *[
            (f"Valle KDE #{i + 1}", cut, "mínimo de densidad entre poblaciones")
            for i, cut in enumerate(cuts)
        ],
    ]
    rows = scenarios(scores, n_total, candidates, current, near, proximity)
    rule_note = ""
    if distance_only and max_distance_m is not None and near is not None:
        rule_note = (
            f'<p class="alert">Este paso usa solo la regla de distancia: salen '
            f"{int((near <= max_distance_m).sum()):,} clientes con su candidato a "
            f"{max_distance_m:g} m o menos y el umbral no saca a nadie. Los escenarios "
            "muestran lo que haría cada umbral si se usara.</p>"
        )
    elif max_distance_m is not None and near is not None:
        extra = int(((near <= max_distance_m) & ~(scores > current)).sum())
        rule_note = (
            f'<p class="alert">Regla de distancia activa: además de los que pasan el umbral, '
            f"{extra:,} clientes con su candidato a {max_distance_m:g} m o menos cuentan como "
            "match y salen de la base. Los escenarios de abajo muestran solo el efecto del "
            "umbral.</p>"
        )
    marks = {"actual": current, "Front": front_threshold}
    warns = "".join(f'<p class="alert">{esc(w)}</p>' for w in flat_components(scored))

    scenario_rows = [
        (
            r["escenario"],
            f"{r['umbral']:.2f}",
            f"{r['matches']:,}",
            f"{r['pct_base']}%",
            f"{r['pct_con_candidato']}%",
            f"{r['delta_vs_actual']:+,}",
            "—" if r.get("distancia_mediana_m") is None else f"{r['distancia_mediana_m']:,.0f}",
            "—" if r.get("pct_solo_cercania") is None else f"{r['pct_solo_cercania']}%",
            r["criterio"],
        )
        for r in rows
    ]
    thresholds = marginal_thresholds(front_threshold)
    summary = [
        (f"> {t:.2f}", f"{int((scores > t).sum()):,}", f"{(scores > t).mean() * 100:.1f}%")
        for t in thresholds
    ]
    blocks = "".join(
        f"<details{' open' if t == round(current, 2) else ''}><summary>Umbral &gt; {t:.2f} · "
        f"{int((scores > t).sum()):,} matches</summary>{_marginal(scored, score_col, t, c)}</details>"
        for t in thresholds
    )
    body = f"""{warns}{rule_note}
<section class="card"><h2>Escenarios para elegir el umbral</h2>
<p>Match = total_score mayor que el umbral. «Solo cercanía» = nombre y dirección por debajo de 0.5.</p>
<div class="wrap">{table(scenario_rows, ('escenario', 'umbral', 'matches', '% de la base', '% con candidato', 'Δ vs actual', 'distancia mediana m', 'solo cercanía', 'criterio'))}</div>
</section>
<section class="card charts"><h2>Cómo se reparten los scores</h2>
{_distribution(scores, grid, density, cuts, marks, c)}
{_sensitivity(grid, counts, knee, marks, c)}
{_components(component_means(scored, score_col), c)}
</section>
<section class="card marginal"><h2>Pares más justos en cada umbral</h2>
<p>Cada bloque muestra los {MARGINAL_ROWS} pares con el score más bajo que todavía pasan. Si parecen el mismo
lugar, el umbral es seguro; si no, sube un escalón.</p>
{table(summary, ('umbral', 'matches', '% con candidato'))}
{blocks}
</section>
<section class="card"><h2>Cómo aplicar otro umbral</h2>
<p>{esc(apply_hint)}</p>
<p>Esta página trae nombres y direcciones de clientes: es solo para revisión interna y no se sube a Azure.</p>
</section>"""
    return _page(brand, client, folder, n_total, scores.size, current, body, int((scores > current).sum()))


def _page(
    brand: KinBrand,
    client: str,
    folder: str,
    n_total: int,
    n_scored: int,
    current: float,
    body: str,
    n_current: int = 0,
) -> str:
    stats = "".join(
        f'<div class="stat"><div class="label">{esc(k)}</div><div class="value">{esc(v)}</div></div>'
        for k, v in (
            ("Filas del Front", f"{n_total:,}"),
            ("Con candidato", f"{n_scored:,}"),
            ("Sin candidato", f"{n_total - n_scored:,}"),
            (f"Matches > {current}", f"{n_current:,}"),
        )
    )
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Umbral Datamatch {esc(folder)}</title>
<style>{brand.head_css}{PAGE_CSS}{QA_CSS}{PAGE_EXTRA_CSS}</style></head><body><div class="page">
<div class="top">{brand.logo(LOGO_FORMAL_LIGHT)}<span class="ka-site">kinanalytics.com</span></div>
<section class="band">
<p class="eyebrow">Datamatch · {esc(client)} · {esc(folder)} · umbral</p>
<h1>¿Qué umbral usar en este paso?</h1>
<p class="sub">Escenarios, curvas y los pares más justos de cada umbral para decidir desde qué
total_score un cliente ya tiene su punto Dataplor. Hoy el paso usa total_score &gt; {esc(current)}.</p>
</section>
<div class="stats">{stats}</div>
{body}
<div class="foot">{brand.logo(LOGO_FORMAL_LIGHT)}<span>{esc(folder)}</span></div>
</div></body></html>
"""

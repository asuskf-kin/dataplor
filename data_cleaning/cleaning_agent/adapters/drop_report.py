"""HTML drop report of a run (silver layer of the DWH mirror), on-brand (skill brand-guidelines-kin).

Self-contained: fonts, tokens and logo are embedded by ``KinBrand`` and the chart is
plain CSS bars, so the page has no script and loads nothing from the internet.
"""

import html
import logging
import time
from pathlib import Path
from typing import Any

from cleaning_agent.adapters.brand import LOGO_FORMAL_LIGHT, PAGE_CSS, KinBrand

logger = logging.getLogger(__name__)

# Report-specific rules on top of the shared page language; tokens and rem only.
# The chart sits on a dark panel because Kin Yellow bars have no contrast on white.
REPORT_CSS = """
.chart{background:var(--ka-color-black);color:var(--ka-color-white);border-radius:var(--ka-radius-box);
padding:1.5rem 1.75rem;margin-bottom:1.75rem}
.chart h2{font-family:var(--ka-font-display);font-size:var(--ka-size-h3);font-weight:var(--ka-weight-medium);margin:0 0 .25rem}
.chart .sub{color:var(--ka-color-gray-3);font-size:var(--ka-size-caption);margin:0 0 1.25rem}
.bars{display:grid;grid-template-columns:minmax(8rem,14rem) 1fr auto;gap:.625rem 1rem;align-items:center}
.bars .name{color:var(--ka-color-gray-3);font-size:var(--ka-size-caption);overflow-wrap:anywhere}
.bars .track{background:var(--ka-color-gray-4);border-radius:var(--ka-radius-pill);height:.75rem;overflow:hidden}
.bars .fill{background:var(--ka-chart-1);height:100%;border-radius:var(--ka-radius-pill)}
.bars .val{font-family:var(--ka-font-display);font-weight:var(--ka-weight-medium);text-align:right}
.card .meta{color:var(--ka-color-text-secondary);font-size:var(--ka-size-caption);margin:0 0 .75rem}
.card ul{margin:0;padding:0;list-style:none}
.card li{display:flex;gap:.75rem;align-items:baseline;padding:.25rem 0}
.count{font-family:var(--ka-font-display);font-weight:var(--ka-weight-bold);min-width:3rem;text-align:right}
.empty{color:var(--ka-color-text-secondary);font-size:var(--ka-size-caption);margin:0}
"""


def _e(value: Any) -> str:
    # Step names and dropped business names are data: escape them, never trust them
    return html.escape(str(value))


def _bars(metrics_list: list[dict[str, Any]]) -> str:
    peak = max((int(m["dropped_count"]) for m in metrics_list), default=0) or 1
    return "".join(
        f"<div class='name'>{_e(m['step_name'])}</div>"
        f"<div class='track'><div class='fill' style='width:{int(m['dropped_count']) / peak * 100:.1f}%'></div></div>"
        f"<div class='val'>{int(m['dropped_count']):,}</div>"
        for m in metrics_list
    )


def _step_card(m: dict[str, Any]) -> str:
    top = m["top_dropped"]
    items = (
        "<ul>"
        + "".join(
            f"<li><span class='count'>{int(freq):,}</span><code>{_e(name)}</code></li>"
            for name, freq in top
        )
        + "</ul>"
        if top
        else "<p class='empty'>No prominent exclusions recorded.</p>"
    )
    return (
        f"<section class='card'><h2>{_e(m['step_name'])}</h2>"
        f"<p class='meta'>Filtered in this step: {int(m['dropped_count']):,} · "
        f"Remaining: {int(m['remaining_count']):,}</p>{items}</section>"
    )


def render_html_report(
    metrics_list: list[dict[str, Any]], brand: KinBrand, generated_at: str
) -> str:
    """The page itself, separate from the file write so it can be checked in tests."""
    total = sum(int(m["dropped_count"]) for m in metrics_list)
    remaining = int(metrics_list[-1]["remaining_count"]) if metrics_list else 0
    stats = "".join(
        f"<div class='stat'><div class='label'>{label}</div><div class='value'>{value}</div></div>"
        for label, value in (
            ("Steps", f"{len(metrics_list):,}"),
            ("Filtered records", f"{total:,}"),
            ("Remaining", f"{remaining:,}"),
        )
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pipeline Report</title>
<style>{brand.head_css}{PAGE_CSS}{REPORT_CSS}</style></head><body><div class="page">
<div class="top">{brand.logo(LOGO_FORMAL_LIGHT)}<span class="ka-site">kinanalytics.com</span></div>
<section class="band">
<p class="eyebrow">Dataplor cleaning · drop report</p>
<h1>Pipeline execution report</h1>
<p class="sub">Generated at {_e(generated_at)}</p>
</section>
<div class="stats">{stats}</div>
<section class="chart"><h2>Filtered records per step</h2>
<p class="sub">Each record is counted once, in the step that removed it</p>
<div class="bars">{_bars(metrics_list)}</div></section>
{"".join(_step_card(m) for m in metrics_list)}
<div class="foot">{brand.logo(LOGO_FORMAL_LIGHT)}<span class="ka-site">kinanalytics.com</span></div>
</div></body></html>
"""


def generate_html_report(
    metrics_list: list[dict[str, Any]], out_dir: Path, brand: KinBrand
) -> Path:
    """Writes the drop report (filtered records per step + top 5 dropped per step)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    html_file = out_dir / f"pipeline_report_{time.strftime('%Y%m%d_%H%M%S')}.html"
    html_file.write_text(
        render_html_report(metrics_list, brand, time.strftime("%Y-%m-%d %H:%M:%S")),
        encoding="utf-8",
    )
    logger.info("HTML drop report generated at: %s", html_file)
    return html_file

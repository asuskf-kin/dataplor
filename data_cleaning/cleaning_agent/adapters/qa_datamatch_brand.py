"""Runs the QA_datamatch CLI with the Kin brand applied (skill brand-guidelines-kin).

This file is executed by QA_datamatch's own interpreter (``uv run --project
QA_datamatch python qa_datamatch_brand.py <theme.json> explore -c cfg``), so it imports
only the standard library, matplotlib and ``datamatch_qa`` — never ``cleaning_agent``.
QA_datamatch's repository is not edited: its palette, chart surface and score colormap
are swapped at runtime for the values in ``theme.json``, which the agent builds from the
brand tokens. Its page CSS is emptied; the agent wraps the HTML with the brand page.
"""

import importlib
import json
import sys
from pathlib import Path
from typing import Any


def apply_theme(theme: dict[str, Any]) -> None:
    from datamatch_qa import analysis, thresholds
    from matplotlib import font_manager
    from matplotlib import pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    for font_file in theme["font_files"]:
        font_manager.fontManager.addfont(font_file)
    colors: dict[str, str] = theme["colors"]
    # Series order of the brand: Yellow -> White -> Gray 3 -> Gray 2 on a dark panel
    analysis.BLUE = colors["series_1"]
    analysis.ORANGE = colors["series_2"]
    analysis.AQUA = colors["series_3"]
    analysis.YELLOW = colors["series_4"]
    analysis.INK = colors["ink"]
    analysis.MUTED = colors["muted"]
    analysis.GRID = colors["grid"]
    plt.rcParams.update(
        {
            "font.family": theme["font_body"],
            "axes.edgecolor": colors["muted"],
            "axes.labelcolor": colors["ink"],
            "text.color": colors["ink"],
            "xtick.color": colors["muted"],
            "ytick.color": colors["muted"],
            "grid.color": colors["grid"],
            "figure.facecolor": colors["surface"],
            "axes.facecolor": colors["surface"],
            "savefig.facecolor": colors["surface"],
            "legend.labelcolor": colors["ink"],
        }
    )
    # QA_datamatch draws the histogram in the primary color at 55% opacity, which
    # blends Yellow into the dark panel (an off-brand olive). Bars become a flat Gray 3
    # so the Yellow density line stays the single highlighted series.
    # Loaded dynamically: this process patches a class it does not own (typed as Any)
    axes_module: Any = importlib.import_module("matplotlib.axes")
    original_hist = axes_module.Axes.hist

    def flat_hist(self: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs.update(color=colors["series_3"], alpha=1.0, edgecolor=colors["surface"])
        return original_hist(self, *args, **kwargs)

    axes_module.Axes.hist = flat_hist  # runtime swap inside the QA process only
    scale = LinearSegmentedColormap.from_list(
        "kin_scale", [colors["scale_low"], colors["scale_high"]]
    )
    score_cols: list[str] = list(thresholds.SCORE_COLS)

    def branded_style(sample: Any, vmin: float, vmax: float) -> Any:
        # Same table as QA_datamatch's _style, with the brand scale instead of RdYlGn
        fmt = {c: "{:.4f}" for c in score_cols if c in sample.columns}
        sub_scores = [c for c in score_cols[:-1] if c in sample.columns]
        styled = sample.style.format(fmt, na_rep="—")
        if "total_score" in sample.columns:
            styled = styled.background_gradient(
                subset=["total_score"], cmap=scale, vmin=vmin, vmax=vmax
            )
        if sub_scores:
            styled = styled.background_gradient(
                subset=sub_scores, cmap=scale, vmin=0, vmax=1
            )
        return styled.set_properties(**{"white-space": "nowrap"})

    thresholds._style = branded_style
    thresholds._CSS = ""  # the agent injects the brand page CSS afterwards


def main(argv: list[str]) -> None:
    theme = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    apply_theme(theme)
    from datamatch_qa.cli import main as qa_main

    qa_main(argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])

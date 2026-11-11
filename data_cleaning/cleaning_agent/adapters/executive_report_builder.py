"""Executive report of a Dataplor cleaning run (port of ``report.ipynb``).

Builds, from the raw input CSV, the final pipeline output and the per-module drop CSVs
(``NN_*.csv`` with the ``drop_*`` columns), the same report the notebook produced:

* HTML, self-contained (charts embedded as base64 PNG),
* PDF in A4 pages, drawn with matplotlib (no LaTeX, no extra dependencies),
* Excel with the categories that were kept and discarded,
* the deliverable CSV of the requested channel (without the hand-deleted franchises).

Everything is joined by ``dataplor_id``, never by ``name``: the same name can have kept and
dropped branches at the same time, and comparing name sets inflates the "kept" side.

The report files contain business names on purpose (that is the deliverable), but the logs
only carry counts and file names: org policy forbids row contents (PII) in logs.
"""

from __future__ import annotations

import base64
import html
import io
import logging
import re
import unicodedata
import uuid
from collections.abc import Callable, MutableMapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

import matplotlib
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
from matplotlib.image import imread
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib.typing import RcKeyType
from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScale, FormatObject, Rule
from openpyxl.styles import Alignment, Border, Color, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.worksheet.worksheet import Worksheet

from cleaning_agent.adapters.brand import (
    BUNDLED_ASSETS_DIR,
    LOGO_FORMAL_LIGHT,
    PAGE_CSS,
    KinBrand,
)

__all__ = ["ExecutiveReportResult", "generate_executive_report"]

# --- Input columns ------------------------------------------------------------
CHANNEL_COLUMN = "channel_cat"
FRANCHISE_FLAG_COLUMN = "es_franquicia"  # "Sí" = deleted by hand
FRANCHISE_BRAND_COLUMN = "franquicia_marca"  # the brand, shown as the trigger
FRANCHISE_FLAG_YES = "Sí"

RAW_COLS = [
    "dataplor_id",
    "name",
    "business_category",
    "main_category",
    "city",
    "state",
    CHANNEL_COLUMN,
]
DROP_COLS = [
    "dataplor_id",
    "name",
    "drop_reason",
    "drop_match",
    "drop_pattern",
    "drop_group_size",
    "drop_partners",
    "drop_detail",
]

STEP_NAMES = {
    "00": "0 · Vida nocturna",  # Module 0 (optional): keeps only bars, clubs, cantinas...
    "01": "1 · Normalización",
    "02": "2 · Cadenas comerciales",
    "03": "3 · Duplicados geográficos",
    "04": "4 · Horarios y fuzzy",
    "05": "5 · Regex final",
    "06": "6 · Propiedad saturada",
}
MANUAL_STEP = "8 · Borrados a mano (franquicias)"
MANUAL_REASON = "8_Borrado_a_mano_(franquicia)"

NO_CATEGORY = "(sin categoría)"
NO_CHANNEL = "(sin canal)"
NO_BRAND = "(sin marca)"
DEFAULT_NAME_TEMPLATE = "reporte_ejecutivo_{pais}_{canal}_{bottler}_{fecha}"

TOP_BRANDS = 30  # brands in the table and chart; the Excel carries all of them
TOP_TRIGGERS = 12
MIN_TRIGGER_COVERAGE = 15  # % of a reason's drops the top must explain to be charted
TOP_CATEGORIES = 15
MIN_CATEGORY_VOLUME = (
    100  # categories below this are too small for the "wiped out" list
)


# --- Brand (skill brand-guidelines-kin) -----------------------------------------
@dataclass(frozen=True)
class _Theme:
    """Kin colors and fonts, resolved once from the brand tokens file (never hard-coded).

    Charts sit on a dark panel, like the brand's chart example: Kin Yellow, the primary
    series, has no contrast on a white page.
    """

    page: str  # PDF page and the corners around each chart panel
    layout: str  # recessed fill of cards on the page
    panel: str  # chart panel, title band, highlighted card
    ink: str  # text on the page
    ink2: str  # secondary text on the page
    muted: str  # labels, axes, the URL
    rule: str  # table rules and borders
    on_panel: str  # text on the dark panel
    series: tuple[str, str]  # chart series 1 and 2: Yellow, then White
    display: str  # Space Grotesk: titles, numerals
    body: str  # Albert Sans: body, axes, tables
    radius: float  # card corner, inches

    @classmethod
    def from_brand(cls, brand: KinBrand) -> _Theme:
        display, body = brand.matplotlib_fonts()
        c = brand.color
        return cls(
            page=c("ka-color-bg"),
            layout=c("ka-color-bg-layout"),
            panel=c("ka-color-black"),
            ink=c("ka-color-text-primary"),
            ink2=c("ka-color-gray-4"),
            muted=c("ka-color-text-secondary"),
            rule=c("ka-color-border"),
            on_panel=c("ka-color-white"),
            series=(c("ka-chart-1"), c("ka-chart-2")),
            display=display,
            body=body,
            radius=brand.length_in("ka-radius-box"),
        )


def _rc_params(theme: _Theme) -> dict[RcKeyType, Any]:
    """Applied through rc_context instead of plt.rcParams.update so that calling the
    report from a long-running graph never changes matplotlib's global style."""
    return {
        "figure.facecolor": theme.page,
        "axes.facecolor": theme.panel,
        "font.family": [theme.body],
        "font.size": 10.5,
        "text.color": theme.on_panel,
        "axes.labelcolor": theme.muted,
        "axes.edgecolor": theme.ink2,
        "xtick.color": theme.muted,
        "ytick.color": theme.muted,
        "grid.color": theme.ink2,
        "grid.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.spines.bottom": False,
        "figure.dpi": 110,
        # TrueType embedding keeps the PDF text real Space Grotesk / Albert Sans
        # (selectable, searchable) instead of Type 3 outlines.
        "pdf.fonttype": 42,
    }


# --- PDF layout (inches) ------------------------------------------------------
A4 = (8.27, 11.69)
MARGIN = 0.62
USABLE_WIDTH = A4[0] - 2 * MARGIN
ROW_HEIGHT = 0.20
MAX_IMAGE_HEIGHT = 6.4
FOOTER_Y = 0.32  # baseline of the logo + kinanalytics.com footer, below the margin
CHART_PAD = 1.8  # chart padding inside its dark panel, in font-size units


# =============================================================================
# Public API
# =============================================================================
@dataclass(frozen=True)
class ExecutiveReportResult:
    """What the report wrote and the key numbers of the run."""

    files: list[Path]
    summary: dict[str, int | float | str]


def generate_executive_report(
    raw_csv: Path,
    output_csv: Path,
    dropped_dir: Path,
    out_dir: Path,
    *,
    country: str,
    bottler: str,
    channel: str | None = "On Premise",
    name_template: str = DEFAULT_NAME_TEMPLATE,
    run_date: str | None = None,
    franchise_csv: Path | None = None,
    apply_manual_deletions: bool = True,
    overwrite_channel_csv: bool = False,
    correlation_id: str | None = None,
    brand: KinBrand | None = None,
    xlsx_dir: Path | None = None,
) -> ExecutiveReportResult:
    """Builds the executive report of one cleaning run and writes it into ``out_dir``.

    Args:
        raw_csv: pipeline input (the initial universe).
        output_csv: final pipeline output (all channels).
        dropped_dir: folder with the ``NN_*.csv`` drop files. Missing folder = no drops.
        out_dir: where the HTML, PDF and channel CSV go (created if missing).
        country: country code; lower case in file names, upper case in the report.
        bottler: bottler name for the ``{bottler}`` placeholder ("" = none).
        channel: deliverable channel (``channel_cat`` value); ``None`` = whole dataset.
        name_template: base name with ``{pais}``, ``{canal}``, ``{bottler}``, ``{fecha}``.
        run_date: value of ``{fecha}``; defaults to now as ``YYYYmmdd_HHMMSS``.
        franchise_csv: the ``_v2`` file with ``es_franquicia``/``franquicia_marca``.
            ``None`` = ``<output_csv stem>_v2.csv`` next to the output.
        apply_manual_deletions: ``False`` skips the hand-deleted franchises step.
        overwrite_channel_csv: the channel CSV is never overwritten by default because
            people edit it by hand after it is exported.
        correlation_id: run identifier added to every log line (new UUID4 if None).
        brand: Kin brand assets (fonts, tokens, logo) for the HTML, PDF, charts and
            Excel. ``None`` = the skill bundled in this repository.
        xlsx_dir: where the Excel goes (the DWH gold layer); ``None`` = ``out_dir``.

    Raises:
        FileNotFoundError: if ``raw_csv`` or ``output_csv`` does not exist.
    """
    log = _get_logger(correlation_id)
    for required in (raw_csv, output_csv):
        if not required.is_file():
            raise FileNotFoundError(
                f"No existe el archivo de entrada del reporte: {required}"
            )

    now = datetime.now()
    meta = _RunMeta(
        country=country.upper(),
        country_slug=country.lower(),
        bottler=bottler,
        raw_name=raw_csv.name,
        output_name=output_csv.name,
        generated_at=now.strftime("%Y-%m-%d %H:%M"),
    )
    warnings: list[str] = []
    data = _load_run_data(
        raw_csv,
        output_csv,
        dropped_dir,
        channel,
        franchise_csv,
        apply_manual_deletions,
        warnings,
        log,
    )
    base_name = _report_base_name(
        name_template,
        {
            "pais": meta.country_slug,
            "canal": _slug(data.channel) if data.channel else "todos_los_canales",
            "bottler": bottler,
            "fecha": run_date or now.strftime("%Y%m%d_%H%M%S"),
        },
        warnings,
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    brand = brand or KinBrand(BUNDLED_ASSETS_DIR)
    theme = _Theme.from_brand(brand)
    logo_png = brand.logo_png(LOGO_FORMAL_LIGHT)
    if logo_png is None:
        log.warning(
            "Logo omitido del PDF: falta el rasterizador 'cairosvg' para %s "
            "(la marca prohíbe redibujarlo).",
            LOGO_FORMAL_LIGHT,
        )
    files: list[Path] = []
    with matplotlib.rc_context(_rc_params(theme)):
        content = _build_content(data, theme)
        channel_file = _export_channel_csv(
            output_csv, out_dir, data, overwrite_channel_csv, log
        )
        if channel_file is not None:
            files.append(channel_file)
        excel_dir = xlsx_dir or out_dir
        excel_dir.mkdir(parents=True, exist_ok=True)
        xlsx = _export_categories_xlsx(
            excel_dir / f"{base_name}.xlsx", data, meta, log, theme
        )
        if xlsx is not None:
            files.append(xlsx)
        # Warnings travel with the report (HTML/PDF) so readers see the caveats.
        content.warnings = list(warnings)
        files.append(
            _export_html(out_dir / f"{base_name}.html", data, content, meta, brand)
        )
        files.append(
            _export_pdf(
                out_dir / f"{base_name}.pdf",
                data,
                content,
                meta,
                theme,
                logo_png,
            )
        )

    for warning in warnings:
        log.warning(warning)
    summary = _summary(data, meta, base_name, len(warnings))
    log.info(
        "Reporte ejecutivo: %s -> %s registros (retención %.1f%%), %d archivo(s): %s",
        summary["initial_rows"],
        summary["final_rows"],
        summary["retention_pct"],
        len(files),
        ", ".join(f.name for f in files),
    )
    return ExecutiveReportResult(files=files, summary=summary)


# =============================================================================
# Logging
# =============================================================================
class _CorrelationAdapter(logging.LoggerAdapter[logging.Logger]):
    """Prefixes every line with the run's Correlation ID (same format as territory_filter)."""

    def process(
        self, msg: object, kwargs: MutableMapping[str, Any]
    ) -> tuple[str, MutableMapping[str, Any]]:
        correlation_id = (self.extra or {}).get("correlation_id", "-")
        return f"[cid={correlation_id}] {msg}", kwargs


def _get_logger(correlation_id: str | None) -> _CorrelationAdapter:
    return _CorrelationAdapter(
        logging.getLogger(__name__),
        {"correlation_id": correlation_id or str(uuid.uuid4())},
    )


# =============================================================================
# Formatting
# =============================================================================
def _thousands(v: float) -> str:
    """Dot as thousands separator (Spanish-speaking readers)."""
    return f"{v:,.0f}".replace(",", ".")


def _pct(v: float, decimals: int = 1) -> str:
    """Decimal comma, same convention as ``_thousands``."""
    return f"{v:.{decimals}f}%".replace(".", ",")


def _pct2(v: float) -> str:
    return _pct(v, 2)


def _one_decimal(v: float) -> str:
    return f"{v:.1f}".replace(".", ",")


# Per-column format. Applied with .map instead of .style: Styler needs jinja2, which is not
# a dependency. Membership in this dict also marks a column as numeric (right-aligned in PDF).
FMT: dict[str, Callable[[float], str]] = {
    "inicial": _thousands,
    "eliminados": _thousands,
    "conservados": _thousands,
    "registros": _thousands,
    "restantes": _thousands,
    "bajas": _thousands,
    "grupos": _thousands,
    "grupo_maximo": _thousands,
    "Tamaño": _thousands,
    "se quedan": _thousands,
    "se van": _thousands,
    "retencion": _pct,
    "% del universo": _pct2,
    "% de los eliminados": _pct,
    "% de los borrados": _pct,
    "% retención acumulada": _pct,
    "% del paso": _pct,
    "grupo_promedio": _one_decimal,
}


def _slug(text: str) -> str:
    """'On Premise' -> 'on_premise', safe for a file name."""
    plain = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", plain.lower()).strip("_")


def _report_base_name(
    template: str, values: dict[str, str], warnings: list[str]
) -> str:
    """Base file name from the template, sanitised so it can never leave ``out_dir``.

    An unknown placeholder falls back to the default name (with a warning) instead of
    breaking the export, as the notebook did.
    """
    try:
        base = template.format(**values)
    except (KeyError, IndexError, ValueError) as exc:
        warnings.append(
            f"reporte.nombre en config.yaml tiene un placeholder que no existe ({exc}). "
            f"Válidos: {', '.join('{' + k + '}' for k in values)}. Se usó el nombre por defecto."
        )
        base = DEFAULT_NAME_TEMPLATE.format(**values)
    base = re.sub(r'[<>:"/\\|?*]+', "_", base).strip() or "reporte_ejecutivo"
    # Without a bottler its placeholder is empty: collapse the '__' it leaves behind.
    return re.sub(r"_{2,}", "_", base).strip("_") or "reporte_ejecutivo"


# =============================================================================
# Loading
# =============================================================================
@dataclass(frozen=True)
class _RunMeta:
    country: str
    country_slug: str
    bottler: str
    raw_name: str
    output_name: str
    generated_at: str


@dataclass(frozen=True)
class _RunData:
    """Everything the sections need, already reconciled."""

    raw: pd.DataFrame
    final: pd.DataFrame
    drops: pd.DataFrame  # one row per dropped id: pipeline + channel + manual
    pipeline_steps: int
    pipeline_drops: int
    out_of_channel: pd.DataFrame
    manual: pd.DataFrame  # dataplor_id, marca
    channel: str | None  # effective channel (None if the output has no channel column)
    channel_step: str
    manual_file: Path | None

    @property
    def n_initial(self) -> int:
        return len(self.raw)

    @property
    def n_full(self) -> int:
        return len(self.final)

    @property
    def n_channel(self) -> int:
        return self.n_full - len(self.out_of_channel)

    @property
    def n_final(self) -> int:
        return self.n_channel - len(self.manual)

    @property
    def retention(self) -> float:
        return self.n_final / self.n_initial * 100 if self.n_initial else 0.0

    @property
    def has_manual(self) -> bool:
        return len(self.manual) > 0


def _present_columns(path: Path, wanted: Sequence[str]) -> list[str]:
    header = pd.read_csv(path, nrows=0, encoding="utf-8-sig").columns
    return [c for c in wanted if c in header]


def _read_columns(path: Path, wanted: Sequence[str]) -> pd.DataFrame:
    """Reads only the wanted columns the file actually has (files differ per run)."""
    return pd.read_csv(
        path, usecols=_present_columns(path, wanted), encoding="utf-8-sig"
    )


def _load_pipeline_drops(
    dropped_dir: Path,
    input_ids: set[str],
    warnings: list[str],
    log: _CorrelationAdapter,
) -> tuple[pd.DataFrame, int]:
    """Drop CSVs of this run, labelled with their step. Returns (drops, steps read)."""
    frames: list[pd.DataFrame] = []
    paths = sorted(dropped_dir.glob("*.csv")) if dropped_dir.is_dir() else []
    if not dropped_dir.is_dir():
        log.info(
            "No existe la carpeta de descartes '%s': sin descartes del pipeline.",
            dropped_dir.name,
        )
    for path in paths:
        step = path.name[:2]
        if step not in STEP_NAMES:  # loose exports or zips in the folder
            continue
        part = _read_columns(path, DROP_COLS)
        # A step that drops nothing does not rewrite its CSV: the file left in the folder
        # belongs to an older run (another bottler). Only ids of this input count.
        this_run = part["dataplor_id"].isin(input_ids)
        if not this_run.any():
            log.info(
                "Ignorado %s (%s registros de otra corrida).",
                path.name,
                _thousands(len(part)),
            )
            continue
        if not this_run.all():
            warnings.append(
                f"{path.name}: {_thousands(int((~this_run).sum()))} de {_thousands(len(part))} "
                "descartes no están en la entrada actual y se ignoraron. Volvé a correr "
                "main.py con save_drops=True."
            )
            part = part[this_run]
        part.insert(0, "paso", STEP_NAMES[step])
        frames.append(part)
    columns = ["paso", *DROP_COLS]
    drops = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=columns)
    )
    # Every drop column always exists: older drop CSVs lack some of them and the sections
    # below would otherwise fail on a missing column instead of showing nothing.
    return drops.reindex(columns=columns), len(frames)


def _channel_filter(
    final: pd.DataFrame, channel: str | None, warnings: list[str]
) -> tuple[pd.DataFrame, str | None, pd.DataFrame]:
    """Rows outside the channel and their drop rows. Returns (outside, channel, drop rows)."""
    if channel and CHANNEL_COLUMN in final.columns:
        outside = final[final[CHANNEL_COLUMN].fillna(NO_CHANNEL) != channel]
        rows = pd.DataFrame(
            {
                "paso": _channel_step(channel),
                "dataplor_id": outside["dataplor_id"],
                "drop_reason": f"7_Fuera_de_canal_({channel})",
                # The match is the record's real channel: it shows where they went.
                "drop_match": outside[CHANNEL_COLUMN].fillna(NO_CHANNEL),
            }
        )
        return outside, channel, rows
    if channel:
        warnings.append(
            f"Se pidió filtrar por canal '{channel}' pero la salida no tiene la columna "
            f"'{CHANNEL_COLUMN}': el reporte cubre el dataset completo."
        )
    return final.iloc[0:0], None, pd.DataFrame()


def _channel_step(channel: str | None) -> str:
    return f"7 · Filtro de canal ({channel})"


def _resolve_franchise_file(
    output_csv: Path, franchise_csv: Path | None, apply: bool, warnings: list[str]
) -> Path | None:
    if not apply:
        return None
    path = franchise_csv or output_csv.with_name(f"{output_csv.stem}_v2.csv")
    if not path.is_file():
        warnings.append(
            f"No está el archivo de borrados a mano ('{path.name}'): el reporte no los descuenta."
        )
        return None
    return path


def _load_manual_deletions(
    path: Path, final: pd.DataFrame, outside: pd.DataFrame, warnings: list[str]
) -> pd.DataFrame:
    """Franchises flagged by hand that are still in the deliverable channel."""
    flags = pd.read_csv(
        path,
        usecols=["dataplor_id", FRANCHISE_FLAG_COLUMN, FRANCHISE_BRAND_COLUMN],
        encoding="utf-8-sig",
    )
    final_ids = set(final["dataplor_id"])
    foreign = int((~flags["dataplor_id"].isin(final_ids)).sum())
    if foreign:
        warnings.append(
            f"{_thousands(foreign)} registros de '{path.name}' no están en la salida del "
            "pipeline: el archivo de borrados a mano es de otra corrida."
        )
    in_channel = final_ids - set(outside["dataplor_id"])
    selected = flags[
        flags[FRANCHISE_FLAG_COLUMN].eq(FRANCHISE_FLAG_YES)
        & flags["dataplor_id"].isin(in_channel)
    ]
    manual = selected.rename(columns={FRANCHISE_BRAND_COLUMN: "marca"})[
        ["dataplor_id", "marca"]
    ]
    return manual.assign(marca=manual["marca"].fillna(NO_BRAND))


def _load_run_data(
    raw_csv: Path,
    output_csv: Path,
    dropped_dir: Path,
    channel: str | None,
    franchise_csv: Path | None,
    apply_manual: bool,
    warnings: list[str],
    log: _CorrelationAdapter,
) -> _RunData:
    raw = _read_columns(raw_csv, RAW_COLS)
    input_ids = set(raw["dataplor_id"])
    drops, steps = _load_pipeline_drops(dropped_dir, input_ids, warnings, log)
    pipeline_drops = len(drops)

    final = _read_columns(output_csv, ["dataplor_id", CHANNEL_COLUMN])
    # The output must be a subset of the input; otherwise the files come from different
    # countries or runs and the report would lie.
    foreign = int((~final["dataplor_id"].isin(input_ids)).sum())
    if foreign:
        warnings.append(
            f"{_thousands(foreign)} registros de la salida no existen en la entrada: "
            f"'{output_csv.name}' no corresponde a '{raw_csv.name}'. "
            "Revisá que ambos sean del país activo."
        )

    outside, effective_channel, channel_rows = _channel_filter(final, channel, warnings)
    manual_file = _resolve_franchise_file(
        output_csv, franchise_csv, apply_manual, warnings
    )
    manual = (
        _load_manual_deletions(manual_file, final, outside, warnings)
        if manual_file is not None
        else pd.DataFrame(columns=["dataplor_id", "marca"])
    )
    manual_rows = (
        pd.DataFrame(
            {
                "paso": MANUAL_STEP,
                "dataplor_id": manual["dataplor_id"],
                "drop_reason": MANUAL_REASON,
                "drop_match": manual["marca"],  # the franchise brand
            }
        )
        if len(manual)
        else pd.DataFrame()
    )

    extra = [f for f in (channel_rows, manual_rows) if len(f)]
    if extra:
        drops = pd.concat([drops, *extra], ignore_index=True)
    location = [
        c for c in ["dataplor_id", "business_category", "state", "city"] if c in raw
    ]
    drops = drops.merge(raw[location], on="dataplor_id", how="left")

    data = _RunData(
        raw=raw,
        final=final,
        drops=drops,
        pipeline_steps=steps,
        pipeline_drops=pipeline_drops,
        out_of_channel=outside,
        manual=manual,
        channel=effective_channel,
        channel_step=_channel_step(effective_channel),
        manual_file=manual_file,
    )
    # Reconciliation: initial - dropped must give exactly the deliverable.
    gap = data.n_initial - len(drops) - data.n_final
    if gap:
        warnings.append(
            f"Descuadre de {_thousands(abs(gap))} registros: inicial − eliminados ≠ salida "
            "final. Los CSV de descartes y el output vienen de corridas distintas; volvé a "
            "correr main.py con save_drops=True para que los números cierren."
        )
    log.info(
        "Entrada %s (%s), salida %s (%s), descartes %s en %d paso(s), canal %s (%s fuera), "
        "borrados a mano %s.",
        raw_csv.name,
        _thousands(data.n_initial),
        output_csv.name,
        _thousands(data.n_full),
        _thousands(pipeline_drops),
        steps,
        effective_channel or "sin filtro",
        _thousands(len(outside)),
        _thousands(len(manual)),
    )
    return data


# =============================================================================
# Report content: cards, charts and tables
# =============================================================================
class _Card(NamedTuple):
    op: str
    title: str
    value: str
    detail: str
    highlighted: bool


@dataclass
class _Content:
    """Charts (PNG bytes) and their formatted tables, keyed by section item."""

    cards: list[_Card]
    hero_detail: str
    theme: _Theme
    figs: dict[str, bytes] = field(default_factory=dict)
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def add_table(self, df: pd.DataFrame, key: str) -> None:
        """Stores the formatted copy: HTML and PDF share it, so formatting lives once."""
        view = df.copy()
        for col, fmt in FMT.items():
            if col in view.columns:
                view[col] = view[col].map(lambda v, f=fmt: f(v) if pd.notna(v) else "—")
        self.tables[key] = view.reset_index(drop=True)

    def add_figure(self, fig: Figure, key: str) -> None:
        """Saves the chart on a rounded dark panel (the brand's chart card).

        The panel is drawn in inches, so its corner matches the card radius token at
        any figure size; outside it, the page colour shows.
        """
        width, height = fig.get_size_inches()
        fig.add_artist(
            FancyBboxPatch(
                (0, 0),
                width,
                height,
                boxstyle=f"round,pad=0,rounding_size={self.theme.radius}",
                transform=fig.dpi_scale_trans,
                facecolor=self.theme.panel,
                edgecolor="none",
                zorder=-1,
            )
        )
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=self.theme.page)
        self.figs[key] = buf.getvalue()


def _build_content(data: _RunData, theme: _Theme) -> _Content:
    content = _Content(
        cards=_build_cards(data), hero_detail=_hero_detail(data), theme=theme
    )
    _section_funnel(data, content)
    reasons = _section_reasons(data, content)
    _section_manual(data, content)
    _section_triggers(data, reasons, content)
    _section_categories(data, content)
    _section_groups(data, content)
    _section_geography(data, content)
    return content


def _share_of_universe(n: int, data: _RunData) -> str:
    """Single base for every card percentage: the initial universe."""
    return f"{_pct(n / data.n_initial * 100)} del universo" if data.n_initial else "—"


def _build_cards(data: _RunData) -> list[_Card]:
    """KPI cards read as a chained sum: initial − dropped = full − outside channel = deliverable.

    The operator travels inside each card so the order survives any wrapping on screen
    or on paper.
    """
    channel, manual = data.channel, data.has_manual
    cards = [
        _Card(
            "",
            "Registros iniciales",
            _thousands(data.n_initial),
            "universo de entrada",
            False,
        ),
        _Card(
            "−",
            "Eliminados por el pipeline",
            _thousands(data.pipeline_drops),
            _share_of_universe(data.pipeline_drops, data),
            False,
        ),
        _Card(
            "=",
            "Dataset completo",
            _thousands(data.n_full),
            f"{_share_of_universe(data.n_full, data)} · todos los canales",
            not (channel or manual),
        ),
    ]
    if channel:
        others = sorted(set(data.final[CHANNEL_COLUMN].dropna().unique()) - {channel})
        label = (
            f"Fuera de canal ({others[0]})" if len(others) == 1 else "Fuera de canal"
        )
        n_out = len(data.out_of_channel)
        cards.append(
            _Card("−", label, _thousands(n_out), _share_of_universe(n_out, data), False)
        )
        if manual:
            cards.append(
                _Card(
                    "=",
                    f"Canal {channel}",
                    _thousands(data.n_channel),
                    _share_of_universe(data.n_channel, data),
                    False,
                )
            )
    if manual:
        n_manual = len(data.manual)
        cards.append(
            _Card(
                "−",
                "Borrados a mano (franquicias)",
                _thousands(n_manual),
                _share_of_universe(n_manual, data),
                False,
            )
        )
    if channel or manual:
        name = f"Entregable {channel}" if channel else "Entregable"
        cards.append(
            _Card(
                "=",
                name,
                _thousands(data.n_final),
                _share_of_universe(data.n_final, data),
                True,
            )
        )
    return cards


def _hero_detail(data: _RunData) -> str:
    target = f"al entregable de {data.channel}" if data.channel else "al dataset final"
    return f"{_thousands(data.n_final)} de {_thousands(data.n_initial)} registros llegan {target}"


# --- Chart helpers -------------------------------------------------------------
def _new_figure(width: float, height: float) -> tuple[Figure, Axes]:
    """Figure bound to the Agg canvas directly: no pyplot, no global figure registry."""
    fig = Figure(figsize=(width, height))
    FigureCanvasAgg(fig)
    return fig, fig.subplots()


def _title(ax: Axes, theme: _Theme, title: str, subtitle: str | None) -> None:
    """Title + subtitle spaced in points, so the gap is constant whatever the height."""
    ax.set_title(
        title,
        loc="left",
        fontsize=13,
        color=theme.on_panel,
        fontfamily=theme.display,
        fontweight="medium",
        pad=24 if subtitle else 8,
    )
    if subtitle:
        ax.annotate(
            subtitle,
            xy=(0, 1),
            xycoords="axes fraction",
            xytext=(0, 7),
            textcoords="offset points",
            va="bottom",
            fontsize=9.5,
            color=theme.muted,
        )


def _style_legend(ax: Axes, theme: _Theme, **kwargs: Any) -> None:
    legend = ax.legend(frameon=False, fontsize=9.5, ncols=2, **kwargs)
    for text in legend.get_texts():
        text.set_color(theme.on_panel)


def _hbar(
    content: _Content,
    labels: Sequence[str],
    values: Sequence[int],
    title: str,
    key: str,
    subtitle: str | None = None,
) -> None:
    """Sorted horizontal bars, one series (Kin Yellow), value at the end of each bar."""
    n = len(labels)
    if n == 0:  # an empty chart says nothing; the table already shows there is no data
        return
    short = [lbl if len(str(lbl)) <= 36 else f"{str(lbl)[:35]}…" for lbl in labels]
    fig, ax = _new_figure(9.2, max(2.0, 0.44 * n + 1.3))
    theme = content.theme
    ax.barh(range(n), values, height=0.62, color=theme.series[0], zorder=3)
    ax.set_yticks(range(n), short)
    ax.invert_yaxis()
    top = max(values) if max(values) > 0 else 1
    ax.set_xlim(0, top * 1.16)
    for i, v in enumerate(values):
        ax.annotate(
            _thousands(v),
            (v, i),
            xytext=(7, 0),
            textcoords="offset points",
            va="center",
            fontsize=9.5,
            color=theme.on_panel,
        )
    ax.set_xticks([])  # the value is printed on the bar: an axis would be redundant
    ax.grid(False)
    ax.tick_params(length=0)
    _title(ax, theme, title, subtitle)
    fig.tight_layout(pad=CHART_PAD)
    content.add_figure(fig, key)


def _retention_by(
    raw: pd.DataFrame, dropped_ids: set[str], column: str
) -> pd.DataFrame:
    """Initial / dropped / kept / retention per value of ``column``, largest first."""
    return (
        raw.assign(eliminado=raw["dataplor_id"].isin(dropped_ids))
        .groupby(column)
        .agg(inicial=("dataplor_id", "size"), eliminados=("eliminado", "sum"))
        .assign(
            conservados=lambda d: d["inicial"] - d["eliminados"],
            retencion=lambda d: d["conservados"] / d["inicial"] * 100,
        )
        .sort_values("inicial", ascending=False)
    )


# --- Sections ----------------------------------------------------------------------
def _section_funnel(data: _RunData, content: _Content) -> None:
    """Section 3: how much each step drops and how much is left after it."""
    by_step = data.drops.groupby("paso").size().rename("eliminados")
    present = set(by_step.index)
    order = [STEP_NAMES[k] for k in sorted(STEP_NAMES) if STEP_NAMES[k] in present]
    for closing in (
        data.channel_step,
        MANUAL_STEP,
    ):  # channel, then manual, close the funnel
        if closing in present:
            order.append(closing)
    funnel = by_step.reindex(order).fillna(0).astype(int).to_frame()
    funnel["restantes"] = data.n_initial - funnel["eliminados"].cumsum()
    funnel["% del universo"] = funnel["eliminados"] / data.n_initial * 100
    funnel["% retención acumulada"] = funnel["restantes"] / data.n_initial * 100
    funnel = funnel.rename_axis("Paso").reset_index()
    content.add_table(funnel, "embudo")
    if len(funnel):
        _funnel_chart(funnel, data, content)


def _funnel_chart(funnel: pd.DataFrame, data: _RunData, content: _Content) -> None:
    """One row per step: the bar is what came in, split into remaining and dropped.

    The explicit sum at the side (in − dropped = remaining) lets the reader follow the
    carry-over from one step to the next without doing the subtraction.
    """
    entered = funnel["restantes"] + funnel["eliminados"]
    n = len(funnel)
    theme = content.theme
    fig, ax = _new_figure(9.6, max(2.2, 0.5 * n + 1.5))
    gap = float(entered.max()) * 0.004  # surface gap between the two segments
    ax.barh(
        range(n),
        funnel["restantes"],
        height=0.6,
        color=theme.series[0],
        label="Siguen en el pipeline",
        zorder=3,
    )
    ax.barh(
        range(n),
        funnel["eliminados"],
        left=funnel["restantes"] + gap,
        height=0.6,
        color=theme.series[1],
        label="Eliminados en el paso",
        zorder=3,
    )
    ax.set_yticks(range(n), funnel["Paso"].astype(str).tolist())
    ax.invert_yaxis()
    ax.set_xlim(0, max(float(entered.max()), 1.0) * 1.42)  # room for the sum
    ax.set_xticks([])
    ax.grid(False)
    ax.tick_params(length=0)
    for i, (came, gone, left) in enumerate(
        zip(entered, funnel["eliminados"], funnel["restantes"], strict=True)
    ):
        ax.annotate(
            f"{_thousands(came)} − {_thousands(gone)} = {_thousands(left)}",
            (came + gap, i),
            xytext=(9, 0),
            textcoords="offset points",
            va="center",
            fontsize=9.5,
            color=theme.on_panel,
        )
    _title(
        ax,
        theme,
        "Cada paso: lo que entró, lo que se eliminó y lo que quedó",
        f"Arranca en {_thousands(data.n_initial)} registros y termina en "
        f"{_thousands(data.n_final)}",
    )
    # Legend above the bars: below, it collides with the last sum.
    _style_legend(ax, theme, loc="lower right", bbox_to_anchor=(1, 1.0))
    fig.tight_layout(pad=CHART_PAD)
    content.add_figure(fig, "embudo")


def _section_reasons(data: _RunData, content: _Content) -> pd.DataFrame:
    """Section 4: the exact rule (``drop_reason``) that dropped each record."""
    reasons = (
        data.drops.groupby(["paso", "drop_reason"])
        .size()
        .rename("registros")
        .reset_index()
        .sort_values("registros", ascending=False)
    )
    reasons["% de los eliminados"] = reasons["registros"] / len(data.drops) * 100
    reasons["% del universo"] = reasons["registros"] / data.n_initial * 100
    content.add_table(
        reasons.rename(columns={"paso": "Paso", "drop_reason": "Motivo"}), "motivos"
    )
    _hbar(
        content,
        reasons["drop_reason"].astype(str).tolist(),
        reasons["registros"].astype(int).tolist(),
        "Motivos de eliminación",
        key="motivos",
        subtitle="Cada registro se atribuye a una sola regla: la primera que coincide",
    )
    return reasons


def _manual_detail(data: _RunData, columns: Sequence[str]) -> pd.DataFrame:
    """Hand-deleted franchises joined with the requested raw columns that exist."""
    cols = [c for c in columns if c in data.raw.columns]
    return data.manual.merge(
        data.raw[["dataplor_id", *cols]], on="dataplor_id", how="left"
    )


def _section_manual(data: _RunData, content: _Content) -> None:
    """Section 4b: franchises deleted by hand, grouped by brand."""
    if not data.has_manual:
        return
    detail = _manual_detail(data, ["name", "business_category"])
    grouped = detail.groupby("marca")
    by_brand = (
        (
            grouped.agg(registros=("dataplor_id", "size"), ejemplo=("name", "first"))
            if "name" in detail.columns
            else grouped.agg(registros=("dataplor_id", "size"))
        )
        .sort_values("registros", ascending=False)
        .reset_index()
    )
    by_brand["% de los borrados"] = by_brand["registros"] / len(detail) * 100
    top = by_brand.head(TOP_BRANDS)
    content.add_table(
        top.rename(columns={"marca": "Marca", "ejemplo": "Ejemplo de nombre"}),
        "borrados_mano",
    )
    _hbar(
        content,
        top["marca"].astype(str).tolist(),
        top["registros"].astype(int).tolist(),
        "Borrados a mano: franquicias por marca",
        key="borrados_mano",
        subtitle=(
            f"Top {len(top)} de {_thousands(len(by_brand))} marcas · "
            f"{_thousands(len(detail))} registros borrados en total"
        ),
    )


def _section_triggers(data: _RunData, reasons: pd.DataFrame, content: _Content) -> None:
    """Section 5: the text (``drop_match``) or regex (``drop_pattern``) behind each reason.

    This is the view for tuning patterns: if something legitimate is falling, it shows here.
    """
    drops = data.drops
    for reason, step in zip(reasons["drop_reason"], reasons["paso"], strict=True):
        if reason == MANUAL_REASON:  # detailed in its own section
            continue
        sub = drops[(drops["drop_reason"] == reason) & drops["drop_match"].notna()]
        if sub.empty:
            continue
        # The regex is more informative than the loose text, when the reason records it.
        col = "drop_pattern" if sub["drop_pattern"].notna().any() else "drop_match"
        top = (
            sub.groupby(col)
            .size()
            .rename("registros")
            .sort_values(ascending=False)
            .head(TOP_TRIGGERS)
            .reset_index()
        )
        top["% del paso"] = top["registros"] / len(sub) * 100
        coverage = float(top["registros"].sum()) / len(sub) * 100
        # Two cases give no useful ranking (they show up in the grouped duplicates
        # section): every drop with its own match, or opaque ids (UUIDs/hashes) as matches.
        if coverage < MIN_TRIGGER_COVERAGE:
            continue
        if top[col].astype(str).str.fullmatch(r"[0-9a-fA-F\-]{16,}").mean() > 0.5:
            continue
        key = f"top_{reason}"
        content.add_table(top.rename(columns={col: "Disparador"}), key)
        if len(top) < 3:  # two bars or fewer are not a chart: the table is enough
            continue
        _hbar(
            content,
            top[col].astype(str).tolist(),
            top["registros"].astype(int).tolist(),
            f"{reason} — top {len(top)} disparadores",
            key=key,
            subtitle=(
                f"{step} · agrupado por {col} · el top explica {_pct(coverage, 0)} "
                f"de las {_thousands(len(sub))} bajas del motivo"
            ),
        )


def _section_categories(data: _RunData, content: _Content) -> None:
    """Section 6: where drops concentrate, by business category."""
    if "business_category" not in data.raw.columns:
        return
    summary = _retention_by(
        data.raw, set(data.drops["dataplor_id"]), "business_category"
    )
    top = summary.head(TOP_CATEGORIES)
    content.add_table(
        top.reset_index().rename(columns={"business_category": "Categoría"}),
        "categorias",
    )
    if len(top):
        _categories_chart(top, data, content)
    # Categories the pipeline nearly wipes out, among those with relevant volume.
    wiped = (
        summary[summary["inicial"] >= MIN_CATEGORY_VOLUME]
        .sort_values("retencion")
        .head(10)
        .reset_index()
    )
    content.add_table(
        wiped.rename(columns={"business_category": "Categoría"}), "arrasadas"
    )


def _categories_chart(top: pd.DataFrame, data: _RunData, content: _Content) -> None:
    """Part-to-whole per category: stacked horizontal bar, two series."""
    n = len(top)
    theme = content.theme
    fig, ax = _new_figure(9.6, 0.46 * n + 1.8)
    peak = float(top["inicial"].max())
    gap = peak * 0.006  # surface gap between segments
    ax.barh(
        range(n),
        top["conservados"],
        height=0.62,
        color=theme.series[0],
        label="Conservados",
        zorder=3,
    )
    ax.barh(
        range(n),
        top["eliminados"],
        left=top["conservados"] + gap,
        height=0.62,
        color=theme.series[1],
        label="Eliminados",
        zorder=3,
    )
    ax.set_yticks(range(n), [str(v) for v in top.index])
    ax.invert_yaxis()
    ax.set_xlim(0, peak * 1.14)
    for i, (initial, retention) in enumerate(
        zip(top["inicial"], top["retencion"], strict=True)
    ):
        ax.annotate(  # selective label: retention only
            _pct(retention, 0),
            (initial + gap, i),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            fontsize=9.5,
            color=theme.on_panel,
        )
    ax.grid(axis="x", zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.xaxis.set_major_formatter(lambda v, _: _thousands(v))
    if data.channel:
        scope = f"el entregable de {data.channel} (incluye el filtro de canal" + (
            " y los borrados a mano)" if data.has_manual else ")"
        )
    else:
        scope = "el dataset final"
    _title(
        ax,
        theme,
        "Top 15 categorías: conservados vs eliminados",
        "El % al final de cada barra es la retención hasta " + scope,
    )
    _style_legend(ax, theme, loc="lower right")
    fig.tight_layout(pad=CHART_PAD)
    content.add_figure(fig, "categorias")


def _section_groups(data: _RunData, content: _Content) -> None:
    """Section 7: groups collapsed by steps 1, 3 and 6, to spot over-aggressive grouping."""
    drops = data.drops
    if not drops["drop_group_size"].notna().any():
        return
    grouped = drops[drops["drop_group_size"].notna()]
    summary = (
        grouped.groupby("paso")
        .agg(
            bajas=("dataplor_id", "size"),
            grupos=("drop_match", "nunique"),
            grupo_promedio=("drop_group_size", "mean"),
            grupo_maximo=("drop_group_size", "max"),
        )
        .reset_index()
        .rename(columns={"paso": "Paso"})
    )
    content.add_table(summary, "grupos")
    largest = (
        grouped.sort_values("drop_group_size", ascending=False)
        .drop_duplicates("drop_match")
        .head(10)[["paso", "name", "drop_match", "drop_group_size", "drop_detail"]]
        .rename(
            columns={
                "paso": "Paso",
                "name": "Ejemplo",
                "drop_match": "Agrupado por",
                "drop_group_size": "Tamaño",
                "drop_detail": "Detalle",
            }
        )
    )
    content.add_table(largest, "grupos_mayores")


def _section_geography(data: _RunData, content: _Content) -> None:
    """Section 8: retention per state, to check no region is punished disproportionately."""
    if "state" not in data.raw.columns:
        return
    geo = (
        _retention_by(data.raw, set(data.drops["dataplor_id"]), "state")
        .head(15)
        .reset_index()
        .rename(columns={"state": "Región"})
    )
    content.add_table(geo, "geografia")


def _report_blocks(content: _Content) -> list[tuple[str, list[str], list[str]]]:
    """Report sections as (title, chart keys, table keys)."""
    tops = [
        k for k in content.tables if k.startswith("top_")
    ]  # a table may lack a chart
    return [
        ("Embudo del pipeline", ["embudo"], ["embudo"]),
        ("Motivos de eliminación", ["motivos"], ["motivos"]),
        ("Borrados a mano: franquicias", ["borrados_mano"], ["borrados_mano"]),
        ("Qué disparó las eliminaciones", tops, tops),
        ("Impacto por categoría", ["categorias"], ["categorias", "arrasadas"]),
        ("Duplicados agrupados", [], ["grupos", "grupos_mayores"]),
        ("Cobertura geográfica", [], ["geografia"]),
    ]


def _block_items(figs: list[str], tables: list[str]) -> list[tuple[str, str]]:
    """Render order of a block as ("fig"|"table", key).

    When charts and tables pair up, each chart is followed by its equivalent table
    (readable without relying on colour); otherwise all charts first, then the tables.
    """
    if figs and figs == tables:
        return [item for k in tables for item in (("fig", k), ("table", k))]
    return [("fig", k) for k in figs] + [("table", k) for k in tables]


# =============================================================================
# Exports
# =============================================================================
def _export_channel_csv(
    output_csv: Path,
    out_dir: Path,
    data: _RunData,
    overwrite: bool,
    log: _CorrelationAdapter,
) -> Path | None:
    """Deliverable CSV: the output filtered by channel, without the hand-deleted franchises.

    Named ``<output stem>_<channel>[_sin_franquicias].csv``. An existing file is kept
    (unless ``overwrite``) because it may carry manual edits.
    """
    if not data.channel:
        return None
    df = pd.read_csv(output_csv, low_memory=False, encoding="utf-8-sig")
    in_channel = df[df[CHANNEL_COLUMN] == data.channel]
    deleted = in_channel["dataplor_id"].isin(set(data.manual["dataplor_id"]))
    suffix = f"_{_slug(data.channel)}" + ("_sin_franquicias" if deleted.any() else "")
    target = out_dir / f"{output_csv.stem}{suffix}.csv"
    if target.exists() and not overwrite:
        log.info(
            "%s ya existe y no se sobrescribe (puede tener ediciones a mano).",
            target.name,
        )
        return target
    filtered = in_channel[~deleted]
    filtered.to_csv(target, index=False, encoding="utf-8-sig")
    log.info(
        "Canal '%s': %s de %s registros, %s borrados a mano -> %s registros en %s.",
        data.channel,
        _thousands(len(in_channel)),
        _thousands(len(df)),
        _thousands(int(deleted.sum())),
        _thousands(len(filtered)),
        target.name,
    )
    return target


# --- Excel -------------------------------------------------------------------------
@dataclass(frozen=True)
class _XlsxStyle:
    header: Font
    normal: Font
    strong: Font
    fill: PatternFill
    top_border: Border
    bottom_border: Border
    # 2-colour scales (low, high) on the Keep/Discard counts: Yellow marks what stays,
    # Gray 3 what goes, so the sheet speaks the same palette as the report.
    keep_scale: tuple[str, str]
    discard_scale: tuple[str, str]


def _xlsx_style(theme: _Theme) -> _XlsxStyle:
    """Excel styles from the brand tokens (openpyxl wants RRGGBB without '#')."""

    def rgb(hex_color: str) -> str:
        return hex_color.lstrip("#").upper()

    # Albert Sans only renders where it is installed; Excel substitutes elsewhere.
    def font(**kwargs: Any) -> Font:
        return Font(name=theme.body, size=10, **kwargs)

    rule = Side(style="thin", color=rgb(theme.rule))
    return _XlsxStyle(
        header=font(bold=True, color=rgb(theme.on_panel)),
        normal=font(),
        strong=font(bold=True),
        fill=PatternFill("solid", fgColor=rgb(theme.ink2)),
        top_border=Border(top=rule),
        bottom_border=Border(bottom=rule),
        keep_scale=(rgb(theme.page), rgb(theme.series[0])),
        discard_scale=(rgb(theme.page), rgb(theme.muted)),
    )


LIST_WIDTH = 3  # columns of a Keep/Discard list: category, channel, count


def _category_table(data: _RunData) -> pd.DataFrame:
    """Per category: its channel, how many came in, survived and were dropped."""
    raw = data.raw
    universe = raw.assign(
        categoria=raw["business_category"].fillna(NO_CATEGORY),
        eliminado=raw["dataplor_id"].isin(set(data.drops["dataplor_id"])),
        canal=raw[CHANNEL_COLUMN].fillna(NO_CHANNEL)
        if CHANNEL_COLUMN in raw
        else NO_CHANNEL,
    )

    def single_channel(s: pd.Series[str]) -> str:
        # In this data each category has one channel; if one had several it is flagged
        # as mixed instead of picking one at random.
        return str(s.iloc[0]) if s.nunique() <= 1 else "(mixto)"

    cat = (
        universe.groupby("categoria")
        .agg(
            canal=("canal", single_channel),
            inicial=("dataplor_id", "size"),
            eliminados=("eliminado", "sum"),
        )
        .assign(conservados=lambda d: d["inicial"] - d["eliminados"])
        .sort_values("inicial", ascending=False)
    )
    return cat.reset_index()


def _category_reason_table(data: _RunData) -> pd.DataFrame:
    """Drops crossing category with the reason that removed them."""
    d = data.drops.assign(categoria=data.drops["business_category"].fillna(NO_CATEGORY))
    if d.empty:
        return pd.DataFrame(columns=["categoria"])
    pivot = d.pivot_table(
        index="categoria",
        columns="drop_reason",
        values="dataplor_id",
        aggfunc="count",
        fill_value=0,
    )
    order = pivot.sum(axis=1).sort_values(ascending=False).index
    return pivot.loc[order].reset_index()


def _sort_by_channel(df: pd.DataFrame, count: str, channel: str | None) -> pd.DataFrame:
    """Groups by channel (target channel first) and by count inside each one."""
    priority = df["canal"].ne(channel).astype(int) if channel else 0
    return (
        df.assign(_prioridad=priority)
        .sort_values(["_prioridad", "canal", count], ascending=[True, True, False])
        .drop(columns="_prioridad")
    )


def _write_header(
    ws: Worksheet, titles: Sequence[str], widths: Sequence[float], style: _XlsxStyle
) -> None:
    for i, (title, width) in enumerate(zip(titles, widths, strict=True), start=1):
        cell = ws.cell(row=1, column=i, value=title)
        cell.font, cell.fill = style.header, style.fill
        cell.alignment = Alignment(
            horizontal="left" if i == 1 else "right", wrap_text=True
        )
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"


def _write_summary_sheet(
    ws: Worksheet, cat: pd.DataFrame, data: _RunData, meta: _RunMeta, style: _XlsxStyle
) -> None:
    """Sheet 'Resumen': parameters, totals (as formulas) and the Keep/Discard lists."""
    ws.title = "Resumen"
    last = len(cat) + 1
    rows: list[tuple[str | None, str | int | None]] = [
        ("Reporte", "Categorías conservadas y eliminadas"),
        ("País (config.yaml)", meta.country),
        ("Embotellador", meta.bottler or "—"),
        ("Canal", data.channel or "todos los canales"),
        ("Entrada", meta.raw_name),
        ("Salida del pipeline", meta.output_name),
        ("Generado", meta.generated_at),
        (None, None),
        ("Universo inicial", f"=SUM(Categorias!C2:C{last})"),
        ("Conservados (entregable final)", f"=SUM(Categorias!D2:D{last})"),
        ("Eliminados", f"=SUM(Categorias!E2:E{last})"),
        ("Categorías distintas", f"=COUNTA(Categorias!A2:A{last})"),
        (
            "Categorías eliminadas por completo",
            f'=COUNTIF(Categorias!G2:G{last},"Eliminada completa")',
        ),
        ("Borrados a mano (franquicias)", len(data.manual)),
        (
            "Categorías sin bajas",
            f'=COUNTIF(Categorias!G2:G{last},"Conservada completa")',
        ),
        (None, None),
        ("Definición", "Conservados = registros que llegan al entregable final."),
        ("", "Si hay canal, incluye el filtro de canal como motivo de baja."),
        ("", "Cada baja se atribuye a un solo motivo: el primero que coincide."),
    ]
    for letter, width in (
        ("A", 30),
        ("B", 13),
        ("C", 11),
        ("D", 3),
        ("E", 30),
        ("F", 13),
        ("G", 11),
    ):
        ws.column_dimensions[letter].width = width
    for i, (label, value) in enumerate(rows, start=1):
        if label is None:
            continue
        cell_a = ws.cell(row=i, column=1, value=label)
        cell_a.font = style.strong if i <= 7 or label == "Definición" else style.normal
        cell_b = ws.cell(row=i, column=2, value=value)
        cell_b.font = style.normal
        if isinstance(value, str) and value.startswith("="):
            cell_b.number_format = "#,##0"
            cell_b.alignment = Alignment(horizontal="left")

    dropped = cat[cat["eliminados"] > 0][["categoria", "canal", "eliminados"]]
    if data.channel:  # Discard lists the opposite channel(s) only
        dropped = dropped[dropped["canal"] != data.channel]
    discard = _sort_by_channel(dropped, "eliminados", data.channel).values.tolist()
    keep = (
        cat[cat["conservados"] > 0][["categoria", "canal", "conservados"]]
        .sort_values("conservados", ascending=False)
        .values.tolist()
    )
    start = len(rows) + 2
    total_row = start + 2 + max(len(discard), len(keep))
    _write_list_block(
        ws, "Discard", discard, 1, start, total_row, style.discard_scale, style
    )
    _write_list_block(ws, "Keep", keep, 5, start, total_row, style.keep_scale, style)

    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)


def _write_list_block(
    ws: Worksheet,
    title: str,
    rows: list[list[Any]],
    col: int,
    start: int,
    total_row: int,
    colors: tuple[str, str],
    style: _XlsxStyle,
) -> None:
    """A Keep/Discard list with its TOTAL and a colour scale per channel run."""
    low, high = colors
    count_col = col + LIST_WIDTH - 1
    letter = get_column_letter(count_col)

    cell = ws.cell(row=start, column=col, value=title)
    cell.font, cell.alignment = style.header, Alignment(horizontal="center")
    for j in range(LIST_WIDTH):
        ws.cell(row=start, column=col + j).fill = style.fill
    ws.merge_cells(
        start_row=start, start_column=col, end_row=start, end_column=count_col
    )
    for j, text in enumerate(("business_category", "canal", "count")):
        header = ws.cell(row=start + 1, column=col + j, value=text)
        header.font, header.border = style.strong, style.bottom_border
        if text == "count":
            header.alignment = Alignment(horizontal="right")

    first = start + 2
    for k, (category, channel, count) in enumerate(rows):
        ws.cell(row=first + k, column=col, value=category).font = style.normal
        ws.cell(row=first + k, column=col + 1, value=channel).font = style.normal
        cell = ws.cell(row=first + k, column=count_col, value=int(count))
        cell.font, cell.number_format = style.normal, "#,##0"
    # An empty list would otherwise produce an inverted SUM range.
    last = first + len(rows) - 1 if rows else first

    cell = ws.cell(row=total_row, column=col, value="TOTAL")
    cell.font, cell.border = style.strong, style.top_border
    ws.cell(row=total_row, column=col + 1).border = style.top_border
    cell = ws.cell(
        row=total_row, column=count_col, value=f"=SUM({letter}{first}:{letter}{last})"
    )
    cell.font, cell.border, cell.number_format = style.strong, style.top_border, "#,##0"

    # One colour scale per run of the same channel: mixing channels would compare apples
    # with oranges.
    run_start = first
    for k in range(len(rows) + 1):
        if k < len(rows) and rows[k][1] == rows[run_start - first][1]:
            continue
        if k > run_start - first:
            ws.conditional_formatting.add(
                f"{letter}{run_start}:{letter}{first + k - 1}", _color_scale(low, high)
            )
        run_start = first + k


def _color_scale(low: str, high: str) -> Rule:
    """2-colour scale min/max (what openpyxl's untyped ColorScaleRule builds)."""
    return Rule(
        type="colorScale",
        colorScale=ColorScale(
            cfvo=[FormatObject("min"), FormatObject("max")],
            color=[Color(low), Color(high)],
        ),
    )


def _write_categories_sheet(
    ws: Worksheet, cat: pd.DataFrame, style: _XlsxStyle
) -> None:
    """Sheet 'Categorias': derived columns are formulas so the sheet recalculates on edit."""
    _write_header(
        ws,
        [
            "Categoría",
            "Canal",
            "Inicial",
            "Conservados",
            "Eliminados",
            "% Retención",
            "Estado",
        ],
        [38, 13, 12, 14, 13, 13, 22],
        style,
    )
    n = len(cat)
    rows = zip(
        cat["categoria"], cat["canal"], cat["inicial"], cat["conservados"], strict=True
    )
    for i, (category, channel, initial, kept) in enumerate(rows, start=2):
        ws.cell(row=i, column=1, value=str(category)).font = style.normal
        ws.cell(row=i, column=2, value=str(channel)).font = style.normal
        ws.cell(row=i, column=3, value=int(initial)).font = style.normal
        ws.cell(row=i, column=4, value=int(kept)).font = style.normal
        ws.cell(row=i, column=5, value=f"=C{i}-D{i}").font = style.normal
        ws.cell(row=i, column=6, value=f'=IF(C{i}=0,"",D{i}/C{i})').font = style.normal
        ws.cell(
            row=i,
            column=7,
            value=f'=IF(D{i}=0,"Eliminada completa",IF(E{i}=0,"Conservada completa","Parcial"))',
        ).font = style.normal
        for col in (3, 4, 5):
            ws.cell(row=i, column=col).number_format = "#,##0"
        ws.cell(row=i, column=6).number_format = "0.0%"

    total = n + 2
    ws.cell(row=total, column=1, value="TOTAL").font = style.strong
    for col, letter in ((3, "C"), (4, "D"), (5, "E")):
        cell = ws.cell(row=total, column=col, value=f"=SUM({letter}2:{letter}{n + 1})")
        cell.font, cell.number_format = style.strong, "#,##0"
    cell = ws.cell(row=total, column=6, value=f'=IF(C{total}=0,"",D{total}/C{total})')
    cell.font, cell.number_format = style.strong, "0.0%"
    for col in range(1, 8):
        ws.cell(row=total, column=col).border = style.top_border
    ws.auto_filter.ref = f"A1:G{n + 1}"


def _write_reasons_sheet(ws: Worksheet, pivot: pd.DataFrame, style: _XlsxStyle) -> None:
    """Sheet 'Categorias x motivo': drops per category and reason, cross-checked."""
    reasons = [str(c) for c in pivot.columns if c != "categoria"]
    total_col = len(reasons) + 2
    _write_header(
        ws,
        ["Categoría", *reasons, "Total bajas", "Chequeo"],
        [38, *[18] * len(reasons), 13, 12],
        style,
    )
    total_letter = get_column_letter(total_col)
    for i, row in enumerate(pivot.itertuples(index=False), start=2):
        ws.cell(row=i, column=1, value=str(row[0])).font = style.normal
        for j in range(2, total_col):
            cell = ws.cell(row=i, column=j, value=int(row[j - 1]))
            cell.font, cell.number_format = style.normal, "#,##0"
        cell = ws.cell(
            row=i,
            column=total_col,
            value=f"=SUM(B{i}:{get_column_letter(total_col - 1)}{i})",
        )
        cell.font, cell.number_format = style.strong, "#,##0"
        ws.cell(
            row=i,
            column=total_col + 1,
            value=(
                f"=IF({total_letter}{i}=IFERROR(INDEX(Categorias!$E:$E,"
                f'MATCH(A{i},Categorias!$A:$A,0)),-1),"OK","revisar")'
            ),
        ).font = style.normal
    ws.auto_filter.ref = f"A1:{get_column_letter(total_col + 1)}{len(pivot) + 1}"


def _write_manual_sheet(ws: Worksheet, data: _RunData, style: _XlsxStyle) -> None:
    """Sheet 'Borrados a mano': every hand-deleted franchise, record by record."""
    cols = [
        c
        for c in ["name", "business_category", "city", "state"]
        if c in data.raw.columns
    ]
    detail = _manual_detail(data, cols).sort_values(["marca", *cols[:1]])
    titles = {
        "name": "Nombre",
        "business_category": "Categoría",
        "city": "Ciudad",
        "state": "Estado",
    }
    _write_header(
        ws,
        ["Marca", *[titles[c] for c in cols], "dataplor_id"],
        [30, *[40 if c == "name" else 22 for c in cols], 38],
        style,
    )
    for i, row in enumerate(
        detail[["marca", *cols, "dataplor_id"]].itertuples(index=False), start=2
    ):
        for j, value in enumerate(row, start=1):
            ws.cell(
                row=i, column=j, value=None if pd.isna(value) else value
            ).font = style.normal
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols) + 2)}{len(detail) + 1}"


def _export_categories_xlsx(
    target: Path,
    data: _RunData,
    meta: _RunMeta,
    log: _CorrelationAdapter,
    theme: _Theme,
) -> Path | None:
    """Excel with which categories were kept and dropped, with counts and per-reason detail."""
    if "business_category" not in data.raw.columns:
        log.info("La entrada no tiene 'business_category': no se escribe el Excel.")
        return None
    cat, pivot = _category_table(data), _category_reason_table(data)
    style = _xlsx_style(theme)
    wb = Workbook()
    summary_ws = wb.active
    assert isinstance(summary_ws, Worksheet)  # a fresh Workbook always has one sheet
    _write_summary_sheet(summary_ws, cat, data, meta, style)
    _write_categories_sheet(wb.create_sheet("Categorias"), cat, style)
    _write_reasons_sheet(wb.create_sheet("Categorias x motivo"), pivot, style)
    if data.has_manual:
        _write_manual_sheet(wb.create_sheet("Borrados a mano"), data, style)
    wb.save(target)
    wiped = int((cat["conservados"] == 0).sum())
    intact = int((cat["eliminados"] == 0).sum())
    log.info(
        "Categorías: %d distintas (%d sin bajas, %d eliminadas completas, %d parciales) -> %s",
        len(cat),
        intact,
        wiped,
        len(cat) - intact - wiped,
        target.name,
    )
    return target


# --- HTML --------------------------------------------------------------------------
# Report-specific rules on top of the shared brand page (brand.PAGE_CSS); tokens and
# rem only. Kin Yellow never colours text on the light page: it is the accent bar of
# the hero and the value of the highlighted card, which sits on black.
REPORT_CSS = """
.band .sub code{color:var(--ka-color-gray-2)}
.hero{display:flex;align-items:baseline;flex-wrap:wrap;gap:.5rem 1.25rem;margin:0 0 1.75rem;
padding-left:1rem;border-left:.375rem solid var(--ka-color-yellow)}
.hero .num{font-family:var(--ka-font-display);font-weight:var(--ka-weight-bold);font-size:var(--ka-size-display);
line-height:var(--ka-lh-tight)}
.hero .det{color:var(--ka-color-gray-4)}
.stat .op{color:var(--ka-color-text-secondary);margin-right:.25rem}
.stat .detail{color:var(--ka-color-gray-4);font-size:var(--ka-size-caption)}
.stat.hl{background:var(--ka-color-black);color:var(--ka-color-white)}
.stat.hl .value{color:var(--ka-color-yellow)}
.stat.hl .detail{color:var(--ka-color-gray-2)}
.alert{background:var(--ka-color-surface);border-radius:var(--ka-radius-box);padding:.75rem 1.25rem;
margin-bottom:1rem;font-size:var(--ka-size-caption);border-left:.25rem solid var(--ka-color-yellow)}
.alert strong{font-weight:var(--ka-weight-semibold);margin-right:.5rem}
.card img{max-width:100%;height:auto;display:block;margin:0 0 1.25rem}
.card table{font-size:var(--ka-size-caption);margin-bottom:1.5rem;font-variant-numeric:tabular-nums}
.card table:last-child{margin-bottom:0}
"""


def _html_body(content: _Content) -> str:
    body = ""
    for title, figs, tables in _report_blocks(content):
        paired = bool(figs) and figs == tables
        pieces = ""
        for kind, key in _block_items(figs, tables):
            if kind == "fig" and key in content.figs:
                alt = key if paired else title
                png = base64.b64encode(content.figs[key]).decode()
                pieces += (
                    f'<img src="data:image/png;base64,{png}" alt="{html.escape(alt)}">'
                )
            elif kind == "table" and key in content.tables:
                pieces += content.tables[key].to_html(index=False, border=0)
        if pieces:
            body += (
                f'<section class="card"><h2>{html.escape(title)}</h2>{pieces}</section>'
            )
    return body


def _export_html(
    target: Path, data: _RunData, content: _Content, meta: _RunMeta, brand: KinBrand
) -> Path:
    """Self-contained, on-brand HTML (fonts, tokens, logo and charts embedded)."""
    cards = "".join(
        f'<div class="stat{" hl" if c.highlighted else ""}">'
        f'<div class="label"><span class="op">{c.op}</span>{html.escape(c.title)}</div>'
        f'<div class="value">{html.escape(c.value)}</div>'
        f'<div class="detail">{html.escape(c.detail)}</div></div>'
        for c in content.cards
    )
    alerts = "".join(
        f'<div class="alert"><strong>Aviso</strong>{html.escape(a)}</div>'
        for a in content.warnings
    )
    bottler = f" · embotellador {html.escape(meta.bottler)}" if meta.bottler else ""
    logo = brand.logo(LOGO_FORMAL_LIGHT)
    target.write_text(
        f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reporte ejecutivo — limpieza Dataplor {html.escape(meta.country)}</title>
<style>{brand.head_css}{PAGE_CSS}{REPORT_CSS}</style></head><body><div class="page">
<div class="top">{logo}<span class="ka-site">kinanalytics.com</span></div>
<section class="band">
<p class="eyebrow">Reporte ejecutivo · País {html.escape(meta.country)}{bottler}</p>
<h1>Reporte ejecutivo — limpieza Dataplor</h1>
<p class="sub">Generado {meta.generated_at} · entrada <code>{html.escape(meta.raw_name)}</code>
· salida <code>{html.escape(meta.output_name)}</code></p>
</section>
<div class="hero"><span class="num">{html.escape(_pct(data.retention))}</span><span class="det">{html.escape(content.hero_detail)}</span></div>
<div class="stats">{cards}</div>
{alerts}
{_html_body(content)}
<div class="foot">{logo}<span class="ka-site">kinanalytics.com</span></div>
</div></body></html>""",
        encoding="utf-8",
    )
    return target


# --- PDF ---------------------------------------------------------------------------
class _PdfReport:
    """Composes on-brand A4 pages stacking charts and tables, with automatic page breaks.

    Every page carries the brand footer: the approved logo file bottom-left (when it
    could be rasterised) and ``kinanalytics.com`` bottom-right.
    """

    def __init__(self, pdf: PdfPages, theme: _Theme, logo_png: bytes | None) -> None:
        self.pdf = pdf
        self.theme = theme
        self.logo = imread(io.BytesIO(logo_png)) if logo_png else None
        self._fig: Figure | None = None
        self._ax: Axes | None = None
        self.y = 0.0

    @property
    def fig(self) -> Figure:
        if self._fig is None:
            self._new_page()
        assert self._fig is not None
        return self._fig

    @property
    def ax(self) -> Axes:
        if self._ax is None:
            self._new_page()
        assert self._ax is not None
        return self._ax

    def _new_page(self) -> None:
        self.close()
        fig = Figure(figsize=A4)
        FigureCanvasAgg(fig)
        ax = fig.add_axes((0, 0, 1, 1))
        ax.set_axis_off()
        ax.set_xlim(0, A4[0])
        ax.set_ylim(0, A4[1])
        self._fig, self._ax = fig, ax
        self.y = A4[1] - MARGIN
        self._footer()

    def _footer(self) -> None:
        theme = self.theme
        self.ax.text(
            A4[0] - MARGIN,
            FOOTER_Y,
            "kinanalytics.com",
            fontsize=8,
            fontfamily=theme.body,
            fontweight="medium",
            color=theme.muted,
            ha="right",
            va="center",
        )
        if self.logo is None:
            return
        height = 0.20
        width = height * self.logo.shape[1] / self.logo.shape[0]
        axes = self.fig.add_axes(
            (
                MARGIN / A4[0],
                (FOOTER_Y - height / 2) / A4[1],
                width / A4[0],
                height / A4[1],
            )
        )
        axes.imshow(self.logo)
        axes.set_axis_off()

    def space(self, height: float) -> float:
        """Reserves ``height`` inches, opening a new page if they do not fit."""
        if self._fig is None or self.y - height < MARGIN:
            self._new_page()
        self.y -= height
        return self.y

    def text(
        self,
        s: str,
        size: float = 10,
        color: str | None = None,
        *,
        x: float = MARGIN,
        display: bool = False,
        weight: str = "normal",
    ) -> None:
        theme = self.theme
        self.ax.text(
            x,
            self.y,
            s,
            fontsize=size,
            color=color or theme.ink,
            fontfamily=theme.display if display else theme.body,
            fontweight=weight,
            va="baseline",
            ha="left",
        )

    def rule(self, color: str, lw: float, dy: float = 0.0) -> None:
        self.ax.plot(
            [MARGIN, MARGIN + USABLE_WIDTH], [self.y + dy] * 2, color=color, lw=lw
        )

    def _box(self, x: float, y: float, w: float, h: float, color: str) -> None:
        """Rounded card at the brand radius, flat (the brand has no shadows)."""
        self.ax.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle=f"round,pad=0,rounding_size={self.theme.radius}",
                linewidth=0,
                facecolor=color,
            )
        )

    def _accent(self, x: float, y: float, h: float) -> None:
        """Yellow accent bar: the brand colour enters as a shape, never as text."""
        self.ax.add_patch(
            Rectangle((x, y), 0.06, h, linewidth=0, facecolor=self.theme.series[0])
        )

    def section_title(self, s: str) -> None:
        self._new_page()  # every section starts on its own page
        self.space(0.30)
        self._accent(MARGIN, self.y - 0.04, 0.26)
        self.text(s, size=15, x=MARGIN + 0.18, display=True, weight="medium")
        self.space(0.14)
        self.rule(self.theme.rule, 0.8)
        self.space(0.22)

    def image(self, png: bytes) -> None:
        """Places a chart scaled to the usable page width."""
        img = imread(io.BytesIO(png))
        h_px, w_px = img.shape[0], img.shape[1]
        height = min(USABLE_WIDTH * h_px / w_px, MAX_IMAGE_HEIGHT)
        width = height * w_px / h_px
        y = self.space(height + 0.18)
        axes = self.fig.add_axes(
            (MARGIN / A4[0], (y + 0.18) / A4[1], width / A4[0], height / A4[1])
        )
        axes.imshow(img)
        axes.set_axis_off()

    def table(self, df: pd.DataFrame) -> None:
        """Draws a table, repeating the header when it continues on the next page."""
        theme = self.theme
        cols = [str(c) for c in df.columns]
        # Width proportional to content but capped: a UUID column cannot eat the others'
        # width (the full value stays in the HTML and the Excel).
        lengths = [
            min(max([len(c), *(len(str(v)) for v in df[c])]), 42) if len(df) else len(c)
            for c in cols
        ]
        total = sum(lengths) or 1
        widths = [USABLE_WIDTH * n / total for n in lengths]
        xs = [MARGIN + sum(widths[:i]) for i in range(len(widths))]
        right = [c in FMT for c in cols]  # numeric columns align right

        def header() -> None:
            self.space(0.26)
            for x, w, c, r in zip(xs, widths, cols, right, strict=True):
                self.ax.text(
                    x + w - 0.06 if r else x,
                    self.y,
                    c,
                    fontsize=8.5,
                    color=theme.ink,
                    fontfamily=theme.body,
                    fontweight="semibold",
                    ha="right" if r else "left",
                    va="baseline",
                )
            self.space(0.08)
            self.rule(theme.ink, 0.7)

        header()
        for values in df.itertuples(index=False):
            if self.y - ROW_HEIGHT < MARGIN:  # the table continues on the next page
                self._new_page()
                header()
            self.space(ROW_HEIGHT)
            for x, w, v, r in zip(xs, widths, values, right, strict=True):
                s = str(v)
                fits = int((w - 0.10) / 0.062)  # characters that fit, with some air
                if len(s) > fits:
                    s = s[: max(1, fits - 1)] + "…"
                self.ax.text(
                    x + w - 0.06 if r else x,
                    self.y,
                    s,
                    fontsize=8.5,
                    color=theme.ink,
                    # Numerals are Space Grotesk in the brand; text stays Albert Sans
                    fontfamily=theme.display if r else theme.body,
                    ha="right" if r else "left",
                    va="baseline",
                )
            self.rule(theme.rule, 0.5, dy=-0.06)
        self.space(0.20)

    def cover(self, data: _RunData, content: _Content, meta: _RunMeta) -> None:
        """Black title band, retention, KPI cards and warnings."""
        theme = self.theme
        self._new_page()
        band_h, pad = 1.60, 0.30
        base = self.space(band_h)
        self._box(MARGIN, base, USABLE_WIDTH, band_h, theme.panel)
        bottler = f" · EMBOTELLADOR {meta.bottler.upper()}" if meta.bottler else ""
        lines = (
            (
                band_h - 0.40,
                f"REPORTE EJECUTIVO · PAÍS {meta.country}{bottler}",
                7.5,
                theme.series[0],
                True,
                "semibold",
            ),
            (
                band_h - 0.84,
                "Reporte ejecutivo — limpieza Dataplor",
                19,
                theme.on_panel,
                True,
                "bold",
            ),
            (0.48, f"Generado {meta.generated_at}", 8, theme.muted, False, "normal"),
            (
                0.28,
                f"Entrada {meta.raw_name} · salida {meta.output_name}",
                8,
                theme.muted,
                False,
                "normal",
            ),
        )
        for dy, s, size, color, display, weight in lines:
            self.ax.text(
                MARGIN + pad,
                base + dy,
                s,
                fontsize=size,
                color=color,
                fontfamily=theme.display if display else theme.body,
                fontweight=weight,
                va="baseline",
            )
        self.space(1.05)
        self._accent(MARGIN, self.y - 0.08, 0.64)
        self.text(
            _pct(data.retention), size=46, x=MARGIN + 0.22, display=True, weight="bold"
        )
        self.space(0.32)
        self.text(content.hero_detail, size=11, color=theme.ink2, x=MARGIN + 0.22)
        self.space(0.30)
        self._cards(content.cards)
        for warning in content.warnings:
            base = self.space(0.56) + 0.12
            self._box(MARGIN, base, USABLE_WIDTH, 0.40, theme.layout)
            self._accent(MARGIN + 0.14, base + 0.10, 0.20)
            short = warning if len(warning) <= 125 else warning[:124] + "…"
            self.ax.text(
                MARGIN + 0.32,
                base + 0.15,
                f"Aviso · {short}",
                fontsize=7.5,
                color=theme.ink,
                fontfamily=theme.body,
                va="baseline",
            )

    def _cards(self, cards: Sequence[_Card]) -> None:
        """KPI cards in rows of 3; each row is reserved whole before drawing.

        The highlighted card (the deliverable) is black with its value in Kin Yellow,
        the only place yellow text is allowed: on a dark surface.
        """
        theme = self.theme
        sep, card_h = 0.14, 0.92
        card_w = (USABLE_WIDTH - 2 * sep) / 3
        for i in range(0, len(cards), 3):
            base = self.space(card_h + sep) + sep  # bottom edge of the cards
            for j, card in enumerate(cards[i : i + 3]):
                x = MARGIN + j * (card_w + sep)
                hl = card.highlighted
                self._box(x, base, card_w, card_h, theme.panel if hl else theme.layout)
                for dy, s, size, color, display, weight in (
                    (
                        card_h - 0.26,
                        f"{card.op} {card.title}".strip().upper(),
                        6.8,
                        theme.muted,
                        False,
                        "semibold",
                    ),
                    (
                        card_h - 0.60,
                        card.value,
                        17,
                        theme.series[0] if hl else theme.ink,
                        True,
                        "bold",
                    ),
                    (
                        0.16,
                        card.detail,
                        7.2,
                        theme.on_panel if hl else theme.ink2,
                        False,
                        "normal",
                    ),
                ):
                    self.ax.text(
                        x + 0.16,
                        base + dy,
                        s,
                        fontsize=size,
                        color=color,
                        fontfamily=theme.display if display else theme.body,
                        fontweight=weight,
                        va="baseline",
                    )

    def close(self) -> None:
        """Flushes the current page into the PDF."""
        if self._fig is not None:
            # PdfPages.savefig is unannotated; the typed alias keeps this module strict. The
            # page keeps its surface colour because the figure was created under the
            # report's rc_context.
            save_page: Callable[[Figure], None] = self.pdf.savefig
            save_page(self._fig)
            self._fig, self._ax = None, None


def _export_pdf(
    target: Path,
    data: _RunData,
    content: _Content,
    meta: _RunMeta,
    theme: _Theme,
    logo_png: bytes | None,
) -> Path:
    """A4 paginated PDF, same content as the HTML, to print or attach."""
    with PdfPages(target) as pdf:
        page = _PdfReport(pdf, theme, logo_png)
        page.cover(data, content, meta)
        for title, figs, tables in _report_blocks(content):
            if not any(k in content.figs for k in figs) and not any(
                k in content.tables for k in tables
            ):
                continue
            page.section_title(title)
            for kind, key in _block_items(figs, tables):
                if kind == "fig" and key in content.figs:
                    page.image(content.figs[key])
                elif kind == "table" and key in content.tables:
                    page.table(content.tables[key])
        page.close()
        info = pdf.infodict()
        info["Title"] = f"Reporte ejecutivo — limpieza Dataplor {meta.country}"
        info["Subject"] = (
            f"Retención {_pct(data.retention)} · {_thousands(data.n_initial)} registros iniciales"
        )
    return target


# =============================================================================
# Summary
# =============================================================================
def _summary(
    data: _RunData, meta: _RunMeta, base_name: str, n_warnings: int
) -> dict[str, int | float | str]:
    """Key numbers for the graph state (JSON-friendly scalars only)."""
    by_step = data.drops.groupby("paso").size()
    summary: dict[str, int | float | str] = {
        "country": meta.country,
        "bottler": meta.bottler,
        "channel": data.channel or "",
        "report_name": base_name,
        "initial_rows": data.n_initial,
        "pipeline_steps": data.pipeline_steps,
        "pipeline_drops": data.pipeline_drops,
        "full_dataset_rows": data.n_full,
        "out_of_channel_rows": len(data.out_of_channel),
        "channel_rows": data.n_channel,
        "manual_deletions": len(data.manual),
        "final_rows": data.n_final,
        "total_drops": len(data.drops),
        "retention_pct": round(data.retention, 4),
        "reconciliation_gap": data.n_initial - len(data.drops) - data.n_final,
        "warnings": n_warnings,
    }
    for code, label in STEP_NAMES.items():
        summary[f"drops_step_{code}"] = int(by_step.get(label, 0))
    return summary

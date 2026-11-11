"""Results deck of a prospecting run, filled into the Kin prospecting template.

The template (``assets/prospecting_deck_template.pptx``) is the approved Golfo deck with
every client-specific text, number and image replaced by placeholders (see
``scripts/build_prospecting_deck_template.py``). Here each slide is filled by shape id:
text keeps the run formatting of the template, tables keep their cell style, the
category bars are rescaled, and the images (client base summary, hexagon map, data
previews) are drawn with the brand fonts and colors and placed in the template's box.
Logos and hexagons stay the template's own pictures: nothing brand-related is drawn.
"""

import copy
import io
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import polars as pl
from matplotlib.figure import Figure
from pptx import Presentation
from pptx.slide import Slide
from pptx.util import Emu

from cleaning_agent.adapters.brand import KinBrand
from cleaning_agent.domain.models import GoldPackageRequest

PREVIEW_ROWS = 6
# Data preview images (slides 18-20): column groups of the BOTTLER file, no client data
PREVIEWS = (
    ("dataplor_id", "name", "business_category", "city", "state", "channel_cat"),
    (
        "price_level",
        "number_of_reviews",
        "average_stars",
        "monday_hours",
        "friday_hours",
        "saturday_hours",
    ),
    (
        "prioridad",
        "probability_existence_cat",
        "weighted_combined_score",
        "pop_density",
        "car_mobility",
        "dist_to_main_road",
    ),
)


def es_int(value: float) -> str:
    """1767 -> 1.767 (Spanish thousands separator, as the Golfo deck)."""
    return f"{round(value):,}".replace(",", ".")


def es_pct(value: float, decimals: int = 2) -> str:
    return (
        f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    )


# --- low-level fill helpers -----------------------------------------------------------
def _shape(slide: Slide, shape_id: int) -> Any:
    for shape in slide.shapes:
        if shape.shape_id == shape_id:
            return shape
    raise KeyError(f"shape {shape_id} not in slide")


def _set_text(shape: Any, lines: list[str] | str) -> None:
    """Replaces the text keeping the first run's formatting of each paragraph."""
    lines = [lines] if isinstance(lines, str) else lines
    frame = shape.text_frame
    paragraphs = frame.paragraphs
    template = paragraphs[0]._p
    while len(frame.paragraphs) < len(lines):
        template.addnext(copy.deepcopy(template))
    for paragraph, line in zip(frame.paragraphs, lines, strict=False):
        runs = paragraph.runs
        if runs:
            runs[0].text = line
            for extra in runs[1:]:
                extra._r.getparent().remove(extra._r)
        else:
            paragraph.add_run().text = line
    for paragraph in list(frame.paragraphs)[len(lines) :]:
        paragraph._p.getparent().remove(paragraph._p)


def _set_rich(shape: Any, paragraphs: list[list[str]]) -> None:
    """Paragraphs of [bold lead, normal rest] (the 'Etapa n |' layout of slide 14)."""
    frame = shape.text_frame
    base = frame.paragraphs[0]._p
    while len(frame.paragraphs) < len(paragraphs):
        base.addnext(copy.deepcopy(base))
    for paragraph, parts in zip(frame.paragraphs, paragraphs, strict=False):
        runs = paragraph.runs
        for run, text in zip(runs, parts, strict=False):
            run.text = text
        for extra in runs[len(parts) :]:
            extra._r.getparent().remove(extra._r)
    for paragraph in list(frame.paragraphs)[len(paragraphs) :]:
        paragraph._p.getparent().remove(paragraph._p)


def _set_table(shape: Any, rows: list[list[str]]) -> None:
    table = shape.table
    for r, values in enumerate(rows[: len(table.rows)]):
        for c, value in enumerate(values[: len(table.columns)]):
            frame = table.cell(r, c).text_frame
            runs = frame.paragraphs[0].runs
            if runs:
                runs[0].text = value
                for extra in runs[1:]:
                    extra._r.getparent().remove(extra._r)
            else:
                frame.paragraphs[0].add_run().text = value


def _png_size(png: bytes) -> tuple[int, int]:
    # PNG header: width and height are big-endian at bytes 16-24
    return int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")


def _replace_picture(
    slide: Slide, shape_id: int, png: bytes, fit: str = "center"
) -> None:
    """Swaps the image of a template picture in place, keeping its shape id (the
    template and the renderer share ids).

    fit="center": aspect kept, centred in the box (generated charts and tables).
    fit="box": the image takes the whole box (template placeholders keep the box size
    so the renderer later fills the original area).
    fit="left": aspect kept, same height, anchored left (footer logos).
    """
    picture = _shape(slide, shape_id)
    blip = picture._element.blipFill.blip
    old_rel = blip.rEmbed
    _part, rel_id = slide.part.get_or_add_image_part(io.BytesIO(png))
    blip.rEmbed = rel_id
    # Drop the old image so it does not stay inside the file (it may hold client data)
    if old_rel != rel_id:
        slide.part.drop_rel(old_rel)
    width_px, height_px = _png_size(png)
    box_left, box_top, box_w, box_h = (
        picture.left,
        picture.top,
        picture.width,
        picture.height,
    )
    if fit == "left":
        picture.height = box_h
        picture.width = int(box_h * width_px / height_px)
    elif fit == "center":
        scale = min(box_w / width_px, box_h / height_px)
        picture.width, picture.height = int(width_px * scale), int(height_px * scale)
        picture.left = box_left + (box_w - picture.width) // 2
        picture.top = box_top + (box_h - picture.height) // 2
    # The template crop of the old image must not cut the new one
    for side in ("crop_left", "crop_right", "crop_top", "crop_bottom"):
        setattr(picture, side, 0.0)


# --- generated images (brand fonts and token colors) ---------------------------------
def _png(fig: Figure) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(
        buffer,
        format="png",
        dpi=200,
        bbox_inches="tight",
        facecolor=fig.get_facecolor(),
    )
    plt.close(fig)
    return buffer.getvalue()


def _table_image(
    brand: KinBrand, header: list[str], rows: list[list[str]], width: float = 11.0
) -> bytes:
    display, body = brand.matplotlib_fonts()
    fig, ax = plt.subplots(figsize=(width, 0.42 * (len(rows) + 1) + 0.2))
    fig.patch.set_facecolor(brand.color("ka-color-white"))
    ax.axis("off")
    table = ax.table(cellText=rows, colLabels=header, loc="center", cellLoc="left")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    for (r, _c), cell in table.get_celld().items():
        # Data values like "$$" (price_level) are text, never math formulas
        cell.get_text().set_parse_math(False)
        cell.set_edgecolor(brand.color("ka-color-gray-2"))
        if r == 0:
            cell.set_facecolor(brand.color("ka-color-gray-4"))
            cell.get_text().set_color(brand.color("ka-color-white"))
            cell.get_text().set_fontfamily(display)
            cell.get_text().set_fontweight("bold")
        else:
            cell.set_facecolor(
                brand.color("ka-color-gray-1")
                if r % 2 == 0
                else brand.color("ka-color-white")
            )
            cell.get_text().set_fontfamily(body)
    table.scale(1, 1.35)
    return _png(fig)


def _hex_map_image(brand: KinBrand, prospects: pl.DataFrame, city: str) -> bytes:
    """Density of High/Moderate prospects per H3 hexagon in the top city (offline)."""
    import h3

    display, body = brand.matplotlib_fonts()
    focus = prospects.filter(
        (pl.col("city") == city)
        & pl.col("probability_existence_cat")
        .str.to_lowercase()
        .is_in(["high", "moderate"])
    )
    counts = focus.group_by("hex_8").len()
    fig, ax = plt.subplots(figsize=(6, 5))
    surface = brand.color("ka-color-gray-4")
    fig.patch.set_facecolor(surface)
    ax.set_facecolor(surface)
    peak = max(counts.get_column("len").to_list() or [1])
    yellow = brand.color("ka-color-yellow")
    for cell, count in counts.iter_rows():
        ring = h3.cell_to_boundary(cell)
        ax.fill(
            [p[1] for p in ring],
            [p[0] for p in ring],
            color=yellow,
            alpha=0.2 + 0.8 * count / peak,
            linewidth=0.3,
            edgecolor=brand.color("ka-color-black"),
        )
    # Frame on where most points are: a few far-off points (same city name, elsewhere)
    # would otherwise shrink the map to a corner
    lat = focus.get_column("latitude").cast(pl.Float64, strict=False).drop_nulls()
    lon = focus.get_column("longitude").cast(pl.Float64, strict=False).drop_nulls()
    if lat.len() > 10:
        low_lat, high_lat = lat.quantile(0.02) or 0.0, lat.quantile(0.98) or 0.0
        low_lon, high_lon = lon.quantile(0.02) or 0.0, lon.quantile(0.98) or 0.0
        pad_lat, pad_lon = (high_lat - low_lat) * 0.08, (high_lon - low_lon) * 0.08
        ax.set_ylim(low_lat - pad_lat, high_lat + pad_lat)
        ax.set_xlim(low_lon - pad_lon, high_lon + pad_lon)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(
        f"{city}: prospectos High y Moderate por hexágono",
        color=brand.color("ka-color-white"),
        fontfamily=display,
        fontsize=11,
    )
    ax.text(
        0.0,
        -0.04,
        "Más amarillo = más prospectos · H3 resolución 8",
        transform=ax.transAxes,
        color=brand.color("ka-color-gray-3"),
        fontfamily=body,
        fontsize=8,
    )
    return _png(fig)


# --- the deck -----------------------------------------------------------------------
def category_label(category: str) -> str:
    """ice_cream_shop -> Ice Cream Shop (how the Golfo deck shows categories)."""
    return category.replace("_", " ").strip().title() if category else category


def _display_figures(figures: dict[str, Any]) -> dict[str, Any]:
    """Same figures with readable category names (the data files keep the raw ones)."""
    shown = dict(figures)
    shown["categories"] = [(category_label(c), v) for c, v in figures["categories"]]
    shown["category_table"] = [
        {**row, "categoria": category_label(row["categoria"])}
        for row in figures["category_table"]
    ]
    shown["city_table"] = [
        {**row, "categoria": category_label(row["categoria"])}
        for row in figures["city_table"]
    ]
    shown["stages"] = [
        {**stage, "categorias": [category_label(c) for c in stage["categorias"]]}
        for stage in figures["stages"]
    ]
    return shown


def render_deck(
    template: Path,
    target: Path,
    figures: dict[str, Any],
    request: GoldPackageRequest,
    prospects: pl.DataFrame,
    brand: KinBrand,
) -> None:
    prs = Presentation(str(template))
    slides: list[Slide] = list(prs.slides)

    def slide(number: int) -> Slide:
        return slides[number - 1]

    f = _display_figures(figures)
    bottler, country = request.bottler_label, request.country_label
    nm = f["no_match"]

    # 1 · cover
    _set_text(_shape(slide(1), 24), f"{country} - {request.client_label}")
    _set_text(_shape(slide(1), 25), request.period_label)
    # 5 · client base used (summary, no client rows)
    _set_text(
        _shape(slide(5), 80),
        [
            f"Maestra de clientes - {request.client_label}",
            f"({es_int(f['clients_total'])} clientes)",
        ],
    )
    _replace_picture(
        slide(5),
        79,
        _table_image(
            brand,
            ["Indicador", "Valor"],
            [
                ["Clientes en la maestra del bottler", es_int(f["clients_total"])],
                [
                    "Puntos Dataplor On Premise (limpios, sin franquicias)",
                    es_int(f["dataplor_total"]),
                ],
                [
                    "Puntos Dataplor que ya son clientes (Datamatch)",
                    es_int(f["matched"]),
                ],
                ["Prospectos (no match)", es_int(f["no_match_total"])],
                ["Prospectos High + Moderate", es_int(f["hm_total"])],
            ],
            width=9,
        ),
    )
    # 9 · starting point
    _set_text(
        _shape(slide(9), 132),
        f"El análisis presentado tuvo en cuenta la zona clave de operación de la embotelladora en {bottler} ({country}), el canal On Premise y las categorías de negocio que se exponen más adelante.",
    )
    _set_table(
        _shape(slide(9), 135),
        [
            ["Dataplor", "Embotellador"],
            [es_int(f["dataplor_total"]), es_int(f["clients_total"])],
        ],
    )
    _set_text(
        _shape(slide(9), 138),
        f"{es_int(nm['high'])} high & {es_int(nm['moderate'])} moderate no-match",
    )
    _set_text(_shape(slide(9), 141), f"{es_int(nm['low'])} no-match")
    _set_text(_shape(slide(9), 144), f"{es_int(f['matched'])} Match")
    _set_table(
        _shape(slide(9), 150),
        [
            ["No match", "POS"],
            ["High", es_int(nm["high"])],
            ["Moderate", es_int(nm["moderate"])],
            ["Low", es_int(nm["low"])],
            ["Total", es_int(f["no_match_total"])],
        ],
    )
    # 10 · results by city
    _set_text(
        _shape(slide(10), 163),
        "A continuación se presenta el potencial total identificado en la prospección digital, desglosado por ciudad. Esta vista permite priorizar los mercados con mayor concentración de puntos High y Moderate en On Premise, para enfocar los esfuerzos comerciales donde el impacto puede ser más alto.",
    )
    city_rows = [["Ciudad", "On Premise", "Total"]] + [
        [c, es_int(v), es_int(v)] for c, v in f["cities"]
    ]
    while len(city_rows) < 4:
        city_rows.append(["—", "0", "0"])
    city_rows += [
        ["Otros", es_int(f["city_others"]), es_int(f["city_others"])],
        ["Total", es_int(f["hm_total"]), es_int(f["hm_total"])],
    ]
    _set_table(_shape(slide(10), 166), city_rows)
    _set_text(
        _shape(slide(10), 168),
        f"{f['top_city']} concentra {es_int(f['top_city_count'])} de los {es_int(f['hm_total'])} potenciales nuevos POS de High y Moderate",
    )
    _set_text(
        _shape(slide(10), 169),
        f"Insight: El {es_pct(f['pct_outside'], 1)} % del potencial ({es_int(f['hm_outside'])} puntos) se ubica a más de 300 m de un cliente actual. La oportunidad está en ampliar la cobertura, además de aprovechar las zonas donde ya existe presencia.",
    )
    # 11 · categories (labels, values and bars rescaled)
    cats = f["categories"]
    top2 = " y ".join(c.lower() for c, _ in cats[:2])
    _set_text(
        _shape(slide(11), 181),
        f"En la prospección digital se identifica una alta concentración de puntos por categoría. Para On Premise, {top2} representan cerca del {es_pct(f['pct_top2'], 0)}% del total de oportunidad High y Moderate. Estas categorías concentran la mayor parte del potencial y guían las prioridades comerciales.",
    )
    _fill_bars(slide(11), cats)
    _set_text(
        _shape(slide(11), 209),
        f"Insight: {es_pct(f['pct_top2'], 1)}% del potencial High y Moderate está en {top2}: las categorías de mayor valor para prospectar.",
    )
    # 12 · opportunity detail
    top5 = ", ".join(r["categoria"] for r in f["category_table"][:5])
    _set_text(
        _shape(slide(12), 221),
        f"Para el canal On Premise, la mayor parte del potencial High–Moderate se concentra en {top5}, que en conjunto representan cerca del {es_pct(f['pct_top5'], 0)}% de la oportunidad. Además, {f['top_city']} concentra {es_int(f['top_city_count'])} de los {es_int(f['hm_total'])} puntos High–Moderate.",
    )
    _set_table(
        _shape(slide(12), 225),
        [["Business Category", "High", "Moderate", "Total"]]
        + [
            [
                r["categoria"],
                es_int(r["high"]),
                es_int(r["moderate"]),
                es_int(r["total"]),
            ]
            for r in f["category_table"]
        ],
    )
    header = [
        "Business Category",
        *[c[:14] for c in f["city_columns"]],
        "Otros",
        "Total",
    ]
    while len(header) < 5:
        header.insert(-2, "—")
    body = [
        [r["categoria"], *[es_int(v) for v in r["valores"]]] for r in f["city_table"]
    ]
    _set_table(
        _shape(slide(12), 229),
        [header]
        + [
            row if len(row) == 5 else [row[0], *(["0"] * (5 - len(row))), *row[1:]]
            for row in body
        ],
    )
    first2 = f["category_table"][:2]
    _set_text(
        _shape(slide(12), 230),
        f"Insight: {first2[0]['categoria']} y {first2[1]['categoria']} suman {es_int(first2[0]['total'] + first2[1]['total'])} puntos High–Moderate."
        if len(first2) == 2
        else "",
    )
    # 13 · hexagon map of the top city
    _set_text(
        _shape(slide(13), 242),
        f"{f['top_city']} concentra la mayor cantidad de puntos con alta probabilidad de existencia",
    )
    _set_text(
        _shape(slide(13), 243),
        f"Considerando que {f['top_city']} es el mercado con la mayor concentración de puntos High y Moderate, el análisis espacial por hexágonos muestra dónde se agrupan: las celdas más amarillas son las áreas prioritarias donde se recomienda focalizar los esfuerzos comerciales.",
    )
    _replace_picture(slide(13), 244, _hex_map_image(brand, prospects, f["top_city"]))
    # 14 · impact by stages
    _set_text(
        _shape(slide(14), 255),
        f"A partir del análisis de prospección digital en {bottler} ({country}), identificamos oportunidades para ampliar la cobertura comercial de {request.client_label} en el canal On Premise, mediante una estrategia de activación progresiva de puntos de venta (POS) con potencial High y Moderate.",
    )
    names = (
        "Categorías prioritarias",
        "Ampliación de categorías",
        "Expansión de cobertura",
        "Cobertura complementaria",
    )
    _set_rich(
        _shape(slide(14), 257),
        [
            [
                f"Etapa {s['etapa']} | {names[s['etapa'] - 1]}:",
                f" {', '.join(s['categorias'])}{' y otras' if s['etapa'] == 4 else ''}: +{es_int(s['pos'])} POS (+{es_pct(s['pct'])} %; +{es_pct(s['pct_acumulado'])} % acumulado).",
            ]
            for s in f["stages"]
        ],
    )
    _set_text(
        _shape(slide(14), 258),
        f"Las cuatro etapas identifican un potencial bruto de {es_int(f['hm_total'])} nuevos POS: {es_int(f['hm_inside'])} dentro del radio actual de las rutas y {es_int(f['hm_outside'])} fuera de este. Esto representa un crecimiento potencial del {es_pct(f['pct_growth'])} % sobre los {es_int(f['clients_total'])} POS actuales.",
    )
    _set_text(
        _shape(slide(14), 259),
        f"* Considerando una tasa estimada de validación en campo del 50 %–70 %, se proyecta una captura neta de {es_int(f['capture_low'])}–{es_int(f['capture_high'])} POS, equivalente a un crecimiento del {es_pct(f['pct_capture_low'])} %–{es_pct(f['pct_capture_high'])} %. Estos resultados están sujetos a validación.",
    )
    # 18-20 · data previews (BOTTLER columns, no client data)
    for number, picture_id, columns in (
        (18, 298, PREVIEWS[0]),
        (19, 317, PREVIEWS[1]),
        (20, 336, PREVIEWS[2]),
    ):
        present = [c for c in columns if c in prospects.columns]
        sample = prospects.select(present).head(PREVIEW_ROWS).fill_null("—")
        rows = [[str(v)[:28] for v in row] for row in sample.iter_rows()]
        _replace_picture(slide(number), picture_id, _table_image(brand, present, rows))
    # 21 · contacts (Kin staff from config; never a tagline the brand forbids)
    _set_text(_shape(slide(21), 347), "Gracias")
    _set_text(_shape(slide(21), 348), "Contactos:" if request.contacts else "")
    contact_ids = (349, 350, 351)
    for shape_id, contact in zip(
        contact_ids, [*request.contacts, "", "", ""], strict=False
    ):
        _set_text(_shape(slide(21), shape_id), contact)
    target.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(target))


# Slide 11 rows of the template: (label, bar, value) shape ids, top category first
BAR_ROWS = (
    (185, 186, 187),
    (188, 189, 190),
    (191, 192, 193),
    (194, 195, 196),
    (197, 198, 199),
    (200, 201, 202),
    (203, 204, 205),
    (206, 207, 208),
)
BAR_FULL_WIDTH = Emu(int(2.92 * 914400))  # width of the longest bar in the template
BAR_MIN_WIDTH = Emu(int(0.05 * 914400))
VALUE_WIDTH = Emu(int(0.7 * 914400))
VALUE_GAP = Emu(int(0.08 * 914400))


def _fill_bars(slide: Slide, categories: list[tuple[str, int]]) -> None:
    """Slide 11: 8 rows of category, bar and count; the bar scales with the count."""
    peak = max((v for _, v in categories), default=1) or 1
    for i, (label_id, bar_id, value_id) in enumerate(BAR_ROWS):
        label, bar, value = (_shape(slide, s) for s in (label_id, bar_id, value_id))
        name, count = categories[i] if i < len(categories) else ("", 0)
        _set_text(label, name)
        _set_text(value, es_int(count) if name else "")
        bar.width = (
            max(BAR_MIN_WIDTH, int(BAR_FULL_WIDTH * count / peak))
            if name
            else BAR_MIN_WIDTH
        )
        value.left = bar.left + bar.width + VALUE_GAP
        # Room for "4.625": the template box fitted three digits and wrapped the rest
        value.width = VALUE_WIDTH
        value.text_frame.word_wrap = False

"""Builds the prospecting deck template from an approved delivery deck (one-off).

    uv run python scripts/build_prospecting_deck_template.py <approved_deck.pptx>

The approved Golfo deck is the model of every prospecting results deck. This script
keeps its Kin design (photos, logos, layout) and removes everything that belongs to that
client: texts and numbers become {{placeholders}}, tables are emptied and the images with
client data (client base screenshot, hexagon map, data previews) become neutral
placeholders. The tagline the brand forbids ("Let knowledge in") is removed and staff
emails become placeholders. Shape ids are kept: the renderer
(cleaning_agent/adapters/prospecting_deck.py) fills the slides by those ids.

Output: cleaning_agent/adapters/assets/prospecting_deck_template.pptx
"""

import io
import re
import sys
import zipfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pptx import Presentation
from pptx.slide import Slide

from cleaning_agent.adapters.brand import (
    BUNDLED_ASSETS_DIR,
    LOGO_FORMAL_DARK,
    LOGO_FORMAL_LIGHT,
    KinBrand,
)
from cleaning_agent.adapters.prospecting_deck import (
    BAR_ROWS,
    _replace_picture,
    _set_rich,
    _set_table,
    _set_text,
    _shape,
)

TARGET = (
    Path(__file__).resolve().parents[1]
    / "cleaning_agent/adapters/assets/prospecting_deck_template.pptx"
)

TEXTS: dict[tuple[int, int], str | list[str]] = {
    (1, 24): "{{pais}} - {{cliente}}",
    (1, 25): "{{periodo}}",
    (5, 80): ["Maestra de clientes - {{cliente}}", "({{clientes}} clientes)"],
    (9, 132): "{{texto_punto_de_partida}}",
    (9, 138): "{{high}} high & {{moderate}} moderate no-match",
    (9, 141): "{{low}} no-match",
    (9, 144): "{{match}} Match",
    (10, 163): "{{texto_resumen_ciudades}}",
    (
        10,
        168,
    ): "{{ciudad_top}} concentra {{n}} de los {{total_hm}} potenciales nuevos POS",
    (10, 169): "{{insight_fuera_de_radio}}",
    (11, 181): "{{texto_categorias}}",
    (11, 209): "{{insight_categorias}}",
    (12, 221): "{{texto_detalle_oportunidad}}",
    (12, 230): "{{insight_top2}}",
    (
        13,
        242,
    ): "{{ciudad_top}} concentra la mayor cantidad de puntos con alta probabilidad de existencia",
    (13, 243): "{{texto_mapa_hexagonos}}",
    (14, 255): "{{texto_impacto}}",
    (14, 258): "{{texto_potencial_bruto}}",
    (14, 259): "{{texto_captura_neta}}",
    (21, 347): "Gracias",
    (21, 349): "{{contacto_1}}",
    (21, 350): "{{contacto_2}}",
    (21, 351): "{{contacto_3}}",
}
TABLES = {
    (9, 135): (2, 2),
    (9, 150): (5, 2),
    (10, 166): (6, 3),
    (12, 225): (8, 4),
    (12, 229): (8, 5),
}
CLIENT_PICTURES = ((5, 79), (13, 244), (18, 298), (19, 317), (20, 336))
# Slides on a dark surface: their footer logo is the white-wordmark file
DARK_SLIDES = {4, 5, 16}
# Cover image with the forbidden tagline baked in ("Let knowledge in. KinAnalytics.com")
COVER_TAGLINE_PICTURE = (1, 27)
EMU_PER_INCH = 914400


def _logo_png(relative: str, height_px: int = 160) -> bytes:
    """Rasterizes an approved logo SVG (never redrawn): PyMuPDF renders the file.

    Run this script with: uv run --with pymupdf python scripts/build_prospecting_deck_template.py
    """
    import pymupdf

    # MuPDF ignores the SVG's <style> classes (.cls-1{fill:#fff}) and paints everything
    # black: copy each class's fill onto its elements. Same file, same colors.
    svg = (BUNDLED_ASSETS_DIR / relative).read_text(encoding="utf-8")
    fills: dict[str, str] = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^}]*)\}", svg):
        fill = re.search(r"fill:\s*([^;]+)", body)
        if fill:
            for name in re.findall(r"\.([\w-]+)", selectors):
                fills[name] = fill.group(1).strip()
    for name, color in fills.items():
        svg = re.sub(rf'class="{name}"', f'fill="{color}"', svg)
    document = pymupdf.open(stream=svg.encode("utf-8"), filetype="svg")
    page = document[0]
    zoom = height_px / page.rect.height
    return bytes(
        page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True).tobytes("png")
    )


def _replace_footer_logos(slides: list[Slide]) -> None:
    """The source footers are images of the logo plus the forbidden tagline: they
    become the approved formal wordmark (FV_13 on light slides, FV_19 on dark ones)."""
    light, dark = _logo_png(LOGO_FORMAL_LIGHT), _logo_png(LOGO_FORMAL_DARK)
    for number, slide in enumerate(slides, start=1):
        if number == COVER_TAGLINE_PICTURE[0]:
            cover = _shape(slide, COVER_TAGLINE_PICTURE[1])
            cover._element.getparent().remove(cover._element)
        for shape in list(slide.shapes):
            is_footer_logo = (
                shape.shape_type is not None
                and "PICTURE" in str(shape.shape_type)
                and shape.top >= 6.8 * EMU_PER_INCH
                and shape.height <= 0.45 * EMU_PER_INCH
            )
            if is_footer_logo:
                _replace_picture(
                    slide,
                    shape.shape_id,
                    dark if number in DARK_SLIDES else light,
                    fit="left",
                )


def _placeholder_png(brand: KinBrand) -> bytes:
    _display, body = brand.matplotlib_fonts()
    fig, ax = plt.subplots(figsize=(8, 3))
    fig.patch.set_facecolor(brand.color("ka-color-gray-1"))
    ax.axis("off")
    ax.text(
        0.5,
        0.5,
        "Imagen generada por el agente para cada corrida",
        ha="center",
        va="center",
        fontfamily=body,
        color=brand.color("ka-color-gray-4"),
    )
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=120, facecolor=fig.get_facecolor())
    plt.close(fig)
    return buffer.getvalue()


def main(source: Path) -> None:
    brand = KinBrand(BUNDLED_ASSETS_DIR)
    prs = Presentation(str(source))
    slides = list(prs.slides)
    for (number, shape_id), text in TEXTS.items():
        _set_text(_shape(slides[number - 1], shape_id), text)
    _set_rich(
        _shape(slides[13], 257),
        [
            [f"Etapa {n} | {{{{nombre_etapa_{n}}}}}:", f" {{{{texto_etapa_{n}}}}}"]
            for n in range(1, 5)
        ],
    )
    for (number, shape_id), (rows, cols) in TABLES.items():
        _set_table(
            _shape(slides[number - 1], shape_id), [["—"] * cols for _ in range(rows)]
        )
    for i, (label, _bar, value) in enumerate(BAR_ROWS, start=1):
        _set_text(_shape(slides[10], label), f"{{{{categoria_{i}}}}}")
        _set_text(_shape(slides[10], value), "0")
    placeholder = _placeholder_png(brand)
    for number, shape_id in CLIENT_PICTURES:
        # Keep the whole box: the renderer fits each run's image into the original area
        _replace_picture(slides[number - 1], shape_id, placeholder, fit="box")
    _replace_footer_logos(slides)
    # Alt texts and speaker notes also describe the client's data: empty them
    for slide in slides:
        for shape in slide.shapes:
            shape._element.xpath("./*[1]/p:cNvPr")[0].set("descr", "")
        if slide.has_notes_slide:
            slide.notes_slide.notes_text_frame.text = ""
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(TARGET))
    _rename_themes(TARGET)
    print(f"Template written: {TARGET}")


def _rename_themes(path: Path) -> None:
    """The theme name carries the source deck's title (client and region)."""
    temporary = path.with_suffix(".tmp")
    with (
        zipfile.ZipFile(path) as source,
        zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename.startswith("ppt/theme/theme"):
                text = data.decode("utf-8")
                # theme, color scheme and font scheme names all repeat the source title
                data = re.sub(
                    r'(<a:(?:theme|clrScheme|fontScheme|fmtScheme) [^>]*?name=")[^"]*(")',
                    r"\1Kin Prospección Digital\2",
                    text,
                ).encode("utf-8")
            target.writestr(item, data)
    temporary.replace(path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))

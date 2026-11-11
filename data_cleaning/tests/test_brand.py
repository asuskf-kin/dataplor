"""Tests for the shared Kin brand adapter (tokens, fonts, logo) and the drop report."""

import re
import sys
import types
from pathlib import Path

import pytest
from matplotlib import font_manager

from cleaning_agent.adapters.brand import (
    BUNDLED_ASSETS_DIR,
    BrandTokenError,
    KinBrand,
)
from cleaning_agent.adapters.drop_report import generate_html_report
from cleaning_agent.adapters.filesystem import FileSystemAudit
from cleaning_agent.domain.models import StepMetric

BRAND = KinBrand(BUNDLED_ASSETS_DIR)
HEX = re.compile(r"#[0-9A-Fa-f]{3,8}\b|rgba?\(|hsla?\(")


def page_css_without_tokens(page: str, brand: KinBrand) -> str:
    """The page's own CSS: everything in <style> except the embedded tokens file."""
    style = re.search(r"<style>(.*?)</style>", page, re.DOTALL)
    assert style is not None
    return style.group(1).replace(brand.tokens_css, "")


def assert_on_brand_html(page: str, brand: KinBrand = BRAND) -> None:
    assert "font/woff2;base64" in page  # fonts embedded, never a CDN
    assert "--ka-color-yellow" in page  # the tokens file travels with the page
    assert "data:image/svg+xml;base64" in page  # logo placed from its approved file
    assert "kinanalytics.com" in page
    for banned in ("fonts.googleapis", "cdn.jsdelivr", "<script", "@import"):
        assert banned not in page
    assert not HEX.search(page_css_without_tokens(page, brand))


def test_colors_come_from_the_tokens_file() -> None:
    assert BRAND.color("ka-color-yellow") == "#E5FF01"
    # var() references resolve, and the light theme wins over the dark block
    assert BRAND.color("ka-chart-1") == BRAND.color("ka-color-yellow")
    assert BRAND.color("ka-color-bg") == BRAND.color("ka-color-white")
    assert BRAND.color("ka-color-text-primary") == BRAND.color("ka-color-black")
    assert BRAND.length_in("ka-radius-box") == pytest.approx(12 / 96)


def test_missing_token_is_an_error_not_a_guess(tmp_path: Path) -> None:
    (tmp_path / "tokens").mkdir()
    (tmp_path / "tokens" / "colors_and_type.css").write_text(
        ":root { --ka-color-black: #141417; }", encoding="utf-8"
    )
    brand = KinBrand(tmp_path)
    assert brand.color("ka-color-black") == "#141417"
    with pytest.raises(BrandTokenError):
        brand.color("ka-color-yellow")
    with pytest.raises(BrandTokenError):
        brand.length_in("ka-radius-box")


def test_matplotlib_fonts_register_static_brand_weights() -> None:
    display, body = BRAND.matplotlib_fonts()
    assert (display, body) == ("Space Grotesk", "Albert Sans")
    for family in (display, body):
        for weight in ("regular", "medium", "semibold", "bold"):
            found = font_manager.findfont(
                font_manager.FontProperties(family=family, weight=weight),
                fallback_to_default=False,
            )
            assert "kin-brand-fonts" in found
    BRAND.matplotlib_fonts()  # idempotent: registering twice adds nothing
    entries = [f for f in font_manager.fontManager.ttflist if f.name == display]
    assert len({f.fname for f in entries}) == len(entries)


def test_logo_png_without_rasteriser_leaves_the_slot_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "cairosvg", None)  # import now raises
    assert BRAND.logo_png() is None


def test_logo_png_rasterises_the_approved_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[bytes] = []

    def svg2png(bytestring: bytes, output_width: int) -> bytes:
        seen.append(bytestring)
        return b"png"

    monkeypatch.setitem(sys.modules, "cairosvg", types.SimpleNamespace(svg2png=svg2png))
    assert BRAND.logo_png() == b"png"
    approved = BUNDLED_ASSETS_DIR / "logos/formal/Kin_Logo_FV_13.svg"
    assert seen == [approved.read_bytes()]


METRICS = [
    {
        "step_name": "1 · Normalización",
        "dropped_count": 120,
        "remaining_count": 880,
        "top_dropped": [("Negocio <b>Ficticio</b>", 12)],
    },
    {
        "step_name": "2 · Cadenas",
        "dropped_count": 0,
        "remaining_count": 880,
        "top_dropped": [],
    },
]


def test_drop_report_is_on_brand_and_self_contained(tmp_path: Path) -> None:
    silver = tmp_path / "data" / "silver"
    path = generate_html_report(METRICS, silver, BRAND)

    assert path.parent == silver
    page = path.read_text(encoding="utf-8")
    assert_on_brand_html(page)
    # Bars are CSS, sized relative to the largest step
    assert "width:100.0%" in page and "width:0.0%" in page
    assert "No prominent exclusions recorded." in page


def test_drop_report_escapes_business_names(tmp_path: Path) -> None:
    page = generate_html_report(METRICS, tmp_path, BRAND).read_text(encoding="utf-8")
    assert "<b>Ficticio</b>" not in page
    assert "&lt;b&gt;Ficticio&lt;/b&gt;" in page


def test_drop_report_with_no_steps_still_renders(tmp_path: Path) -> None:
    page = generate_html_report([], tmp_path, BRAND).read_text(encoding="utf-8")
    assert_on_brand_html(page)


def test_audit_adapter_threads_the_brand(tmp_path: Path) -> None:
    audit = FileSystemAudit(tmp_path / "data", BRAND)
    assert audit.html_report([], tmp_path) is None
    metric = StepMetric(
        module_id=1,
        step_name="1 · Normalización",
        rows_before=10,
        rows_after=8,
        top_dropped=[("Negocio Ficticio", 2)],
    )
    path = audit.html_report([metric], tmp_path)
    assert path is not None
    assert_on_brand_html(path.read_text(encoding="utf-8"))

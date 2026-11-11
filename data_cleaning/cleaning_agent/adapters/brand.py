"""Kin brand for every HTML/PDF/chart deliverable (skill brand-guidelines-kin).

One place that embeds what the brand rules require, so no generator improvises:
- Space Grotesk + Albert Sans as base64 woff2 (no CDN, works offline / in PDF);
- the design tokens file verbatim (colors, type, radius come only from tokens);
- the logo placed from its approved SVG file as an isolated data-URI ``<img>``
  (never drawn or typeset);
- for matplotlib: token colors parsed from the same tokens file, the bundled TTFs
  registered as static weights, and the approved logo rasterised (when a rasteriser
  is installed) instead of redrawn.
"""

import base64
import hashlib
import importlib
import os
import re
import tempfile
from functools import cached_property
from pathlib import Path

from matplotlib import font_manager

LOGO_FORMAL_LIGHT = "logos/formal/Kin_Logo_FV_13.svg"  # dark wordmark: light surfaces
LOGO_FORMAL_DARK = "logos/formal/Kin_Logo_FV_19.svg"  # white wordmark: dark surfaces
# The skill bundled in this repo. wiring.py passes the configured path explicitly; this
# default only keeps direct callers of the report generators on-brand.
BUNDLED_ASSETS_DIR = (
    Path(__file__).resolve().parents[2] / ".claude/skills/brand-guidelines-kin/assets"
)
TOKENS_FILE = "tokens/colors_and_type.css"
FONT_DISPLAY_TTF = "fonts/space-grotesk.ttf"
FONT_BODY_TTF = "fonts/albert-sans.ttf"
FONT_DISPLAY_FAMILY = "Space Grotesk"
FONT_BODY_FAMILY = "Albert Sans"

# matplotlib cannot select weights on a variable font: it always renders the default
# instance (Light for Space Grotesk). Static instances per weight fix that.
_STATIC_WEIGHTS: dict[str, tuple[str, tuple[int, ...]]] = {
    FONT_DISPLAY_TTF: (FONT_DISPLAY_FAMILY, (400, 500, 600, 700)),
    FONT_BODY_TTF: (FONT_BODY_FAMILY, (400, 500, 600, 700)),
}
_WEIGHT_NAMES = {400: "Regular", 500: "Medium", 600: "SemiBold", 700: "Bold"}
_REGISTERED: set[Path] = set()  # fontManager is process-global: register each file once

_DECLARATION = re.compile(r"--([\w-]+)\s*:\s*([^;]+);")
_VAR_REF = re.compile(r"var\(--([\w-]+)\)")
_HEX = re.compile(r"#[0-9A-Fa-f]{6}")
_PX = re.compile(r"(\d+(?:\.\d+)?)px")
CSS_PX_PER_INCH = 96.0  # CSS reference pixel, to turn px tokens into print inches

# Shared page language of every Kin HTML report: light page, black title band with a
# Yellow eyebrow, stat cards, cards with a Yellow left accent and a logo + URL footer.
# Only design tokens (colors/type/radius) and rem/em units.
PAGE_CSS = """
*{box-sizing:border-box}
body{margin:0;background:var(--ka-color-bg-layout);color:var(--ka-color-text-primary);
font-family:var(--ka-font-body);font-size:var(--ka-size-body);line-height:var(--ka-lh-body)}
.page{max-width:60rem;margin:0 auto;padding:2.5rem 1rem}
table{display:block;overflow-x:auto}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem}
.kin-logo{height:1.75rem;width:auto;display:block}
.band{background:var(--ka-color-black);color:var(--ka-color-white);border-radius:var(--ka-radius-box);
padding:2rem 2.25rem;margin-bottom:1.75rem}
.eyebrow{font-family:var(--ka-font-display);font-size:var(--ka-size-overline);font-weight:var(--ka-weight-semibold);
letter-spacing:var(--ka-tracking-eyebrow);text-transform:uppercase;color:var(--ka-color-yellow);margin:0 0 .5rem}
.band h1{font-family:var(--ka-font-display);font-size:var(--ka-size-h2);font-weight:var(--ka-weight-bold);
line-height:var(--ka-lh-tight);margin:0 0 .5rem;overflow-wrap:anywhere}
.band .sub{color:var(--ka-color-gray-3);margin:0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(10rem,1fr));gap:1rem;margin-bottom:1.75rem}
.stat{background:var(--ka-color-surface);border-radius:var(--ka-radius-box);padding:1.25rem 1.5rem}
.stat .label{font-size:var(--ka-size-overline);letter-spacing:var(--ka-tracking-eyebrow);text-transform:uppercase;
color:var(--ka-color-text-secondary);font-weight:var(--ka-weight-semibold)}
.stat .value{font-family:var(--ka-font-display);font-size:var(--ka-size-h2);font-weight:var(--ka-weight-bold)}
.card{background:var(--ka-color-surface);border-radius:var(--ka-radius-box);padding:1.5rem 1.75rem;margin-bottom:1.25rem}
.card h2{font-family:var(--ka-font-display);font-size:var(--ka-size-h3);font-weight:var(--ka-weight-medium);
margin:0 0 1rem;padding-left:.75rem;border-left:.25rem solid var(--ka-color-yellow)}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:.5rem .75rem;border-bottom:.0625rem solid var(--ka-color-border);vertical-align:top}
th{font-weight:var(--ka-weight-semibold);color:var(--ka-color-text-primary)}
td.num{font-family:var(--ka-font-display);text-align:right}
code{font-family:var(--ka-font-body);font-size:var(--ka-size-caption);word-break:break-all}
.pill{display:inline-block;border-radius:var(--ka-radius-pill);padding:.125rem .75rem;font-weight:var(--ka-weight-semibold);
font-size:var(--ka-size-caption)}
.pill.ok{background:var(--ka-color-yellow);color:var(--ka-color-black)}
.pill.fail{background:var(--ka-color-black);color:var(--ka-color-white)}
.foot{display:flex;justify-content:space-between;align-items:center;margin-top:2rem}
.foot .kin-logo{height:1.375rem}
"""


class BrandTokenError(KeyError):
    """A token the deliverable needs is not in the tokens file: never improvise one."""


class KinBrand:
    def __init__(self, assets_dir: Path) -> None:
        self.assets_dir = assets_dir

    def _b64(self, relative: str) -> str:
        return base64.b64encode((self.assets_dir / relative).read_bytes()).decode()

    @cached_property
    def tokens_css(self) -> str:
        return (self.assets_dir / TOKENS_FILE).read_text(encoding="utf-8")

    @cached_property
    def head_css(self) -> str:
        """@font-face + design tokens: put inside <style> before page rules."""
        return (
            "@font-face{font-family:'Space Grotesk';"
            f"src:url('data:font/woff2;base64,{self._b64('fonts/space-grotesk.woff2')}') format('woff2');"
            "font-weight:300 700;font-style:normal}\n"
            "@font-face{font-family:'Albert Sans';"
            f"src:url('data:font/woff2;base64,{self._b64('fonts/albert-sans.woff2')}') format('woff2');"
            "font-weight:100 900;font-style:normal}\n" + self.tokens_css
        )

    def logo(
        self, relative: str = LOGO_FORMAL_LIGHT, css_class: str = "kin-logo"
    ) -> str:
        """The approved logo file as an isolated <img> (class collisions avoided)."""
        uri = "data:image/svg+xml;base64," + self._b64(relative)
        return f'<img class="{css_class}" src="{uri}" alt="Kin Analytics">'

    # --- Tokens for non-CSS renderers (matplotlib, openpyxl) --------------------
    @cached_property
    def _light_tokens(self) -> dict[str, str]:
        """Raw values of the light theme (the ``:root`` block), ``var()`` resolved.

        The dark block is skipped on purpose: reports are light pages, and mixing both
        blocks would let the dark overrides win silently.
        """
        root = re.search(r":root\s*\{(.*?)\}", self.tokens_css, re.DOTALL)
        if root is None:
            raise BrandTokenError(f"No :root block in {TOKENS_FILE}")
        raw = {
            name: value.strip() for name, value in _DECLARATION.findall(root.group(1))
        }

        def resolve(value: str, depth: int = 0) -> str:
            ref = _VAR_REF.fullmatch(value)
            if ref is None or depth > 8 or ref.group(1) not in raw:
                return value
            return resolve(raw[ref.group(1)], depth + 1)

        return {name: resolve(value) for name, value in raw.items()}

    def color(self, token: str) -> str:
        """Hex value of a color token, e.g. ``color("ka-color-yellow")`` -> ``#E5FF01``."""
        match = _HEX.fullmatch(self._light_tokens.get(token, ""))
        if match is None:
            raise BrandTokenError(f"Color token --{token} missing in {TOKENS_FILE}")
        return match.group(0).upper()

    def length_in(self, token: str) -> float:
        """A px token in inches (CSS reference pixel), for print layouts."""
        match = _PX.fullmatch(self._light_tokens.get(token, ""))
        if match is None:
            raise BrandTokenError(f"px token --{token} missing in {TOKENS_FILE}")
        return float(match.group(1)) / CSS_PX_PER_INCH

    # --- Fonts and logo for matplotlib ------------------------------------------
    def matplotlib_fonts(self) -> tuple[str, str]:
        """Registers the bundled TTFs as static weights; returns (display, body) families."""
        for relative, (family, weights) in _STATIC_WEIGHTS.items():
            source = self.assets_dir / relative
            for weight in weights:
                path = _static_instance(source, family, weight)
                if path not in _REGISTERED:
                    font_manager.fontManager.addfont(path)
                    _REGISTERED.add(path)
        return FONT_DISPLAY_FAMILY, FONT_BODY_FAMILY

    def font_files(self) -> list[str]:
        """Static TTF instances of every brand weight, for a renderer in another process."""
        return [
            str(_static_instance(self.assets_dir / relative, family, weight))
            for relative, (family, weights) in _STATIC_WEIGHTS.items()
            for weight in weights
        ]

    def logo_png(
        self, relative: str = LOGO_FORMAL_LIGHT, width_px: int = 900
    ) -> bytes | None:
        """The approved logo rasterised to PNG, or None when no rasteriser is installed.

        The brand forbids redrawing the logo, so without ``cairosvg`` the slot stays
        empty (a missing logo is acceptable, an invented one never is). The caller
        logs it, with its run's correlation id.
        """
        try:
            cairosvg = importlib.import_module("cairosvg")
        except ImportError:
            return None
        png: bytes = cairosvg.svg2png(
            bytestring=(self.assets_dir / relative).read_bytes(), output_width=width_px
        )
        return png


def _static_instance(source: Path, family: str, weight: int) -> Path:
    """Static TTF of one weight, cached by content hash so a new font regenerates it."""
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    target = (
        Path(tempfile.gettempdir())
        / "kin-brand-fonts"
        / f"{source.stem}-{weight}-{digest}.ttf"
    )
    if target.is_file():
        return target
    # fontTools ships with matplotlib (its PDF backend subsets fonts with it).
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    font = instancer.instantiateVariableFont(TTFont(source), {"wght": weight})
    style = _WEIGHT_NAMES[weight]
    postscript = f"{family.replace(' ', '')}-{style}"
    names = font["name"]
    # matplotlib matches by family name + OS/2 weight, and the PDF embeds the
    # PostScript name: all three must describe this instance, not the variable master.
    for name_id, value in (
        (1, family),
        (2, "Regular"),
        (4, f"{family} {style}"),
        (6, postscript),
        (16, family),
        (17, style),
    ):
        names.setName(value, name_id, 3, 1, 0x409)
    font["OS/2"].usWeightClass = weight
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    font.save(partial)
    partial.replace(target)  # atomic: a concurrent run never reads a half-written font
    return target

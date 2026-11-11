# PPTX implementation

Read this when producing **PowerPoint / .pptx decks**.

## START HERE — fill the template, don't rebuild

> ⛔ Every Kin deck starts from `assets/templates/Kin_Presentation_Template.pptx`. This is
> the real 20-slide Design System deck: photo covers, section dividers, the light↔dark
> system, and **Space Grotesk + Albert Sans embedded inside the file**. You **duplicate its
> slides and replace the text**. You do **not** generate slides from scratch with
> python-pptx/pptxgenjs to imitate it — that path loses the fonts, the covers, and the
> dark/light backgrounds (it's what went wrong before).

```bash
cp assets/templates/Kin_Presentation_Template.pptx /tmp/deck.pptx
# 1. preview which of the 20 layouts you want (see §09 table for the map)
python /mnt/skills/public/pptx/scripts/thumbnail.py /tmp/deck.pptx deck-thumbs
# 2. unpack to edit
python3 -c "import sys,zipfile; zipfile.ZipFile('/tmp/deck.pptx').extractall('/tmp/unpacked')"
# 3. duplicate the slides you need, in order (slideN.xml = the layout you picked)
python /mnt/skills/public/pptx/scripts/add_slide.py /tmp/unpacked slide1.xml --after slide1.xml
# 4. delete unused slides = edit <p:sldIdLst> in ppt/presentation.xml, then:
python /mnt/skills/public/pptx/scripts/clean.py /tmp/unpacked
# 5. edit text in ppt/slides/slideN.xml (see rules below), then repack from INSIDE the dir:
(cd /tmp/unpacked && rm -f /tmp/out.pptx && zip -Xr /tmp/out.pptx .)
# 6. validate against the template so its own quirks aren't read as your errors:
python /mnt/skills/public/pptx/scripts/office/validate.py /tmp/out.pptx --original assets/templates/Kin_Presentation_Template.pptx
```

**Editing text without wrecking the styling:**
- Replace text by assigning **`run.text`**, never `text_frame.text` (the latter collapses
  the paragraph to one unstyled run and you lose Space Grotesk / the Yellow word).
- One `<a:p>` per list item; copy the sibling `<a:pPr>` to keep spacing. Keep `b="1"` on
  titles/labels that already have it.
- Parse XML with `defusedxml.minidom` — round-tripping through `xml.etree` rewrites
  namespace prefixes and corrupts the deck.
- **Template slots ≠ your item count.** If a layout has 4 cards and you have 3, delete the
  4th card's whole shape group (not just its text), then QA for orphaned art.
- Keep each slide's background (dark photo / solid dark / light gray) — don't flatten it to
  a plain fill. The dark/light switch is per-slide and part of the system.

**Fonts are already embedded** in the template (Space Grotesk + Albert Sans, regular +
bold), so a filled deck keeps Kin's type on any machine. If you add a brand-new slide that
somehow references another weight and it substitutes, install the bundled TTFs and re-embed
(see "Fonts" below) — but for normal fill work you don't need to touch fonts at all.

## Building a one-off slide from scratch (rare — only if no layout fits)

If — and only if — you must author a slide with no template equivalent, `python-pptx` /
pptxgenjs reference the font by name and Office **cannot** consume woff2, so install the
bundled **TTFs** first (they ship at `assets/fonts/*.ttf`):

```bash
mkdir -p ~/.fonts && cp assets/fonts/*.ttf ~/.fonts/ && fc-cache -f
```

The bundled TTFs are **variable** fonts. Some Office/renderer paths read only a single
static instance — if a weight renders wrong, instance the needed weight to a static TTF
with fontTools before installing:

```python
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.ttLib import TTFont
f = TTFont("assets/fonts/space-grotesk.ttf")
instantiateVariableFont(f, {"wght": 700}, inplace=True)   # e.g. Bold
f.save("/tmp/SpaceGrotesk-Bold.ttf")
```

> Space Grotesk's variable default axis is 300 and its internal family name is
> "Space Grotesk Light" — set the weight/face **explicitly** or it renders Light.

Then set the face explicitly:

```js
{ fontFace: "Space Grotesk", bold: true }   // Headings, titles
{ fontFace: "Space Grotesk" }               // Sub-headings, labels
{ fontFace: "Albert Sans" }                 // Body text (Regular)
{ fontFace: "Albert Sans", italic: true }   // Body emphasis variant (albert-sans-italic.ttf)
```

**A scratch-built deck must embed the fonts** or it loses them off your machine. Embed by
adding the static TTFs to `ppt/fonts/*.fntdata`, declaring the `fntdata` content-type,
setting `embedTrueTypeFonts="1"` on `<p:presentation>`, and adding an `<p:embeddedFontLst>`
**immediately after `<p:notesSz>`** (schema order matters — anywhere else fails validation)
with font relationships in `presentation.xml.rels`. Then validate.

## Logos & hexagons — PLACE THE FILE, never draw it

> ⛔ **Hard rule (ADHERENCE #5).** In PPTX, **never** reconstruct the logo or a hexagon
> with `shapes.add_shape`, `MSO_SHAPE`, freeform/`add_freeform`, text set in a font, or
> polygons. The "Kin" wordmark is vector paths and the hexagon is a polygon **inside the
> approved SVG files** — you rasterize the *file* and place it as a picture. If you find
> yourself building a shape to look like the logo or a hexagon, STOP: that is the bug that
> produces wrong "Kin" letters and mis-shaped hexagons. If no file fits, leave the slot
> empty and tell the user which file is missing.

`python-pptx` needs a raster, so rasterize the approved SVG (render 2–3× the display size
for crisp scaling), then place it with `add_picture`. Never `add_shape`.

```python
import io, cairosvg
from pptx.util import Inches

def place_svg(slide, rel_path, left, top, **size):
    """Rasterize an approved SVG and place it. The ONLY way a logo/hexagon enters a slide."""
    png = cairosvg.svg2png(url=rel_path, output_width=900)  # render big, scale down
    return slide.shapes.add_picture(io.BytesIO(png), left, top, **size)

# Footer wordmark — pick by surface (§10):
place_svg(slide, "assets/logos/formal/Kin_Logo_FV_19.svg",  # dark slide  (FV_13 on light/gray)
          Inches(0.3), Inches(6.9), height=Inches(0.35))

# A hexagon accent (journey step, "vs" mark, bullet) — from file, never add_shape:
place_svg(slide, "assets/logos/symbol/Kin_Logo_S_14.svg",   # yellow hex (S_13 = gray)
          Inches(0.5), Inches(2.0), height=Inches(0.6))
```

## Section divider — the yellow hexagon-point (chevron), not a plain stripe

The divider accent is **the pointed tip of a hexagon** (an arrow/chevron shape pointing
into the slide, as in reference slide 03) — **not** a plain rectangular yellow stripe or
band. Build it one of two correct ways, never as a flat `<rect>`/stripe:

- **Preferred**: rasterize an approved hexagon SVG (`assets/hexagons/patterns/hex-solid.svg`
  recolored to Yellow, or the yellow symbol mark) and place it with `place_svg`, positioned
  so its point enters the content area.
- If a shape is unavoidable, use a **6-sided regular polygon** via `add_freeform` at its
  **original hexagon proportion** (point-up/point-in, equal sides) — never a stretched
  quad, never a rectangle. Fill with the Yellow token color only.

The numbered box (`01`, `02`…) and the section title in Space Grotesk sit against this
hexagon-point, white on the dark variants / dark ink on the light-gray variant.

Colors: use `RGBColor` with the exact hex from §02 for fidelity. Yellow as the primary
data series, Grays for secondary, on dark backgrounds.

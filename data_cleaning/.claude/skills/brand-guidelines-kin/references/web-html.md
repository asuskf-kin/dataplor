# Web / HTML implementation

Read this when producing **HTML, web pages, or any browser-rendered artifact** — and
also **one-pagers and multi-page documents**, which are built as self-contained HTML
sized to the page (Letter/A4 portrait) and then exported **Print → Save as PDF**. All
paths are relative to the skill directory. Nothing here needs npm or a CDN — fonts
and logos are embedded directly so the output is fully self-contained.

> **One-pager / document → PDF → Drive.** Because everything is embedded (fonts as
> base64 @font-face, logo/hexagon as data-URI), the single HTML file renders identically
> offline, prints to a pixel-faithful PDF, and can be uploaded to Google Drive / opened
> in Docs. Set the page box with `@page { size: A4 portrait; margin: 0 }` (or `Letter`)
> and give each page a fixed pixel width so the print matches the screen. Follow the
> one-pager / document layout specs in §09 of SKILL.md.

## Fonts — embed as base64 @font-face

The fonts ship under `assets/fonts/` as variable woff2 (latin subset, covers
accented ES/PT glyphs). Read and base64-encode them — no network, no uploads:

```python
import base64, pathlib

def load_font(filename):
    data = pathlib.Path("assets/fonts") / filename
    return base64.b64encode(data.read_bytes()).decode()

space_grotesk = load_font("space-grotesk.woff2")
albert_sans   = load_font("albert-sans.woff2")
```

```css
@font-face {
  font-family: 'Space Grotesk';
  src: url('data:font/woff2;base64,{space_grotesk}') format('woff2');
  font-weight: 300 700;   /* variable — real weight axis, not synthesized */
  font-style: normal;
}
@font-face {
  font-family: 'Albert Sans';
  src: url('data:font/woff2;base64,{albert_sans}') format('woff2');
  font-weight: 100 900;   /* variable */
  font-style: normal;
}
/* Italic variant — only if body emphasis is needed. Load albert-sans-italic.ttf
   (ship a woff2 build of it the same way if you use it heavily). */
@font-face {
  font-family: 'Albert Sans';
  src: url('data:font/ttf;base64,{albert_sans_italic}') format('truetype');
  font-weight: 100 900;
  font-style: italic;
}

/* Usage */
h1, h2, h3, .label, .stat, .overline { font-family: 'Space Grotesk', sans-serif; }
body, p, .body-text { font-family: 'Albert Sans', sans-serif; font-weight: 400; }
```

> **License:** both fonts are SIL Open Font License 1.1; the license texts ship
> alongside them (`assets/fonts/OFL-SpaceGrotesk.txt`, `OFL-AlbertSans.txt`) and must
> travel with the woff2 files wherever this skill is copied.

> ⛔ **ADHERENCE #3 — the only fonts are Space Grotesk + Albert Sans, embedded from
> `assets/fonts/`.** Never fall back to Arial/Helvetica/system-ui, never link a Google
> Fonts/CDN URL, never `@import`. If the embed is skipped, the deliverable renders in a
> system font and is off-brand — embed every time, including one-pagers and documents.

Never use Google Fonts CDN or system fallbacks — always embed.

## Color CSS variables

```css
:root {
  --kin-yellow:  #E5FF01;
  --kin-black:   #141417;
  --kin-dark:    #222326;
  --kin-gray-3:  #999EA6;
  --kin-gray-2:  #D4D5D6;
  --kin-gray-1:  #EFEFEE;
  --kin-white:   #FFFFFF;
}
```

## Logos — embed as a data-URI (preferred)

> ⛔ **ADHERENCE #5 — never draw the logo.** The "Kin"/"Kin Analytics" wordmark is
> vector paths inside the approved SVG; you embed the *file*, never re-create it as live
> text in a font, hand-authored paths, or a CSS drawing. This is what produces wrong
> "Kin" letters. If no file fits the surface, leave the slot empty and say which file is
> missing.

> ⚠️ **Class collision — do not naively inline these SVGs.** Each file carries an
> internal `<style>` block using class names `.cls-1`/`.cls-2`. CSS inside inline SVG
> is **not** scoped — it leaks to the whole document. Paste two logos into one page
> and the last `.cls-1`/`.cls-2` rule wins, recolouring every logo. So **embed as a
> data-URI** (each `<img>` is fully isolated):

```python
import base64, pathlib

def logo_data_uri(rel_path):
    svg = pathlib.Path(rel_path).read_bytes()
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode()

img = f'<img src="{logo_data_uri("assets/logos/informal/Kin_Logo_IV_19.svg")}" alt="Kin" style="height:28px">'
```
```css
.logo-header { height: 28px; width: auto; display: block; }   /* header */
.logo-footer { height: 22px; }                                /* footer */
```

If you genuinely need the SVG inline (e.g. to animate or recolour paths via CSS),
first **rename the classes to something unique per logo** (`.kin-iv19-1`,
`.kin-iv19-2`, …) so they can't collide with another logo's styles.

### Favicon

```python
href = logo_data_uri("assets/logos/symbol/Kin_Logo_S_14.svg")  # yellow hex for dark UIs; S_13 for light
# <link rel="icon" href="{href}">
```

## Hexagon — place the file; clip-path is ONLY for masking a photo

> ⛔ **ADHERENCE #5.** A hexagon used as a **brand element** (accent, bullet, step
> marker, "vs" mark, divider point) is **placed from an approved file** — never drawn.
> Embed it exactly like a logo, as an isolated data-URI `<img>`:

```python
# Yellow hex accent (S_14 = yellow, S_13 = gray); recolor via the approved recolorable
# hexagon SVGs in assets/hexagons/patterns/ if you need a specific fill.
hex_img = f'<img src="{logo_data_uri("assets/logos/symbol/Kin_Logo_S_14.svg")}" alt="" style="height:20px">'
```

The **only** legitimate use of `clip-path`/polygon is to **mask a photo or content box**
into a hexagon silhouette (an image crop) — never to fabricate the brand mark itself:

```css
/* OK: cropping an <img> or a filled content cell into a hexagon silhouette. */
/* NOT OK: using this to stand in for the Kin hexagon brand mark — place the file. */
.hex-photo-mask {
  clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%);
}
```

If you catch yourself drawing a polygon/clip-path to *be* a yellow brand hexagon (e.g. a
section-divider point or a step bullet), STOP and place the file instead — that is the
bug that yields mis-shaped hexagons and stray yellow shapes.

## Motion — hexagon reveal animation

See §06b in SKILL.md for the 4-state concept (Cluster → Seed → Grow → Reveal) and the
motion principles. CSS reference for the signature reveal:

```css
/* Hex cluster reveal: state 1→4 */
.hex-dark {
  fill: #222326;
  animation: hex-fade-out 0.6s ease-out forwards;
}
.hex-yellow {
  fill: #E5FF01;
  transform-origin: center;
  animation: hex-scale-in 0.8s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
}
@keyframes hex-scale-in {
  from { transform: scale(0.1); opacity: 0; }
  to   { transform: scale(1.0); opacity: 1; }
}
@keyframes hex-fade-out {
  from { opacity: 1; }
  to   { opacity: 0.15; }
}
```

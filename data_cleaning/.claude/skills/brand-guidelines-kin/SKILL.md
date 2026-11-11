---
name: brand-guidelines-kin
description: "Applies Kin Analytics' official VISUAL identity — logos, brand colors, Space Grotesk + Albert Sans typography, the hexagon motif, photography treatment, and layout/grid — to any deliverable. Use whenever creating or restyling something that should look like Kin: slide decks (.pptx), Word docs (.docx), PDFs, HTML/web pages, dashboards, charts, social graphics, reports, one-pagers, or case studies — even if the user doesn't say \"brand\". Also trigger on \"make this on-brand\", \"fix the colors\", \"add the Kin logo\", \"is this on-brand?\", or any request involving Kin's colors, fonts, logo, or visual design standards. Covers visual identity only (not voice or copy tone)."
---

# Kin Analytics — Visual Brand Guidelines

> **Version** 1.13 · **Last updated** 2026-09-01 · **Owner** Kin Marketing — Brand
> (cristina.mosquera@kinanalytics.com) · **Status** Maintained · History in
> `CHANGELOG.md`.
>
> **Canonical spec = Kin Design System (Claude Design).** This skill is its **synced
> export** for agents/Code — the implementation of the brand's *visual identity*
> (colors, type, logos, icons, charts, layout). On any conflict, the **Kin Design
> System wins**; sync direction is **Design System → this skill**. Scope is visual
> identity only (not voice or copy). Tokens live in
> `assets/tokens/colors_and_type.css` (single source for color/type).

## FILE AUTHORITY — what is canon

Never derive brand facts (color, type, logo shapes) from anything outside Tier 1.

**Tier 1 — authoritative**
- `SKILL.md` — the binding rules (this file).
- `assets/tokens/colors_and_type.css` — token source of truth for color + type.
- Official art/assets: `assets/color/source/`, `assets/fonts/`, `assets/logos/`,
  `assets/icons/`, `assets/charts/`, `assets/hexagons/patterns/`.
- `references/*.md` — implementation code per output format.

**Tier 2 — generated (never hand-edit; regenerate)**
- `assets/quick-reference/Kin_Brand_Cheatsheet.html` and
  `assets/templates/Kin_Landing_Starter.html` are **outputs of their `build_*.py`**.
  Edit the script and re-run; don't hand-edit the HTML.

> Upstream canon is the **Kin Design System** (Claude Design); this skill is its synced
> export. Additional approved logo files live there (compact mark, "Leave it to Kin"
> lockup, solid-hex marks) — import them when syncing.

## ADHERENCE — hard rules (treat every violation as blocking)

1. **No hand-written colors.** No literal `#hex`/`rgb()`/`hsl()` — use a token via
   `var(--…)` from `colors_and_type.css`.
2. **No raw px.** Use spacing / radius / type tokens.
3. **No external fonts.** Only Space Grotesk + Albert Sans, served locally — never a
   webfont/CDN/`@import`.
4. **No internet imports.** Bundle every dependency; the system must work offline.
5. **Never draw, typeset, trace, or rebuild the logo or hexagon.** The logo is **only** ever placed by referencing an approved file in `assets/logos/` (and hexagon marks from `assets/hexagons/`). NEVER hand-author it as inline SVG paths/polygons, `clip-path`, canvas, live text in any font, an "approximation", or — in PPTX — `add_shape`/`MSO_SHAPE`/freeform built to look like it. Even if the geometry looks right, that is the bug that yields wrong "Kin" letters and mis-shaped hexagons. In every format (PPTX, PDF, HTML, docx) you place the *file*: HTML → `<img>` with a base64 data-URI (see `references/web-html.md`); PPTX → rasterize the SVG to PNG and `add_picture` (see `references/pptx.md`). The section divider's yellow accent is a **hexagon-point, never a plain rectangular stripe**. If no approved file fits the surface, **leave the logo slot empty and tell the user which file is missing** — a missing logo is acceptable; an invented one is never.

**Which logo file (quick map — full table in §10):**
- Footer wordmark, dark slide → `assets/logos/formal/Kin_Logo_FV_19.svg` (white + yellow hex)
- Footer wordmark, light/gray slide → `assets/logos/formal/Kin_Logo_FV_13.svg` (black + gray hex)
- Short "Kin" mark, dark → `assets/logos/informal/Kin_Logo_IV_19.svg`; light/gray → `Kin_Logo_IV_13.svg`
- Never use the all-gray `*_16` variant on a gray surface.

If a case has no token or local asset, **stop and tell the user what's missing** — do
not improvise a literal value or a remote import.

## Theming — light & dark are both first-class

Every color is a CSS variable on `:root` (light, default) and overridden on
`[data-theme="dark"]`. Switch by setting the attribute on `<html>` or any region:
`<section data-theme="dark"> … </section>`. Surface, text, border, and shadow tokens
flip together; **Kin Yellow is identical in both themes**.

## Overview

Kin Analytics is a data and AI intelligence company. Its visual identity is bold, clean, and modern — built on electric yellow, near-black, geometric precision, and the hexagon as a core motif. Everything Kin produces should feel sharp, confident, and data-forward.

**Sign-off** — the only approved brand sign-off is *"Leave it to Kin"*, used **only when
explicitly requested**, never automatically. The Design System recognizes no other display
line; do not add taglines the DS doesn't sanction.

> ⛔ **Never use "Let knowledge in"** (any spelling/casing/punctuation). It is **not**
> an approved Kin tagline — remove it on sight. (Per the Kin Design System canon.)

**Website**: KinAnalytics.com

### Self-contained — works in any project

This skill carries everything it needs; it assumes nothing about the host project:
- **Logos** — official SVGs under `assets/logos/` (see §10). Never recreated.
- **Fonts** — Space Grotesk + Albert Sans under `assets/fonts/`, as variable **TTF** (for PPTX/DOCX) **and** woff2 (for HTML/PDF), plus an Albert Sans italic TTF (see §03). No npm, no CDN.

All paths in this guide are **relative to the skill directory** — run code from here, or prefix
the paths accordingly.

### Where the code lives — `references/`

This file holds the **brand decisions** (what to use, when, and the rules). The
**implementation code** lives in `references/`, split by output format — read only the
one you need:

| Producing… | Read | Needs |
|------------|------|-------|
| HTML / web / artifacts | `references/web-html.md` | nothing (fully embedded) |
| **One-pager / solution brief** | `references/web-html.md` + §09 "One-Pager" | start from `assets/templates/Kin_OnePager_Starter.html` |
| **Document (multi-page)** | `references/web-html.md` + §09 "Document" | start from `assets/templates/Kin_Document_Starter.html` |
| **Landing page (responsive web)** | `references/web-html.md` + §09 "Landing pages" | start from `assets/templates/Kin_Landing_Starter.html` |
| **Social post — We're Hiring** | `references/web-html.md` + §09 "Social Media" | **duplicate & fill** `assets/templates/Kin_Social_Hiring_Starter.html` |
| **Social post — New Collaborator** | `references/web-html.md` + §09 "Social Media" | **duplicate & fill** `assets/templates/Kin_Social_NewCollaborator_Starter.html` (light/dark via `data-theme`) |
| **One-pager (HTML → PDF)** | `references/web-html.md` | nothing (embed fonts + logo, then Print → Save as PDF) |
| **Multi-page document (HTML → PDF)** | `references/web-html.md` | nothing (embed fonts + logo, then Print → Save as PDF) |
| PowerPoint `.pptx` | `references/pptx.md` + §09 | **duplicate & fill** `assets/templates/Kin_Presentation_Template.pptx` (never rebuild from scratch) |
| Case study / sales DOCX | `references/docx-case-study.md` | `docx` npm v9+ (+ `cairosvg`) |
| Photo prep / treatment | `references/photography.md` | PIL/Photoshop |

One-pager and document are built as **self-contained HTML** (fonts and logo embedded, per `web-html.md`) sized to the page (Letter/A4 portrait), then exported with **Print → Save as PDF**. The same HTML can be brought into Google Docs/Drive. Never hand-draw the logo or set a system font — see ADHERENCE #5 and #3.

These cover font embedding, logo placement, CSS variables, hexagon code, motion, and
the approved case-study template.

### Shareable one-pager (no Claude needed)

A print-ready visual brand cheat-sheet for the whole org lives at
`assets/quick-reference/Kin_Brand_Cheatsheet.html` — self-contained (fonts, logo, and
icons embedded), open in any browser and **Print → Save as PDF** to hand out. It
regenerates from the bundled assets with
`python assets/quick-reference/build_cheatsheet.py`, so re-run it after any brand
change to keep it in sync.

### Starter templates

`assets/templates/` holds ready-to-use, self-contained starting points (fonts, logo,
and icons embedded — no build step):
- `Kin_Presentation_Template.pptx` — the **canonical 20-slide Kin deck** (dark/light
  covers, section dividers, the light↔dark system, Space Grotesk + Albert Sans **embedded
  in the file**). **Every `.pptx` deck starts here** — duplicate and fill its slides; never
  rebuild a deck from scratch (see §09 "The canonical Kin Presentation template").
- `Kin_OnePager_Starter.html` — a **self-contained** single-page solution brief (dark
  hero with eyebrow + Yellow-accent title, stat strip, "how it works" hexagon cards,
  "Leave it to Kin." sign-off footer). Fonts base64-embedded, logo/hexagon placed from
  file, **no CDN, no React** — opens anywhere and exports cleanly via Print→Save as PDF.
- `Kin_Document_Starter.html` — a **self-contained** multi-page document (photo cover with
  metadata row, content pages with eyebrow + callouts + hexagon bullets + two-column
  layout, running footer with logo and page number). Same embedding rules. Duplicate the
  content-page block for more pages.
- `Kin_Landing_Starter.html` — a responsive on-brand landing page (sticky header,
  hero with a single hexagon accent, KPI stats band, icon feature cards, CTA, footer). Use it
  as scaffolding: swap copy/sections, keep the palette, type, and logo as-is.
- Regenerate/extend the landing page with `python assets/templates/build_landing.py`.
- `Kin_Social_Hiring_Starter.html` — a **self-contained** 4:5 (1080×1350)
  "We're Hiring" post (gray canvas, top-right hexagon lockup, black role band with Yellow
  Space Grotesk, Yellow label chips, black "WHAT WE OFFER" hexagon block). Editable
  placeholder copy — swap the role, modality, and list items.
- `Kin_Social_NewCollaborator_Starter.html` — a **self-contained**
  4:5 new-hire announcement with a large identity hexagon (flag, name, role chip, team line)
  and an overlapping portrait hexagon. Ships **Light** (default) and **Dark** via the
  `data-theme` attribute on `<html>` — the panel, chip, URL, and Kin logo variant all flip
  together. Replace the portrait and flag placeholders and the identity copy.

---

## 01 — Logo

### Logo Versions

Kin has three logo types — choose the right one for context:

| Type | When to use |
|------|-------------|
| **Formal** — "Kin Analytics" full wordmark | Formal applications, first impressions, new audiences |
| **Informal** — "Kin" shortened wordmark | More casual applications, audiences who already recognize the brand |
| **Symbol** — Hexagon mark only | Icon-sized contexts, app icons, favicon, standalone brand mark |

> **The logo is a fixed asset — never recreated.** The official artwork ships with this skill as transparent SVGs under `assets/logos/`. See **§10 — Logo Files** for the full file-to-context map. NEVER draw or typeset the logo yourself ("Kin" in a font + a hexagon is *not* the brand mark) — use only the bundled files.

The bundled files are the **horizontal** orientation of each type. Tagline lockups and vertical lockups are not included — request the official file if a design needs one.

### Clear Space

Always maintain a minimum clear space around the logo equal to **the width of the hexagon symbol** in the logo. This is the non-negotiable minimum — use more whenever possible. No other elements (text, images, graphics) may enter this zone.

### Logo Position

The logo can be placed in **any of the four corners** of a graphic piece, respecting the established margins. There is also an alternative centered placement: the logo sits on a horizontal axis at the **midpoint of the height** of the piece — use this for more visual or special applications.

### Color Usage Rules

Only use these approved color combinations — creating new ones not in this guide is prohibited:

| Background | Logo color | Use case |
|------------|-----------|----------|
| Black `#141417` | White wordmark + Yellow hex | ✅ Preferred dark background |
| Dark `#222326` | White wordmark + Yellow hex | Dark slides, print |
| Yellow `#E5FF01` | Black wordmark + Black hex | Yellow slides, print |
| White / Light | Dark wordmark + Gray hex | ✅ Preferred light background |
| **Gray** (`#D4D5D6` Gray 2 / `#EFEFEE` Gray 1) | **Dark wordmark + Gray hex — same logo as white** | ✅ **Rule:** on gray surfaces use the light-background (dark-wordmark) logo, **never the all-gray muted variant** — it lacks contrast on gray |
| Any dark surface | Transparent bg, light wordmark + Yellow hex | Overlay on dark |
| Any light surface | Transparent bg, dark wordmark + Gray hex | Overlay on light |

### Logo Don'ts

Never do any of the following:
1. **Don't condense** the logotype (squish horizontally)
2. **Don't expand** the logotype (stretch horizontally)
3. **Don't rotate** the logotype
4. **Don't alter element order** within the logotype
5. **Don't use an outline** stroke on the logotype
6. **Don't apply unauthorized colors** — only those specified above
7. **Don't place on low-contrast backgrounds** where the logo blends in
8. **Don't use images that damage legibility** behind the logo
9. **Don't place over complex images** — the logo must be clearly readable

---

## 02 — Color Palette

### Full Palette

| Name | Hex | RGB | CMYK | Pantone |
|------|-----|-----|------|---------|
| White | `#FFFFFF` | 255-255-255 | 0-0-0-0 | White |
| Gray 1 | `#EFEFEE` | 239-239-238 | 0-0-0-5 | Cool Gray 1 |
| Gray 2 | `#D4D5D6` | 212-213-214 | 1-0-0-20 | 427 |
| Gray 3 | `#999EA6` | 153-158-166 | 5-0-0-45 | 429 |
| Gray 4 | `#222326` | 34-35-38 | 5-5-0-93 | 432 |
| Black | `#141417` | 20-20-23 | 0-0-0-96 | Black 6 |
| Kin Yellow | `#E5FF01` | 229-255-1 | 15-0-100-0 | 394 |

> ⚠️ **Print caution**: Kin Yellow (`#E5FF01`) may have consistency issues when printing in CMYK. Always proof before production.

### Surface tokens — presentation gray (`--ka-color-bg-gray2`)

Beyond the recessed layout gray (`--ka-color-bg-layout` = `#F2F2F2`, behind cards), the
Design System defines a **presentation-surface gray** one step darker:

| Token | Light value | Dark value | Role |
|-------|-------------|------------|------|
| `--ka-color-bg-gray2` | `#D4D5D6` (Gray 2) | `#222326` (Gray 4) | **Cover backgrounds and "light" section dividers** (the C — Light gray variant). |

Cover and light-divider variants use **`--ka-color-bg-gray2`**, never a hard-coded
`#D4D5D6`. It flips to Gray 4 in dark theme automatically. Yellow is never a background
on this or any surface.

### Color Role & Proportion

Yellow is the accent — not the base. Use it **very sparingly — roughly 3% of any
layout** (per Kin Design System canon); **never a dominant surface**. The dark palette
(Black + Grays) carries the weight:
- **Dominant**: Black `#141417` and Gray 4 `#222326` — backgrounds, large surfaces
- **Supporting**: Grays 1–3 — text hierarchy, borders, secondary surfaces
- **Accent (~3%)**: Kin Yellow `#E5FF01` — primary CTA, a key highlight, the hexagon mark

### Color Pairing Rules

- **Dark theme**: `#141417` background + White text + Yellow accents
- **Yellow theme**: `#E5FF01` background + Black text/elements
- **Light theme**: White background + Black text + Gray 3 for secondary
- **Never** combine Yellow background with white text (insufficient contrast)
- Not all palette colors can sit on top of each other — always check legibility. When in doubt, use maximum contrast pairings.

### Yellow Text Rule — Critical

**Never use Kin Yellow (`#E5FF01`) as a text color on white or light backgrounds.** Yellow on white is nearly invisible and fails contrast accessibility standards entirely.

| Surface | Yellow text allowed? | Use instead |
|---------|----------------------|-------------|
| Dark (`#141417`, `#222326`) | ✅ Yes — high contrast, on-brand | — |
| Yellow (`#E5FF01`) background | ❌ No | Black `#141417` text |
| White / Gray 1 (`#EFEFEE`) | ❌ No | Gray 4 `#222326` for labels/overlines |

This applies to **all text elements** on light surfaces: section labels, overlines, eyebrow text, captions, UI labels — even small decorative text. Yellow on light backgrounds looks broken, not branded.

**Correct pattern for section labels on white:**
- Use `#222326` (Gray 4) for the text
- Bring in the brand color through a yellow graphic element nearby — a bottom border rule, a left accent bar, a small filled shape — rather than coloring the text itself

---

## 03 — Typography

### Typefaces

| Role | Font | Weights available |
|------|------|-------------------|
| **Display, titles, headings, numerals, stats** | **Space Grotesk** | Light, Regular, Medium, Bold (4 weights) |
| **Body, paragraphs, UI labels, descriptive copy** | **Albert Sans** | Thin, ExtraLight, Light, Regular, Medium, SemiBold, Bold, ExtraBold, Black (9 weights) |

Roles (matching the design-system canon): **Space Grotesk** → display / titles / numerals; **Albert Sans** → body / paragraphs / UI labels. Numerals and stats are always Space Grotesk (tabular for graphs).

Space Grotesk adds personality and identity. Albert Sans provides readability for longer text. Never use Arial, system fonts, or Google Fonts CDN — always embed these fonts.

### Typeface Usage by Level

| Text level | Font | Weight |
|------------|------|--------|
| Display / hero text | Space Grotesk | Bold (700), tight letter-spacing |
| Main headings | Space Grotesk | Medium–Bold (500–700) |
| Sub-headings | Space Grotesk | Regular–Medium (400–500) |
| Body paragraphs | Albert Sans | Regular (400), line-height ~1.6 |
| UI labels, nav | Albert Sans | Medium–SemiBold (500–600) |
| Subscribe / CTA text | Albert Sans | SemiBold (600) |
| Captions | Albert Sans | Regular–Light (300–400) |
| Overlines / eyebrow text | *(font not fixed by the design system — either family)* | All-caps, tracked-out, SemiBold weight, Gray 3 or Yellow |
| **`kinanalytics.com` (header & footer)** | **Albert Sans** | **Medium (500) — always, no exceptions** |

> **Eyebrows/overlines**: the design system fixes only their treatment — UPPERCASE, tracked-out, Gray 3 or Yellow — and does **not** mandate a typeface, so either family is on-brand. Keep it consistent within a single deliverable.

> **`kinanalytics.com` rule**: Wherever the website URL appears — header, footer, or any document — it must always be set in **Albert Sans Medium (weight 500)**, Gray 3 (`#999EA6`). Never use Space Grotesk for this element.
>
> ```css
> .site {
>   font-family: 'Albert Sans', sans-serif;
>   font-weight: 500;
>   font-size: 12px;
>   color: #999EA6; /* Gray 3 */
>   letter-spacing: 0.02em;
> }
> ```

### Fonts — files & licensing

The fonts ship **with this skill** under `assets/fonts/` in **both formats**, from the
same official Design System master — no npm, no network:

| File | Format | Use for |
|------|--------|---------|
| `space-grotesk.ttf` · `albert-sans.ttf` · `albert-sans-italic.ttf` | **variable TTF** | **PPTX / DOCX** (python-pptx, `docx` npm) — the canonical Design System format |
| `space-grotesk.woff2` · `albert-sans.woff2` | **variable woff2** | **HTML → PDF** (base64 `@font-face`) — regenerated from the same TTF master |

> **Why both.** The Design System's canonical font format is **variable TTF**. woff2 is
> kept only because it base64-embeds smaller for HTML/PDF; it is generated *from* the
> official TTF so the two never drift. **Office (PPTX/DOCX) cannot consume woff2 — always
> use the `.ttf` for those**, instancing a static weight if the tool can't read variable
> fonts (see `references/pptx.md`).

Both are SIL Open Font License 1.1; their license texts (`assets/fonts/OFL-SpaceGrotesk.txt`,
`OFL-AlbertSans.txt`) **must travel with the font files** wherever this skill is copied.
The Kin logos in `assets/logos/` are proprietary — internal use only; do not publish them
outside Kin.

The weight ranges above are real — both families are **variable fonts**, so any weight in
range renders natively (not synthesized): **Space Grotesk** `wght` 300–700 (internal family
name is "Space Grotesk Light" — default axis is 300; set the weight explicitly), **Albert
Sans** `wght` 100–900, plus a matching **italic** TTF for Albert Sans.

> **Embedding code** → web base64 `@font-face` in `references/web-html.md`; PPTX/DOCX
> `.ttf` usage in `references/pptx.md` and `references/docx-case-study.md`.

---

## 04 — Photography Style

All photography in Kin materials uses a **gradient map treatment** — not a simple grayscale. This specific technique unifies the visual system with Kin's color palette.

### The Treatment: Gradient Map (Duotone)

Every photo receives a **Photoshop Gradient Map adjustment layer** that remaps image luminosity to two specific Kin colors:

| Gradient Stop | Color | Hex | Applies to |
|---------------|-------|-----|------------|
| Shadows (dark tones) | Gray 4 | `#222326` | Blacks and deep shadows |
| Highlights (light tones) | Warm Light Gray | `#D8D8D5` | Whites and bright areas |

The result is a sophisticated desaturated duotone — darker than pure grayscale, with a warm-neutral cast in the lights. This is consistent across **all** branded photography (15 files confirmed with identical recipe).

> **Recipe + code** — the Photoshop Gradient Map steps and a Python/PIL
> implementation live in `references/photography.md`.

### Photography Don'ts

- ❌ Never use full-color photography without treatment in branded materials
- ❌ Do not use pure grayscale (it lacks Kin's warm-dark tonality)
- ❌ Do not apply Yellow tinting to photos — Yellow is reserved for graphic/UI elements
- ❌ Avoid stock-photo-feeling, overly cheerful, or brightly lit imagery

### Photography Tone & Subject

Professional, data-forward, confident. Categories used in brand library: **Finance** (financial professionals, workspaces) and **Enterprise** (offices, collaboration, technology). Dark, moody, and high-contrast treatments suit the brand best.

---

## 05 — Hexagons

The hexagon is the most important formal element of the graphic system — it's both the logo mark and the primary decorative motif.

### Orientation

Hexagons are always **"vertical" / pointy-top** orientation — pointed ends aligned vertically (top and bottom points). Never use flat-top orientation.

In code, build hexagons pointy-top (points at top and bottom). SVG point-math and a
CSS `clip-path` snippet are in `references/web-html.md`.

### Restraint (canonical)

The hexagon is brand equity, not a filler shape. Use it **sparingly — one or two per
composition, as an accent**. Two touching hexagons can evoke the honeycomb, but
**never** a background tessellation, repeating honeycomb wallpaper, or any repeating
decorative pattern behind content. Only its regular **point-up** proportion — never
stretch, squash, skew, rotate, or change its aspect ratio.

### Usage Modes

Use one hexagon (occasionally two) as:
1. **Text container** — short copy inside a solid hexagon
2. **Image container / mask** — a photo clipped into a hexagon
3. **Accent mark** — a single hexagon as a brand accent

Prefer an **approved hexagon file** over hand-authoring; if none fits, a plain
rounded-rectangle block is the on-brand fallback.

### Hexagon Files (reusable assets)

Recolorable hexagon SVGs ship under `assets/hexagons/patterns/`: `hex-solid`,
`hex-outline`, `hex-frame` (badge ring), and the small accent pair
`hex-cluster` / `hex-cluster-accent` (center hex yellow). Single-color shapes use
`currentColor`. Editable `.ai` masters → `source/`; examples → `reference/`. Full map
→ `assets/hexagons/README.md`.

> ⚠️ Per canon, hexagons are an **accent (1–2 max), never a background pattern** — so
> there is intentionally **no wallpaper/tile asset**. For a photo inside a hexagon use
> a CSS `clip-path` (see `references/web-html.md`).

---

## 06 — Icon Style

Icons follow a **geometric line style** confirmed across two weights and all five Kin background colors.

### Style Rules

- **Outline/line-based only** — never filled or solid
- **Geometric and structural** — clean, angular, precise; minimal rounded corners only where functionally necessary
- **Consistent stroke weight** — uniform throughout each icon and across the set
- **Two weights available**: Bold (default for UI/headers) and Regular (for body-size contexts)
- Match the geometric language of the hexagon motif — structured, not organic

### Icon Color Usage

Icons adapt to all five Kin backgrounds — use the appropriate color for contrast:

| Background | Icon Color |
|------------|------------|
| Black `#141417` | White `#FFFFFF` |
| Gray 4 `#222326` | White `#FFFFFF` |
| Gray 2 `#D4D5D6` | Black `#141417` |
| White/Light `#EFEFEE` | Black `#141417` |
| Yellow `#E5FF01` | Black `#141417` |

### Icon Categories (confirmed in brand library)

Finance & Enterprise focused: folder, documents/copy, email/envelope, cloud upload, arrow, search, data grid/table, line chart, institution/bank. Expand from this vocabulary — do not introduce decorative or illustrative icons.

### Icon Don'ts

- ❌ No filled/solid icons — always outline style
- ❌ No mixed stroke weights within a single composition
- ❌ No colored icons (only white or black — never Yellow or Gray tones on icons)
- ❌ No decorative or illustrative icon styles (e.g. isometric, 3D, gradient fills)

### Icon Files (official assets — prefer these over redrawing)

The icon set ships under `assets/icons/` — **9 icons** (`folder`, `documents`,
`email`, `cloud-upload`, `arrow`, `search`, `data-grid`, `line-chart`, `bank`) in two
weights (`bold/`, `regular/`), named `icon-<name>-<weight>.svg`. **When a file exists
for what you need, use it** rather than drawing one from scratch. They're monochrome
and stroke-based (`stroke="currentColor"`), so one file recolors white or black per the
table above — never bake in yellow/gray.

The master artwork is `assets/icons/source/Kin_Icons.ai` and the full spec sheet is
`assets/icons/reference/Kin_Icons.pdf`; the bundled SVGs are traced to match them.

Full file map + embedding code → `assets/icons/README.md` (data-URI for web →
`references/web-html.md`; cairosvg rasterise for PPTX/DOCX → `references/pptx.md`).

---

## 06b — Motion & Animation

From the Kin Motion Proposal (Visual Guidelines 2024), the animation language mirrors the brand's visual system — hexagons reveal through **scale and opacity**, using Yellow as the focal reveal moment.

### Hexagon Reveal — Core Animation Sequence

The signature Kin motion pattern is a **4-state hexagon cluster reveal**:

| State | Description |
|-------|-------------|
| **1 — Cluster** | Group of dark hexagons (`#222326`) arranged in honeycomb cluster — no yellow, all dark |
| **2 — Seed** | A small Yellow hexagon (`#E5FF01`) appears at center of cluster — small scale, surrounded by dark hexes |
| **3 — Grow** | Yellow hexagon scales up, filling the center zone — dark hexagons recede or become outline/transparent |
| **4 — Reveal** | Full-size Yellow hexagon stands alone — dark cluster fades or exits |

### Motion Principles

- **Yellow is the reveal** — it always enters last and grows to become the focal point
- **Dark to light** — motion travels from dense dark mass → single Yellow accent
- **Scale-based** — primary animation tool is scale (not position drift or rotation)
- **Opacity fades** — dark hexagons dissolve as Yellow expands; use opacity not wipe/slide
- **No spin or rotation** — hexagons stay in pointy-top orientation throughout motion
- **Easing**: ease-in-out for scale; linear or ease-out for opacity fade of darks

> **CSS / SVG animation code** for the hexagon reveal → `references/web-html.md`.

---

## 07 — Layout & Grid System

The minimum unit of measurement for all layouts is **the width of the hexagon symbol** in the logo. Margins are defined as multiples of this unit.

### Grid by Format

| Format | Ratio | Columns | Rows | Use case |
|--------|-------|---------|------|----------|
| Square | 1:1 | 3 main (subdivided) | 3 main (subdivided) | Social media posts |
| Vertical | 3:4 | 6 columns | 8 rows | Portrait layouts, stories |
| Horizontal | 16:9 | 10 columns | 6 rows | Presentations, widescreen |

### Logo Placement in Layouts

- Place logo in **any corner** of the piece, respecting margins
- Alternative: centered on a **horizontal axis at the vertical midpoint** of the piece (for feature/hero layouts)
- When using the symbol-only logo, give it **twice the width** of the symbol as shown in the full logo

### Composition Principles

- Respect established margins — no elements bleed into the margin zone
- Use a single hexagon (or two) as an accent to anchor a composition — not as a repeating pattern
- Alternate background colors across a content series (e.g., social feed) for visual balance
- Keep layouts clean with strong whitespace — don't crowd content

---

## 08 — Design Principles

1. **Bold simplicity** — generous whitespace, strong typographic hierarchy
2. **Electric contrast** — Yellow pops against dark; use it purposefully, not as a fill
3. **Geometric precision** — hexagons, clean edges, no rounded organic shapes
4. **Monochromatic base** — the grayscale palette carries the weight; Yellow punctuates
5. **No gradients** — flat color only throughout the graphic system
6. **Consistent photographic treatment** — grayscale filter on all photography
7. **Hexagon as accent** — 1–2 per composition, point-up; never a background pattern or honeycomb wallpaper
8. **Rounded corners** — content boxes and cards use a **12px** radius (the soft card scale); full-pill (`999px`) only for small status pills/toggles. Never 0px, never fully circular, never only some corners
9. **Token-driven** — pull color, type, spacing, and radius from the design tokens (`assets/tokens/colors_and_type.css`). Per Kin Design System adherence: **no hard-coded raw hex or px**, and **no external fonts/CDNs** — use `var(--…)` and local fonts. If a value has no token, stop and flag it rather than inventing one

---

## 09 — Application by Format

### Presentations (PPTX / 16:9)

Decks deliberately alternate light and dark surfaces so they don't read as one flat mode. All colors come from **tokens** (per ADHERENCE) — never hard-coded. Dark surfaces (`#141417`) carry covers, section dividers, and brand moments; light surfaces carry dense content, data, and body copy.

**Built for Google Slides.** Kin decks are generated and exported optimized for **Google Slides / Drive**: a responsive 16:9 layout where nothing bleeds past the frame — every element stays inside the slide bounds, content centers vertically, and text containers use auto height + generous padding so a font substitution on import never overflows. When creating a deck, **state up front that it is for Google Slides** so it is built to that format from the start.

**Vertical rhythm (every content slide).** The section title sits **high** in the content area — near the top, with a little air above it, not centered or sunk. The body/content follows **below, in the middle zone**, at a comfortable reading size. This title-high / body-mid hierarchy holds on every content slide (each section is a flex column anchored to the top with generous padding) so slides read consistently. Eyebrow labels have real presence (smaller than the title, not a tiny caption); body copy is never cramped; every box carries generous inner padding so text never touches an edge, and boxes use auto height so a longer line grows the box instead of overflowing.

**Blocks stay whole on export (PDF / PPTX).** Any run of text that visually belongs to one box — eyebrow + title + subtitle, or title + subtitle + metadata — is built as **one single container** with the texts stacked inside as child content in the same vertical flow. **Never** as separate boxes placed near each other: on screen they look joined, but on export they split and drift. The single container uses auto height, generous inner padding, and **no absolute positions or fixed coordinates on the inner texts** — so it exports as one intact block. Applies to every content box in every template.

- **Cover slide** (one per deck): hero headline in Space Grotesk Bold, Yellow accent. Carries the confidentiality mark (`Kin Analytics© <year>` + `CONFIDENTIAL`) bottom-right — **cover only, never repeated**. Never carries the content footer. Three background variants (below).
- **Section dividers**: photo + a **Yellow hexagon-point (chevron)** — the pointed tip of a hexagon entering the slide, as in reference slide 03, **not a plain rectangular yellow stripe/band** — with a numbered box (`01`, `02`…) and section title in Space Grotesk. Build it from an approved hexagon file (or a regular 6-sided polygon at original proportion), never a flat rectangle. Three background variants (below); alternate them between dividers. Each divider carries the **all-black Kin logo bottom-right on the yellow panel** — placed from file, a brand mark, not the footer. **No content footer and no confidentiality mark.**
- **Content slides**: Yellow for key data callouts; Albert Sans for body copy. Two-element footer only (see below).
- **Data/chart slides**: Yellow as primary series, Grays for secondary.
- **Team slides**: Photo in hexagon crop with Gray filter; name in Space Grotesk, role in Albert Sans.
- **Timeline/project slides**: Yellow for active/current state; Gray for past/future.
- **Closing slide**: handles its own sign-off; **never carries the content footer**. Use "Leave it to Kin." here only if explicitly requested (per the sign-off rule).

Grid: 10 columns × 6 rows. Content boxes/cards: **12px** rounded corners. Text containers use auto/`min-height` + generous padding — never a fixed `height` (font substitution on export must not overflow).

#### Cover & section-divider background variants

Both the cover and each section divider pick one of the same three backgrounds (via the `Cover background` / `Section heading background` tweak). Yellow is **never** a background.

- **A — Dark photo**: duotone architectural photo full-bleed; title box `#141417`; white/yellow text.
- **B — Solid dark**: solid `#141417`, no photo; elevated/shadowed title box; white/yellow text.
- **C — Light gray**: `--ka-color-bg-gray2` field (Gray 2) with a dark title card so the yellow title stays readable; use the light-background logo (dark wordmark) on the gray field — never the all-gray `*_16` variant.

**Title-box integrity (all covers — presentation and document).** Everything in the title box — eyebrow, title, subtitle, and the `CLIENT / PARTNER / ENGAGEMENT` metadata row — is **one container with the elements stacked inside, in normal flow**. The metadata row is never a separately-positioned element with its own coordinates; it is always a child of the box, directly below the subtitle. The box uses **auto height and generous bottom padding**, so if the font is substituted on PDF export the block grows instead of the metadata detaching and drifting out of the box.

#### Content-slide footers

Every content slide carries a two-element footer and nothing else:
- **Bottom-left**: the formal "Kin Analytics" wordmark **placed from file** — `assets/logos/formal/Kin_Logo_FV_13.svg` on light/gray surfaces, `assets/logos/formal/Kin_Logo_FV_19.svg` on dark surfaces (rasterize to PNG for PPTX). The full lockup, never the hexagon alone, never the short "Kin" wordmark, never hand-typed or hand-drawn text.
- **Bottom-right**: the URL `kinanalytics.com`, always lowercase.

No tagline or sign-off in the footer. Both elements balanced in size, and they sit **close to the bottom corners** (a tight side margin) — the logo hugging the bottom-left and the URL the bottom-right, not pulled toward the centre. The cover, closing slide, and section dividers never carry this footer.

#### The canonical "Kin Presentation" template — START HERE, DO NOT REBUILD

> ⛔ **Hard rule (presentations).** Every Kin `.pptx` deck **starts from the bundled
> template** `assets/templates/Kin_Presentation_Template.pptx` — a real, editable 20-slide
> PowerPoint that IS the Design System deck (dark/light covers, section dividers, the
> light↔dark system, Space Grotesk + Albert Sans **embedded inside the file**). You
> **duplicate and fill** its slides; you do **not** regenerate slides from scratch with
> `python-pptx`/`pptxgenjs` to "look like" it. Building from zero is the bug that lost the
> fonts, the photo covers, and the light/dark switch. If a needed layout genuinely isn't in
> the template, duplicate the closest slide and adapt it — never invent a parallel styling.

**Why the template, not a rebuild:** the fonts, cover photos, hexagon art, and the
per-slide dark/light backgrounds live *inside* this .pptx as real slide masters and media.
Rebuilding reproduces none of that reliably. The template also ships with **Space Grotesk
and Albert Sans embedded** (regular + bold), so a filled deck keeps Kin's type even on a
machine that doesn't have the fonts installed — which is the root cause of substituted
(Arial-looking) text in earlier decks.

**Workflow (see `references/pptx.md` for the commands):**
1. Copy `assets/templates/Kin_Presentation_Template.pptx` to your working file.
2. `thumbnail.py` it, map each section of your content onto the closest of the 20 layouts
   below, and pick your covers (dark photo / solid dark / light gray).
3. Duplicate the slides you need with `add_slide.py`, delete the rest, then fill text by
   assigning `run.text` (never `text_frame.text`, which strips the styling — see pptx.md).
4. Keep the embedded fonts and the light/dark backgrounds intact; don't flatten a slide to
   a single background color.
5. QA: render to images and confirm Space Grotesk/Albert Sans actually rendered (not a
   fallback), covers are the photo/gray variants, and no layout art drifted.

The 20 rendered layouts also exist as PNGs in `assets/templates/reference-designs/` — use
those only to *preview* which slide to pick; the `.pptx` is what you actually edit.

| # | Layout | When to use |
|---|--------|-------------|
| 01 | **Cover** — dark photo, eyebrow, Yellow title in dark card, client/partner/engagement meta row | Opening |
| 02 | **Agenda — timeline** — numbered markers (01.–05.) with Yellow-highlighted titles on dark photo, white footer band | Table of contents |
| 03 | **Section divider** — dark photo + Yellow **hexagon-point (chevron, not a stripe)**, big index, white heading + Yellow-highlighted line | Between sections |
| 04 | **Values row** — five staggered hexagons (dark / Yellow / gray / dark / white), light gray field | 3–5 value words |
| 05 | **Process cards** — eyebrow, dark heading, 3 dark rounded cards with Yellow text | Steps / items |
| 06 | **Point detail** — eyebrow, dark heading, bulleted lead phrase, one dark callout with Yellow text | Single point + emphasis |
| 07 | **Comparison** — split light "Option A" vs dark "Option B", Yellow hexagon "vs" divider | A/B comparison |
| 08 | **Three points (light)** — lead-in statement, three bordered cards 01/02/03 + Yellow tick | 3 parallel points |
| 09 | **Results / dashboard** — two Yellow-bar stat callouts + two dark chart cards (bar + donut) | Metrics / impact |
| 10 | **Key takeaway (Yellow)** — full-bleed Yellow, dark eyebrow, big dark statement | Single anchoring statement |
| 11 | **The problem (dark)** — full dark, Yellow eyebrow, white headline with one Yellow-highlighted word | Problem statement |
| 12 | **By the numbers (dark)** — huge stat headline (part Yellow), supporting paragraph | Hero metric |
| 13 | **Quote (light)** — Yellow quote-mark block, big dark quote, attribution | Testimonial |
| 14 | **How it works** — eyebrow, heading, 3 numbered hexagon steps with connector lines | 3-step process |
| 15 | **Roadmap (dark)** — Now / Next / Later / Vision on a hexagon-node timeline; Yellow = current | Roadmap / phases |
| 16 | **Light & dark demo** — two side-by-side cards, same content in both themes | System / theming |
| 17 | **Team** — heading + 4 cards with hexagon-cropped gray photos, name + role | Team intro |
| 18 | **Integrations** — heading, supporting line, 4 light cards each with a line icon | Integrations |
| 19 | **Security & trust (dark)** — Yellow eyebrow, white heading, 2×2 grid with Yellow hexagon bullets | Trust / compliance |
| 20 | **Closing** — dark photo, "Leave it to Kin" lockup, social handles row with Yellow circle icons | Final slide |

**Cover variations** (`reference-designs/cover-variants-1.png`) — visual comparison of the three cover backgrounds above; title card, Yellow title, and meta row stay identical across them.

**Agenda variations** (`reference-designs/agenda-variants-1.png`) — same content (01–05 + Q&A), two forms: **A — Timeline** (numbered markers on dark photo, matches slide 02) and **B — Numbered list** (light slide, "What we'll cover", numbered rows with a Yellow tick).

### One-Pager / Solution Brief (single portrait page)

> **Start from `assets/templates/Kin_OnePager_Starter.html`** — a self-contained on-brand
> one-pager (fonts base64-embedded, logo/hexagon from file, no CDN). Duplicate it and swap
> the copy; keep the palette, type, logo, and the "Leave it to Kin." sign-off. Build from
> scratch only if the need genuinely doesn't fit the pattern below. Export via Print→Save
> as PDF.

A reproducible single portrait page (Letter/A4, fixed pixel width) for proof-of-value briefs, engagement summaries, and leave-behinds. A rendered specimen lives at `assets/templates/reference-designs/onepager-reference-1.png` — **view it before building**. This documents the *layout pattern*, not the specimen's content. Top to bottom:

1. **Header** — the short "Kin" logo (with hexagon) from file, top-left; `KINANALYTICS.COM` uppercase/tracked, top-right. Below them a **full-width black band** (`#141417`, 12px rounded) with a Yellow tracked eyebrow, a large white Space Grotesk title, and a gray subtitle/category.
2. **Opening block** — Left: a large dark Space Grotesk headline. **Always highlight the final word/phrase** with a Yellow background — never a middle word, only the close. This end-highlight is a mandatory signature of the format. Right: two Albert Sans paragraphs.
3. **Journey row** — five numbered steps `01–05`, each number **preceded by a hexagon from file. All journey-step hexagons are Yellow (`#E5FF01`)** — they are *not* alternated black/yellow; every step hexagon is yellow, no exception. (The two-column detail headings below keep their own yellow/black hexagon pairing — the all-yellow rule is only for the journey row.) Each step has a title + short description. Thin divider rule above the row with a label at each end.
4. **Impact banner** — a full-width black band (`#141417`, 12px) with large Yellow stats, each **preceded by a Yellow hexagon** (e.g. `+30%`, `−20%`), gray labels above, plus a "what good looks like" block with a Yellow subtitle. State results as evidence, never a promise.
5. **Two detail columns** — each header **preceded by a hexagon** (one Yellow, one black), introducing a numbered list `01–04` with a bold title + gray description.
6. **Three-data row** — three columns: gray uppercase label, large value, short description; the last value may carry the Yellow highlight.
7. **Footer** — **only** "Leave it to Kin." bottom-right, preceded by a Yellow hexagon — no logo, no URL. This sign-off is **one-pager only**; it never appears in the presentation footer.

Type: Space Grotesk for titles/numbers/values, Albert Sans for running copy. Colors from tokens; `#E5FF01` only as accent/highlight/banner fill, never the page background; logo + hexagons only from file (original proportion, never deformed); 12px corners; nothing from the internet.

**Band theme — dark (default) or light** (selectable via the `Band theme` tweak):
- **Dark**: title band and impact banner stay black (`#141417`) with white/gray text.
- **Light is a hybrid, not all-gray**: the **title band/header at the top stays black (`#141417`)** in both variants; only the *other* blocks switch to system grays — the impact banner to `#F2F2F2`, content boxes to grays — with text flipped to dark ink (`#141417`) and gray for contrast.
Everything else is identical across both variants: structure, Space Grotesk/Albert Sans type, the `#E5FF01` accent + stat numbers + end-highlight, the hexagons, and the "Leave it to Kin." sign-off. Yellow is never a full-page background in either variant.

> If a one-pager need doesn't fit this pattern (landscape, multi-page, a section type not listed), flag it and confirm before improvising.

### Multi-page Document (playbooks, frameworks, long-form briefs)

> **Start from `assets/templates/Kin_Document_Starter.html`** — a self-contained on-brand
> multi-page document (photo cover + metadata, content pages with callouts, hexagon
> bullets, two-column layout, running footer). Fonts base64-embedded, logo/cover from file,
> no CDN. Duplicate the content-page `<div class="page">` block for each new page and swap
> the copy. Export via Print→Save as PDF.

A reproducible multi-page document (Letter/A4 portrait, fixed pixel width). Documents the *layout pattern*, not any specimen's content. Three page types:

1. **Cover** — uses one of **two official cover images full-bleed** as the page background, selectable via the `Document cover` tweak. The images ship at `assets/templates/document-covers/` (`kin-document-cover-gris.jpg`, `kin-document-cover-black.jpg`; specimens also in `reference-designs/`):
   - **gris** — light page, dark centre hexagon.
   - **black** — dark page, light centre hexagon.
   The images are used **exactly as-is; the hexagons live in the image and are never redrawn or recreated.** Over the image, editable text sits **inside the centre hexagon**: a tracked eyebrow above a large Space Grotesk title with a subtitle below (one stacked container in normal flow — see "Title-box integrity" under Presentations). Title color is **Yellow (`#E5FF01`) on gris** and **dark ink on black** (the black variant's centre hexagon is light, so yellow wouldn't read). The **"Kin" logo from file** sits top-left; footer is `kinanalytics.com` lowercase bottom-left + page number (cover is page 1). **No sign-off on the cover.**
2. **Table of contents** — one index page styled after the presentation agenda: section list with page numbers and clear hierarchy; Space Grotesk entry titles, Albert Sans for the rest. Same header (logo top-right) and footer as content pages.
3. **Content pages** — the "Kin" logo from file top-right on every page. System hexagons as a very-low-opacity watermark, varying position page to page but always subtle. Space Grotesk bold headings, Albert Sans body. Footer every page: `kinanalytics.com` lowercase bottom-left + page number.

Colors from tokens; `#E5FF01` only as accent, never a page background; logo + hexagons only from file; nothing from the internet; example text is **editable placeholder**, never inherited copy.

> If a document need doesn't fit this pattern (landscape, a page type not listed), flag it and confirm before improvising.

### Social Media (1080×1350, 4:5)

> **Start from the starters — don't rebuild.** Two official 4:5 templates ship as
> self-contained HTML in `Kin_Social_Hiring_Starter.html` and
> `Kin_Social_NewCollaborator_Starter.html` (both in `assets/templates/`). Rendered specimens live at
> `assets/templates/reference-designs/social-*-reference-*.jpg` — **view them before
> building.** Duplicate the closest starter and fill it; never invent a parallel layout.

Social posts for Instagram / LinkedIn. Both templates share the **4:5 canvas
(1080×1350)**, the hexagon system from the official brand pack, and **editable
placeholder copy** the user replaces with the real information. Names are prefixed
**"Social Media — "** so the family reads as one section in the template picker. General
rules: short headline in **Space Grotesk**; `kinanalytics.com` lowercase where a URL
appears; `#E5FF01` as accent or panel fill, **never body text on a light field**; logo,
hexagons, and flag/portrait from file only (original proportion, never redrawn or
retyped); nothing loaded from the internet. Add the **"Leave it to Kin"** sign-off only if
explicitly requested — no other tagline.

**1 · We're Hiring** (`Kin_Social_Hiring_Starter.html`). Gray canvas (`--ka-color-bg-gray2`). Two hexagons
lock the top-right corner: a small one bleeding off the top edge and a Kin Yellow one
bleeding off the right edge with the **black "Kin" logo from file centred inside it**.
Header: a light "WE'RE HIRING" eyebrow over the role in a **black band with Yellow Space
Grotesk**, then the modality line (e.g. "100% REMOTE"). Body sections each carry a small
**Yellow label chip** — *What you'll do* / *What we're looking for* / *Nice to have* (the
last one right-aligned) — with dot bullets. Bottom-left, a **black hexagon block** holds
"WHAT WE / OFFER" (Yellow) beside a Yellow-arrow benefits list.

**2 · New Collaborator** (`Kin_Social_NewCollaborator_Starter.html`). New-hire announcement. A URL tag
(Yellow bar + `kinanalytics.com`) sits top-left. A large **panel hexagon** carries the
identity block — country flag, name in large **Space Grotesk**, role in a tracked chip, and
the team line — with the collaborator's **portrait inside an overlapping hexagon** on the
right (grayscale treatment, per the §04 photography rules). The **"Kin" logo from file**
sits bottom-right. The `data-theme` attribute on `<html>` switches **Light** (default: gray
canvas, Yellow panel, black chip with Yellow text, black logo) and **Dark** (dark canvas,
light panel, Yellow chip with black text, white logo) — the panel, chip, URL, portrait
fill, and logo variant all flip together. Portrait and flag are local placeholder assets to
be replaced.

> If a new social format is needed (1:1 square, 9:16 story, client announcement), add it
> under the same **"Social Media — "** prefix and confirm the layout before improvising a
> new family — don't silently invent one.

### Documents (DOCX)

- White background, Black body text (`#141417`)
- Headings: Space Grotesk Bold, Black; sub-headings: Space Grotesk Medium, Gray 4
- Body: Albert Sans Regular
- Use Yellow rules/bars sparingly for section breaks
- Tables: Gray 1 alternating rows, Gray 2 borders

### B2B Case Study / Sales Enablement (DOCX) — Approved Format

There is an approved Kin format for client-facing case studies and sales-enablement
documents — dark title banner, two-column body with a metrics sidebar, yellow section
bars, and a black CTA footer. The full layout spec and Node.js (`docx` v9+) template
live in **`references/docx-case-study.md`**.

> Note: the `kin-use-case` skill also produces case-study docs — if it's available,
> defer to it for narrative/structure and use this spec for the visual rules.

### Web / HTML Artifacts

- Embed fonts as base64 — never use Google Fonts CDN or system fallbacks.
- Use the CSS custom-property palette and font/logo embedding code in
  **`references/web-html.md`**.

#### Presentation-surface gray token

Beyond the usual surfaces, the design system defines `--ka-color-bg-gray2` (`#D4D5D6` in light, mapping to Gray 4 `#222326` in dark) as the presentation/cover surface gray and light-divider fill. Use this token — never hard-code `#D4D5D6` where it applies (per ADHERENCE).

#### Landing pages (following Kin brand end to end)

Start from `assets/templates/Kin_Landing_Starter.html` (a Tier 2 output — extend via `assets/templates/build_landing.py`, don't hand-edit the HTML). A landing follows the section order below; not every page needs every section, but the sequence holds and new section types aren't invented without confirming. All ADHERENCE rules apply.

**Theming.** Light or dark via `data-theme`; every surface comes from tokens. Sections may alternate theme for rhythm — **dark hero, light body, dark CTA band** is the canonical cadence — never the whole page flat in one mode. Kin Yellow is identical in both themes.

1. **Nav** — the "Kin" logo from file top-left (variant to suit the surface), a slim row of links, and a Yellow CTA button (`#E5FF01`, dark ink). `kinanalytics.com` lowercase wherever a URL appears.
2. **Hero** — a display headline in Space Grotesk that **ends on a Yellow-highlighted word or phrase** (the one-pager's end-highlight signature — the close only, never a mid-sentence word). Subcopy in Albert Sans below. Primary CTA = Yellow button, dark text; secondary = ghost link. One or two hexagons from file as accent, never a tessellated background.
3. **Social proof** — a discreet strip of partner/client logos or a single trust line, gray on a recessed surface (`--ka-color-bg-layout`). Logos from file only.
4. **Problem** — a full-width dark band (`#141417`) with a white headline carrying one Yellow-highlighted word (echo of the deck's "problem" slide). Sentence case, no list — one sharp statement plus a support line at most.
5. **Solution / How it works** — three steps in Albert Sans, numbered 01–03, each preceded by a hexagon from file. **All step hexagons are Yellow** (not alternated). Step titles in Space Grotesk, descriptions in gray.
6. **Features** — a grid of 2–3 rounded cards (12px, generous padding, min-height/auto), each with an icon from the **local Kin set**, a Space Grotesk title, and Albert Sans body. Cards on `--ka-color-bg-layout`; never more than one Yellow accent per card.
7. **Metrics / proof** — two or three large figures in Space Grotesk, each with an uppercase gray label; Yellow reserved for the single most important figure. Results as evidence, not promise. May reuse the deck's dashboard treatment (Yellow primary series, Grays secondary) where a chart appears.
8. **Testimonial** — one quote, large, in Space Grotesk, with the Yellow quote-mark block (the deck treatment); attribution in Albert Sans (name in ink, role in gray). One quote per section — never stack several.
9. **Integrations / security** (optional, product pages) — integrations as a row of icon-labelled cards using the local line icons; security/trust as a 2×2 grid with Yellow hexagon bullets (the deck's security slide). Factual copy.
10. **CTA band** — a full-width band (dark `#141417` **or** Yellow — never both competing as background) with a short Space Grotesk headline and one primary button. The sign-off **"Leave it to Kin."** appears here **only if explicitly requested** — never automatically.
11. **Footer** — the formal "Kin Analytics" wordmark from file, a column of links, social handles, and `kinanalytics.com` lowercase. No tagline unless the sign-off was requested in the CTA band.

**Type hierarchy**: hero display → section eyebrows (uppercase, tracked) → section titles → card/step titles → body → caption. Space Grotesk for headlines, numbers, and stats; Albert Sans for all running text.

**Hard rules** (ADHERENCE): colors from tokens, never raw hex/px; `#E5FF01` only as accent, highlight, CTA, and band fill — never a full-page background; logo, hexagons, and icons from file only (original proportion, never deformed; hexagons as 1–2 accents per section, never wallpaper); 12px corners; nothing loaded from the internet.

> If a landing doesn't fit this pattern (multi-page site, a section type not listed, an interactive app surface), flag it and confirm the layout before improvising — don't silently invent a new structure.

### Data Visualizations / Charts

Series & type:
- Series order: Yellow (`#E5FF01`) → White → Gray 3 (`#999EA6`) → Black (`#141417`).
  Yellow is always the primary/highlighted series.
- Background: Black or White depending on theme; flat color only — **no gradients**.
- Axis labels & gridlines: Albert Sans Regular, Gray 3, subtle. Chart titles: Space
  Grotesk Medium.

Patterns from the official dashboard example (`assets/charts/examples/`):
- **Cards/panels:** dark surface (`#1c1c20`–`#222326`) on black, generously rounded
  corners, title in Space Grotesk + a `⋯` menu top-right.
- **KPI / stat numbers:** large Space Grotesk Bold in **Yellow**; supporting labels in
  Gray 3. Secondary stats can be Yellow too on dark.
- **Bar charts:** grouped bars cycling Yellow→White→Gray→Black; value **callout pills**
  are Yellow with **black** text and a small pointer.
- **Progress / ratio bars:** Yellow fill on a Gray track, rounded ends.
- **Donut:** thick ring, flat segments in Yellow/White/Gray/Black, no labels inside.
- **Legends:** small filled **Yellow squares** beside Gray/White labels; values
  right-aligned.

**Assets:** Illustrator master in `assets/charts/source/Kin_Graphs_Style.ai`, rendered
example in `assets/charts/examples/Kin_Graphs_Style.pdf`. **Look at the example and
match it.** File map → `assets/charts/README.md`.

---

## Quick Reference

**Sign-off**: "Leave it to Kin" (only when requested) · (⛔ never "Let knowledge in")  
**Website**: kinanalytics.com (always lowercase)  
**Primary palette**: `#E5FF01` · `#141417` · `#FFFFFF`  
**Supporting grays**: `#222326` · `#999EA6` · `#D4D5D6` · `#EFEFEE`  
**Print**: Yellow = Pantone 394 · Black = Black 6 · ⚠️ Proof yellow before printing  
**Fonts**: Space Grotesk (headings) · Albert Sans Regular (body)  
**Shape motif**: Hexagon — pointy-top, accent only (1–2 max), never wallpaper  
**Style**: Bold · Geometric · High-contrast · Flat · No gradients


---

## 10 — Logo Files (official assets — use these, never recreate)

> **Hard rule.** The real Kin logo is **only** the bundled SVG files below. NEVER draw, typeset, or recreate it — not with `<text>`, not with a hand-built `<polygon>`, not rendered from a font. "Kin" typed in Space Grotesk next to a hexagon is **not** the logo, no matter how close it looks. If no bundled file fits the context, show a neutral placeholder and say so — do **not** fabricate the mark.

The official artwork ships with this skill under `assets/logos/`. Every file is a **transparent SVG** carrying the authentic wordmark/hexagon vector — scalable to any size, ~1 KB each. There is no base64, no generator, no font-rendered fallback: just these files.

### Which file to use

Pick by **logo type** (how much wordmark) and **background**:

| Type | Background | File |
|------|-----------|------|
| **Informal** "Kin" | Dark (`#141417`, `#222326`, dark photo) | `assets/logos/informal/Kin_Logo_IV_19.svg` — white wordmark + yellow hex |
| **Informal** "Kin" | Light **or gray** (white, `#EFEFEE`, `#D4D5D6`, **yellow**) | `assets/logos/informal/Kin_Logo_IV_13.svg` — black wordmark + gray hex |
| **Informal** "Kin" | Muted / secondary (NOT gray brand surfaces) | `assets/logos/informal/Kin_Logo_IV_16.svg` — all gray |
| **Formal** "Kin Analytics" | Dark | `assets/logos/formal/Kin_Logo_FV_19.svg` — white wordmark + yellow hex |
| **Formal** "Kin Analytics" | Light **or gray** | `assets/logos/formal/Kin_Logo_FV_13.svg` — black wordmark + gray hex |
| **Formal** "Kin Analytics" | Muted / secondary (NOT gray brand surfaces) | `assets/logos/formal/Kin_Logo_FV_16.svg` — all gray |
| **Symbol** (hexagon only) | Dark — favicon, app icon, small mark | `assets/logos/symbol/Kin_Logo_S_14.svg` — yellow |
| **Symbol** (hexagon only) | Light — favicon, app icon, small mark | `assets/logos/symbol/Kin_Logo_S_13.svg` — gray |

**Defaults:** use **informal** for most app / web / doc use; **formal** for first impressions and formal covers; **symbol** only where the wordmark wouldn't be legible (≤ ~32 px, favicons, avatars).

**Notes:**
- The formal wordmark is **horizontal** — "Kin Analytics" on one line with the hexagon at the right end. There is no stacked "Analytics-under-Kin" file.
- Only the **horizontal** orientation is bundled. Tagline lockups and vertical lockups are not included — if a design needs one, request the official file; do not improvise it.
- On a **yellow** (`#E5FF01`) surface, use the **light-background** file (black wordmark + gray hex) — the dark wordmark reads cleanly on yellow.
- On a **gray** brand surface (Gray 2 `#D4D5D6` / Gray 1 `#EFEFEE`), use the **light-background** file (dark wordmark + gray hex) — **the same logo as on white**. **Never** use the all-gray muted file (`*_16`) on a gray surface; the gray wordmark on gray lacks contrast (see §02 Color Usage Rules). The `*_16` muted variant is only for special low-emphasis cases, never on the gray brand surfaces.
- Do **not** edit the SVG fills to invent a color treatment that has no file. Use the closest bundled file by contrast, or request the official variant.

### Using the logo files in output

> ⚠️ **Critical gotcha — never naively inline these SVGs.** Each file carries an
> internal `<style>` block using class names `.cls-1`/`.cls-2`. CSS inside inline SVG
> is **not** scoped — it leaks to the whole document, so two inlined logos collide and
> the last rule recolours every logo on the page.

- **HTML / web:** embed each logo as an isolated **data-URI** `<img>` (and the
  favicon). Code → `references/web-html.md`. If you must inline the SVG to
  animate/recolour it, first rename the `.cls-*` classes to be unique per logo.
- **PPTX / raster:** rasterise the SVG to PNG with `cairosvg` before placing it.
  Code → `references/pptx.md`.
- **DOCX:** same cairosvg rasterise; see `references/docx-case-study.md`.

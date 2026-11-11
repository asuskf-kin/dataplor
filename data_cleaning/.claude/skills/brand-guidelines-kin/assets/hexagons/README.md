# Hexagon assets

Kin's core motif as reusable files. See §05 "Hexagons" in SKILL.md for the rules
(pointy-top only, always grouped, the three usage modes).

## What's here

| Path         | Format | Role                                                       |
|--------------|--------|------------------------------------------------------------|
| `patterns/`  | `.svg` | Ready-to-use shapes/patterns — embeddable & recolorable    |
| `source/`    | `.ai`  | Editable Illustrator masters (add yours here)              |
| `reference/` | `.pdf`/`.png` | Composition/usage examples — look-and-match only     |

## Starter SVGs in `patterns/`

| File | Use |
|------|-----|
| `hex-solid.svg` | Filled hexagon — text container, fills, bullets. `fill:currentColor` |
| `hex-outline.svg` | Thin outline hexagon. `stroke:currentColor` |
| `hex-frame.svg` | Thick ring — badges, icon frames, avatars |
| `hex-cluster.svg` | **Accent pair** — two touching hexagons (the max grouping), outline |
| `hex-cluster-accent.svg` | Accent pair with one hexagon **yellow** (focal) |

These are **recolorable**: single-color shapes use `currentColor`, so set the color
in CSS (`color:#E5FF01` etc.) or per §05's background rules.

> ⚠️ **Canon (Kin Design System):** the hexagon is an **accent — one or two per
> composition, never a background tessellation / honeycomb wallpaper / repeating
> pattern**. That's why there is **no `hex-pattern` tile** here. Point-up only; never
> stretch, skew, or rotate.

## What to upload (advice)

- **Prefer SVG** for any hexagon shape/pattern that gets placed in output — scalable,
  tiny, recolorable. Replace/extend the starter files above; keep the same names so
  nothing else needs to change, or add new ones like `hex-<use>.svg`.
- **`.ai`** masters → `source/` (optional, for designers).
- **`.pdf`/`.png`** only for *usage inspiration* → `reference/`. Don't use raster for
  the shapes themselves — it can't recolor or scale.

## Using them

- **Photo in a hexagon** needs no file — use a CSS `clip-path` (see
  `references/web-html.md`).
- **Web:** inline the SVG and set `color:`, or embed as a data-URI. Code →
  `references/web-html.md`.
- **PPTX/DOCX:** recolor, then rasterise with `cairosvg`. Code → `references/pptx.md`.

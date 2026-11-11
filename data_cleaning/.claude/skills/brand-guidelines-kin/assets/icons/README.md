# Icon assets

Kin's geometric line-icon set. See §06 "Icon Style" in SKILL.md for the style rules
and the per-background color table.

## What's here

| Path          | Format | Role                                                        |
|---------------|--------|-------------------------------------------------------------|
| `source/`     | `.ai`  | **Master** — official Adobe Illustrator artwork (`Kin_Icons.ai`) |
| `reference/`  | `.pdf` | The official spec sheet (`Kin_Icons.pdf`) — all icons × weights × backgrounds |
| `bold/`       | `.svg` | Ready-to-embed icons, **Bold** weight (default — UI, headers) |
| `regular/`    | `.svg` | Ready-to-embed icons, **Regular** weight (body-size contexts) |

> **The SVGs in `bold/` and `regular/` are traced to match the official sheet** so they
> can be embedded directly (a `.ai`/`.pdf` can't be dropped into HTML or a slide). For
> pixel-perfect production work, export fresh SVGs from `source/Kin_Icons.ai` and drop
> them in to replace these — the filenames are the contract.

## The 9 icons

`folder` · `documents` · `email` · `cloud-upload` · `arrow` · `search` ·
`data-grid` · `line-chart` · `bank`

Naming: `icon-<name>-<weight>.svg` (e.g. `icon-search-bold.svg`). Extend from this
Finance/Enterprise vocabulary — don't introduce decorative or illustrative icons.

## Recoloring

The SVGs are **monochrome and stroke-based** with `stroke="currentColor"`, so one file
works on any background — set the color per §06's table (white on dark, black on
light/gray/yellow). Never bake in yellow or gray icon colors.

## Embedding in output

- **HTML / web:** inline the SVG and set `color:` (uses `currentColor`), or embed as a
  data-URI `<img>`. Code → `references/web-html.md`.
- **PPTX / DOCX:** recolor first, then rasterise to PNG with `cairosvg`.
  Code → `references/pptx.md`.

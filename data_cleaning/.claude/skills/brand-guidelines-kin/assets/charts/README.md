# Chart / graph style assets

Kin's graph style. These are **visual ground truth** — when you render a chart in code,
match these examples and the patterns in §09 "Data Visualizations / Charts" of SKILL.md.

## What's here

| Path         | File                     | Role                                          |
|--------------|--------------------------|-----------------------------------------------|
| `source/`    | `Kin_Graphs_Style.ai`    | Editable Adobe Illustrator master art         |
| `examples/`  | `Kin_Graphs_Style.pdf`   | Rendered dashboard example — look at & match  |

> `.ai` and `.pdf` are **reference/source**, not runtime-embeddable like the logo
> SVGs. Use them to see exactly how an on-brand chart looks (colors, gridlines,
> labels, spacing), then reproduce that in whatever the output needs (HTML/SVG, PPTX
> chart, matplotlib, etc.). To add more, drop in `chart-<type>.ai` / `.pdf`.

## Style anchors (from §09 — keep examples consistent with these)

- Primary series: Kin Yellow `#E5FF01`
- Secondary: Gray 3 `#999EA6` · Tertiary: Gray 2 `#D4D5D6`
- Background: Black `#141417` (dark theme) or White (light theme)
- Axis labels: Albert Sans Regular, Gray 3
- Chart titles: Space Grotesk Medium
- Flat color only — no gradients

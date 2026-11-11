# Design tokens — single source of truth

This folder holds the **machine-readable brand tokens**. The goal is that color,
typography, spacing, radius, and shadow are defined **once, here**, and every other
file (SKILL.md, `references/web-html.md`, the build scripts) **references these values
instead of re-typing them**. Duplicated palettes are what drift and get "invented" —
this folder exists to prevent that.

## Files

| File | Holds | Status |
|------|-------|--------|
| `colors_and_type.css` | `:root` CSS custom properties — color + typography tokens | drop in from Claude Design |

> Built in Claude Design — paste/export it here as `colors_and_type.css`. Once it's in,
> it becomes the canonical token set; the rest of the skill should be pointed at it.

## What a complete token set should cover (the "musts")

- **Color:** core (yellow/black/white), grays 1–4, semantic roles (bg, surface,
  text-primary/secondary, border, accent, focal) for dark **and** light, photography
  duotone (`#222326`→`#D8D8D5`), chart series order, states (hover/active/disabled/focus).
- **Typography:** families + fallbacks (Space Grotesk, Albert Sans), weight tokens,
  a size scale (display→caption/overline), line-height + letter-spacing, the
  `kinanalytics.com` rule (Albert Sans Medium 500, gray-3).
- **Spacing / radius / shadow:** if `colors_and_type.css` only covers color+type, add
  `spacing_radius_shadow.css` (or extend this file) — those categories must be written
  down, not left to taste. The brand is flat, so shadow is likely `none` — but say so
  as a token.

Designer-facing equivalents (Adobe `.ase` swatches, `.ai`, `.pdf`) live in
`../color/source/`. Keep the two in sync: the `.ase` and the CSS must agree on hex.

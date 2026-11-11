# Changelog — brand-guidelines-kin

Kin Analytics visual brand skill. Dates are absolute (YYYY-MM-DD).
Owner: Kin Marketing — Brand (cristina.mosquera@kinanalytics.com).

## 1.13 — 2026-09-01 — Social Media 4:5 templates (We're Hiring + New Collaborator)

Added the official 4:5 (1080×1350) social family under the "Social Media — " prefix, replacing
the thin "Social Media (1:1 Square)" note in §09.

- **New starters** as flat files in `assets/templates/` (same convention as
  `Kin_OnePager_Starter.html`, `Kin_Document_Starter.html`, etc. — not in subfolders):
  `Kin_Social_Hiring_Starter.html` (gray canvas, top-right Yellow hexagon lockup with black
  Kin logo, black role band with Yellow Space Grotesk, Yellow label chips, black "WHAT WE
  OFFER" hexagon block) and `Kin_Social_NewCollaborator_Starter.html` (identity hexagon +
  overlapping portrait hexagon, **Light/Dark via `data-theme`** on `<html>` — panel, chip,
  URL, portrait fill, and logo variant all flip together).
- Both are **self-contained** (fonts base64-embedded, logo/hexagons from file, no CDN),
  built to the same standards as the other starters (editable placeholder copy, from-file
  assets, nothing from the internet). Portrait and flag ship as replaceable placeholders.
- **Reference designs** saved to `assets/templates/reference-designs/`:
  `social-hiring-reference-1.jpg`, `social-new-collaborator-light-reference-1.jpg`,
  `social-new-collaborator-dark-reference-1.jpg` (the specimens used in Claude Design).
- SKILL.md: rewrote §09 "Social Media" to a full 4:5 spec, registered both starters in the
  "Where the code lives" table and the "Starter templates" list.
- **Hexagon fidelity fix (post-review):** both starters use the canonical **regular point-up**
  hexagon (W/H ≈ 0.866, same geometry as `assets/logos/symbol/`) — never stretched. The
  New-Collaborator panel and portrait hexagons had been drawn with `preserveAspectRatio="none"`
  (elongated); replaced with true regular hexagons sized to the reference. The Hiring
  top-right lockup (small gray hex + large Yellow hex with the black Kin logo) was re-measured
  from the specimen so proportion and bleed match. **The Hiring top-right hexagons now use
  the official `assets/hexagons/patterns/hex-solid.svg` asset** (embedded as a recoloured
  data-URI, Yellow + Gray) rather than any hand-authored `<polygon>` — nothing is redrawn.

## 1.11 — 2026-08-03 — Document template re-aligned to PDF (cover geometry + logo + clusters)

Corrected fidelity issues in `Kin_Document_Starter.html` found by comparing it pixel-by-pixel
against `Document_Template.pdf`:

- **Cover hexagon geometry measured from the PDF, not eyeballed.** Extracted the dark
  hexagon's real bounds (≈68% page width, horizontally centered, polygon top at ~29% height)
  and sized/positioned the placed SVG to match, compensating for the ~17% transparent padding
  inside the hexagon file. The title/eyebrow/subtitle now sit centered in the hexagon's lower
  half (as in the PDF) instead of spilling past its bottom edge.
- **Cover uses the short "Kin" mark** (`Kin_Logo_IV_13.svg`), matching the PDF — was the full
  "Kin Analytics" wordmark.
- **Yellow corner hexagon** repositioned to peek from behind the dark hexagon and clip against
  the page's bottom-left edges (via `overflow:hidden`), as in the PDF.
- **Decorative hexagon clusters** on the title, contents, and content pages are now **two
  overlapping hexagons** (matching the PDF), not one.

Still fully self-contained (fonts base64, hexagons placed/recolored from the master SVG — no
hand-drawn paths, zero external URLs), A4.

## 1.10 — 2026-08-03 — One-pager & document templates aligned to official PDFs

Re-aligned the two HTML starters (added in 1.9) to the **official exported PDFs** of the
Design System, so the templates match the source of truth exactly rather than a
reconstruction from screenshots.

- **`Kin_OnePager_Starter.html` rebuilt to `One_Pager_Template.pdf`.** Now follows the exact
  §09 one-pager anatomy: header (logo + URL), black title band (eyebrow + title +
  subtitle/category), opening headline with the **Yellow end-highlight** beside two
  paragraphs, journey row 01–05 with all-Yellow hexagons, black impact banner with
  hexagon-prefixed +XX%/−XX% metrics, two columns (Yellow hex + black hex headings) with
  01–04 lists, three-data row (last Value highlighted), and the "Leave it to Kin." sign-off
  bottom-right. **Page size corrected to A4** (was Letter).
- **`Kin_Document_Starter.html` rebuilt to `Document_Template.pdf`.** Now the real 5-page
  structure: (1) light-gray **cover** with the large dark hexagon holding centered eyebrow +
  Yellow title + subtitle and a Yellow corner hexagon; (2) **title page** ("Playbook" eyebrow,
  big title, "Kin Analytics Confidential / Version / date", decorative gray hexagon);
  (3) **table of contents** (section/subsection rows + page numbers, gray hexagon);
  (4–5) **content pages** with `NN — Section title` eyebrow, section heading, subsection
  headings, body paragraphs / bulleted list, and decorative gray hexagons. **A4.**
- Both remain fully self-contained (fonts base64, logo + hexagons placed from file — the
  black/gray hexagons are recolored from the Yellow master SVG, still not hand-drawn — zero
  external URLs). Export via Print→Save as PDF.

## 1.9 — 2026-08-03 — Self-contained one-pager & document templates bundled

Completed the "start from a real template" set: alongside the PPTX template (1.8), the
skill now ships editable HTML starters for the one-pager and multi-page document so those
formats aren't rebuilt from scratch either.

- **Added `assets/templates/Kin_OnePager_Starter.html`** and
  **`assets/templates/Kin_Document_Starter.html`** — rebuilt from the Design System's
  Claude Design exports into **fully self-contained** HTML.
- **Why rebuilt, not stored as-is.** The uploaded exports were Claude Design *bundler*
  artifacts: they loaded React from a CDN (unpkg.com), carried the fonts in the bundler's
  gzip format rather than standard `data:font` base64, and drew the Kin logo as inline SVG
  paths — three violations of the skill's "no CDN, fonts base64, logo placed from file, no
  hand-drawn logo" rules. Stored as-is they'd render only inside Claude Design and would
  substitute to Arial on Print→PDF (the recurring font bug). Verified the bundle's fonts are
  byte-identical (md5) to the skill's TTFs, so the rebuilds reuse the skill fonts exactly.
- **Both templates now:** base64-embed Space Grotesk + Albert Sans (regular + italic),
  place the logo and hexagons from file (zero hand-drawn paths), use the official dark cover
  photo for the document, and carry **no external URLs** — so they open anywhere and export
  cleanly via Print→Save as PDF.
- **Updated §09** (One-Pager and Document sections), the formats table, and the
  starter-templates list to point at the new files as the required starting point.

## 1.8 — 2026-08-03 — Canonical PPTX template bundled as the required starting point

Fixed the root cause of decks losing their fonts, photo covers, and light/dark system:
the skill had **no editable deck**, only reference PNGs, so decks were being rebuilt from
scratch and never matched the Design System.

- **Bundled `assets/templates/Kin_Presentation_Template.pptx`** — the real 20-slide Design
  System deck (dark/light covers, section dividers, the light↔dark system, all 20 layouts).
  This is now the **required starting point**: decks are made by duplicating and filling its
  slides, never regenerated from scratch with python-pptx/pptxgenjs.
- **Embedded Space Grotesk + Albert Sans (regular + bold) inside the template.** The
  original Design System .pptx referenced the fonts by name but did **not** embed them, so
  it substituted to Arial on any machine without the fonts installed — the exact bug seen in
  generated decks. The bundled copy embeds them (fntdata + `embedTrueTypeFonts` +
  `embeddedFontLst` after `notesSz`), so filled decks keep Kin's type anywhere. Validated.
- **Rewrote the PPTX rule** in SKILL.md §09 and `references/pptx.md`: lead with the
  duplicate-and-fill workflow (thumbnail → add_slide → clean → edit `run.text` → validate
  `--original`), keep per-slide dark/light backgrounds intact, and treat scratch-building as
  a rare fallback that must re-embed fonts. Updated the formats table and starter-templates
  list to point at the template.

## 1.7 — 2026-07-30 — Official TTF fonts bundled; token source rebuilt; gray2 synced

Root-caused why documents/decks lost the Kin fonts on export and closed the gaps
against the current Design System README.

- **Fonts — added the official variable TTFs.** The skill previously shipped **only
  woff2**, but the Design System's canonical format is **variable TTF**, and Office
  (PPTX/DOCX) cannot consume woff2 — so decks/docs silently fell back to a system font.
  Bundled `space-grotesk.ttf`, `albert-sans.ttf`, and `albert-sans-italic.ttf` (from the
  Design System master) alongside the woff2 (now **regenerated from the same TTF master**
  so they can't drift). §03 documents both formats and which to use where.
- **`references/pptx.md`** — replaced the vague "use the .ttf builds if you have them"
  with concrete install + variable-font instancing steps, and flagged that Space Grotesk's
  variable default is 300 / family name "Space Grotesk Light" (set weight explicitly).
- **`references/web-html.md`** — added an italic `@font-face` for Albert Sans.
- **Rebuilt `assets/tokens/colors_and_type.css`** — it was declared the single source of
  truth for color+type but was **missing from the skill**. Reconstructed from the README
  tokens (grays 1–4, semantic light/dark roles, chart series, type scale, the
  `kinanalytics.com` rule).
- **Added `--ka-color-bg-gray2`** (`#D4D5D6` light → `#222326` dark) to §02 — the
  presentation-surface gray used by the C-variant covers and light section dividers.

Weight ranges verified from the TTFs: Space Grotesk `wght` 300–700; Albert Sans 100–900.

**Full README concordance audit (same release).** Cross-checked every section of the skill
against the Design System README (428 lines). Result: ~95% aligned. Fixes applied:

- **Removed unapproved display lines.** "Say hello to knowing." and "Smarter decisions."
  were listed as approved display lines but appear **nowhere** in the Design System README,
  which sanctions only the sign-off "Leave it to Kin" (and bans "Let knowledge in").
  Removed from the Overview, Quick Reference, the Social Media footer, and the DOCX
  case-study page footer. (Historical CHANGELOG entries left intact as record.)
- **Landing page added to the formats table.** The landing-page pattern existed in §09 but
  was missing from the "Producing…" navigation table; added its row.
- **Logo filenames — deliberately kept as FV/IV SVG.** The README names the footer logo
  `kin-analytics-logo.png`, but the skill's `Kin_Logo_FV_*/IV_*.svg` system (6 files:
  formal/informal × 3 color variants) is more complete and matches the actual files on
  disk. Kept the skill's system rather than sync backward to a lossier name. Flag for the
  Design System to update its README naming to match.
- **Known README self-contradiction (no skill change needed).** The README's journey-row
  hexagons say "alternating yellow and black" in one place and "all yellow, no exception"
  in another; the skill already follows the explicit override (all yellow). Flag to fix
  upstream.

## 1.6 — 2026-07-28 — Typography roles aligned to design-system canon

Fixed the font-role tables, which contradicted the design system and themselves:

- **Space Grotesk → display / titles / numerals / stats; Albert Sans → body /
  paragraphs / UI labels.** Removed "labels/UI" from the Space Grotesk row (it belongs
  to Albert Sans) and made "numerals" explicit, matching the README canon.
- **Resolved the overline/eyebrow contradiction** (one row said Albert Sans, another said
  Space Grotesk). The design-system README fixes only the *treatment* of eyebrows
  (UPPERCASE, tracked-out, Gray 3/Yellow) and does not mandate a family, so the skill now
  leaves the eyebrow typeface **open** (either family), with a note to stay consistent
  within a deliverable.

## 1.5 — 2026-07-28 — One-pager & document: same no-draw + Kin-fonts protection

Extends the PPTX hardening to one-pagers and multi-page documents (HTML → PDF → Drive):

- **Format map** now lists one-pager and document, both routed to `references/web-html.md`
  (build as self-contained HTML sized to the page, then Print → Save as PDF; the same HTML
  goes to Google Drive/Docs).
- **`web-html.md` hexagon section fixed**: previously it taught `clip-path` to draw a
  hexagon — which contradicts ADHERENCE #5 and caused hand-drawn hexagons. Now a brand
  hexagon is **placed from an approved file** (data-URI `<img>`); `clip-path` is allowed
  **only** to mask a photo/content box into a hexagon silhouette, never to fabricate the
  brand mark.
- **`web-html.md` logo + fonts hardened** with ⛔ notes: never re-create the wordmark as
  font-text/paths (ADHERENCE #5); never fall back to a system font or CDN — always embed
  Space Grotesk + Albert Sans from `assets/fonts/` (ADHERENCE #3), one-pagers/documents
  included.
- Added an HTML → PDF → Drive note with `@page` sizing for one-pager/document.
- Verified the woff2 fonts are valid and base64-embed cleanly for HTML/PDF.

## 1.4 — 2026-07-28 — PPTX: harden logo/hexagon placement + fix divider chevron

Targeted fix for PPTX decks drawing a fake logo (wrong "Kin" letters), redrawing
hexagons, and rendering the section divider as a flat yellow stripe:

- **`references/pptx.md` rewritten**: a ⛔ hard warning to never rebuild the logo/hexagon
  with `add_shape`/`MSO_SHAPE`/freeform/font-text; a single `place_svg()` helper as the
  ONLY way art enters a slide (rasterize approved SVG → `add_picture`); explicit hexagon
  placement; and a **section-divider chevron** section (yellow hexagon-point, never a
  rectangular stripe).
- **ADHERENCE #5 reinforced** to name the PPTX failure mode (`add_shape` built to look
  like the mark) and point to the per-format placement method.
- **Section divider** description in §09 + slide catalog corrected: it is the **pointed
  tip of a hexagon (chevron)**, not a "chevron-panel"/"angular block"/stripe.
- Verified `cairosvg` rasterizes all logo + hexagon SVGs cleanly (letters render correct).

## 1.3 — 2026-07-07 — Logo-drawing fix + Google Slides / export rules

Fixes decks rendering a **hand-drawn logo** and off-spec footers:

- **New ADHERENCE hard rule #5**: never draw/typeset/trace/rebuild the logo or hexagon —
  place only from `assets/logos/` (and `assets/hexagons/`), and **rasterize SVG→PNG** for
  PPTX. Includes a quick file map so the exact path is present at the point of use, not
  buried in §10. If no file fits, leave the slot empty and say which file is missing.
- **Content-slide footer** now names the exact files inline
  (`Kin_Logo_FV_13.svg` light/gray · `Kin_Logo_FV_19.svg` dark).
- **Google Slides target**: decks are built responsive for Google Slides/Drive (nothing
  bleeds past the 16:9 frame; vertical centering; auto-height text).
- **Vertical rhythm** rule (title-high / body-mid) and legibility/padding guidance.
- **Blocks stay whole on export**: eyebrow+title+subtitle(+metadata) as one stacked
  container, no absolute-positioned inner texts, so PDF/PPTX export doesn't split them.
- **One-pager Band theme** (dark default / light hybrid — top band stays black).
- **Journey-step hexagons corrected to all-Yellow** (were "alternating"); two-column
  detail headings keep their yellow/black pairing.

## 1.2 — 2026-07-06 — Reference designs + one-pager/document/landing patterns

Purely additive — no existing rule, token, asset, or tagline decision from 1.1 was
changed. Added on top of the 1.1 base:

- **Rendered reference designs** in `assets/templates/reference-designs/`: the 20-slide
  Kin Presentation deck, cover/agenda variant comparisons, and the one-pager specimen.
  §09 now catalogs every slide layout and points to them; `references/pptx.md` points to
  them too.
- **§09 Presentations expanded** to match the design-system README: light/dark surface
  rhythm, the three A/B/C cover & section-divider background variants, the
  `--ka-color-bg-gray2` presentation-surface token, and the two-element content footer
  (formal wordmark + lowercase `kinanalytics.com`, no sign-off).
- **New One-Pager pattern** (header band → Yellow end-highlight headline → journey row
  with alternating Yellow/black hexagons → impact banner → two hex-headed columns →
  three-data row → "Leave it to Kin." footer with Yellow hexagon).
- **New multi-page Document pattern** (cover / TOC / content pages). The **cover uses
  one of two official full-bleed images** (`assets/templates/document-covers/` — gris
  and black), with editable text inside the centre hexagon; hexagons live in the image
  and are never redrawn. TOC and content pages carry a ≈0.05 hexagon watermark.
- **New landing-page guidance** in Web/HTML, matching the design-system README's official
  11-section pattern (nav → hero → social proof → problem → how-it-works → features →
  metrics → testimonial → integrations/security → CTA band → footer), start from
  `Kin_Landing_Starter.html`, `data-theme` theming, all under ADHERENCE.
- **Title-box integrity** rule added for all covers (presentation + document): eyebrow,
  title, subtitle, and metadata row are one stacked container in normal flow with
  auto-height + bottom padding, so PDF font substitution can't detach the metadata row.
- **Content-slide footer**: clarified the logo/URL hug the bottom corners (tight side
  margin), not pulled toward the centre.

Tagline handling is unchanged from 1.1: approved display lines "Say hello to knowing." /
"Smarter decisions."; sign-off "Leave it to Kin." only when explicitly requested;
"Let knowledge in" remains banned.

## 1.1 — 2026-06-25 — Conform to Kin Design System (canonical)

- **Removed the banned tagline "Let knowledge in"** everywhere (SKILL.md, references,
  cheat-sheet, landing + build scripts) — replaced with approved display lines
  ("Say hello to knowing." / "Smarter decisions."). Documented the ban.
- **Hexagon = accent (1–2 max), never wallpaper.** Reconciled §05/§07/§08, removed the
  `hex-pattern` honeycomb tile, reduced cluster assets to a 2-hex accent pair, and
  changed the landing hero to a single hexagon.
- **Yellow ≈ 3%** (was ~10%), never a dominant surface.
- **Logo on gray surfaces** (Gray 1/2): use the light-background (dark-wordmark) logo —
  same as white; never the all-gray `*_16` muted variant (no contrast on gray). Added
  to §02 Color Usage Rules + §10.
- Added **radius (12px default)** and **token-adherence** rules (no raw hex/px, no
  external fonts) pointing at `assets/tokens/colors_and_type.css`.

- **Merged in the Design System's structural rules** (kept this richer SKILL.md as the
  base): added **FILE AUTHORITY** (Tier 1/2), **ADHERENCE** hard rules (no raw
  hex/px, no external fonts/imports), and the **light/dark theming** model
  (`data-theme`).

> Governance note: the earlier "Tier 1 / single source of truth" framing is superseded
> — canonical spec = Kin Design System; this skill is its synced export.

## 1.0 — 2026-06-23

First governed, asset-complete release. Consolidates and supersedes the older
monolithic `brand-kin` skill (which carried no bundled assets). Designated
**Authority Tier 1 (Governance 1)** — the single source of truth for Kin Analytics
visual identity; on any visual conflict, this skill overrides other files/templates.

**Added**
- Bundled assets: official logos (formal/informal/symbol SVGs), Space Grotesk +
  Albert Sans variable fonts (woff2 + OFL licenses).
- Icon set: 9 geometric line icons × bold/regular as recolorable (`currentColor`)
  SVGs, traced to match `Kin_Icons.ai`; plus the `.ai` master + `.pdf` reference.
  Verified each icon against the official sheet (corrected `data-grid` and `bank`).
- Chart/graph style: `Kin_Graphs_Style.ai` master + `.pdf` example, with the
  observed dashboard patterns documented in §09.
- Hexagon assets: reusable recolorable SVGs in `assets/hexagons/patterns/` (solid,
  outline, frame, cluster, accent cluster, seamless pattern) + `source/`/`reference/`
  folders + `build_hexagons.py`. §05 wired to point at them; landing page hexagon
  section expanded to show four uses (text container, image container, badge, cluster).
- Shareable one-pager: `assets/quick-reference/Kin_Brand_Cheatsheet.html` (print →
  PDF) + `build_cheatsheet.py` to regenerate it.
- Starter template: `assets/templates/Kin_Landing_Starter.html` — self-contained
  responsive landing page + full element showcase (palette, type, on-brand charts,
  hexagon text/image containers, honeycomb, icon library) across **dark and light
  themes** + `build_landing.py` to regenerate it.
- Governance: this changelog and a version/owner/last-updated header. Scope kept
  strictly to visual identity (no cross-links to marketing/voice skills, by design).

**Changed**
- Refactored to progressive disclosure: lean `SKILL.md` (decisions) + `references/`
  by output format (`web-html`, `pptx`, `docx-case-study`, `photography`).
- Tightened the description for triggering accuracy; scoped the skill to *visual*
  identity (voice/copy handed off to the related skills).
- Removed the stale "2024" from the title; aligned to a single current year.

**Removed**
- `brand-kin` — duplicate skill with no bundled assets — deleted from the skills
  directory (backed up to `~/Downloads/brand-kin-DEPRECATED-backup.zip`).
  `brand-guidelines-kin` is now the sole Kin Analytics visual brand skill.

---

## 1.12 — 2026-08-03 — Document cover & decorative hexagons use official Design System assets

Replaced the hand-positioned hexagons in `Kin_Document_Starter.html` with the **actual
Design System artwork**, so the cover and interior decoration are pixel-faithful instead of
reconstructed.

- **Cover uses the official cover image.** Bundled the two official vertical cover templates
  (`vertical_black`, `vertical_gris`) as `assets/templates/document-covers/cover-vertical-{black,gris}.png`
  and set the gray one as the cover's full-bleed background. The eyebrow + Yellow title +
  subtitle sit centered in the dark hexagon's lower half (measured from the image). This ends
  the earlier problem where the placed hexagons and Yellow corner shape didn't match.
- **Interior decorative clusters extracted from the PDF.** The title, contents, and content
  pages now use the real **three-hexagon clusters** lifted from `Document_Template.pdf`
  (`deco-cluster-topright/bottomleft/bottomright.png`, white made transparent), replacing the
  earlier two single hexagons positioned by eye.
- Still A4, still self-contained (fonts + all imagery base64, zero external URLs). Note: the
  cover and clusters are now raster PNGs of official art rather than placed SVGs — the faithful
  source, treated like the existing bundled cover photos.

*To cut a new version: make changes, bump the version in `SKILL.md`'s header and
here, set the date, and re-run `build_cheatsheet.py` if any visual element changed.*

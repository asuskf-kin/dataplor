# DOCX — B2B Case Study / Sales Enablement (Approved Format)

Read this when producing a **client-facing case study or sales-enablement DOCX** in
the approved Kin format. Uses the `docx` npm library (v9+); rasterize logos with
`cairosvg` (see `references/pptx.md` for the pattern). Paths relative to skill dir.

> **Overlap note:** the `kin-use-case` skill also produces case-study documents. If
> both are available, prefer whichever the user names; otherwise treat `kin-use-case`
> as the authority on narrative/structure and this file as the visual spec.

For general (non-case-study) DOCX styling, see §09 "Documents" in SKILL.md.

## Page setup
- US Letter (8.5" × 11"), all page margins = 0 (full-bleed tables handle spacing)
- Fonts: Space Grotesk (headings/labels/stats), Albert Sans (body)
- Font sizes in half-points: `size: n * 2`

## Header
- Kin logo left-aligned — rasterise the SVG to PNG for DOCX (`cairosvg.svg2png`); use
  the light-background formal logo (`assets/logos/formal/Kin_Logo_FV_13.svg`)
- `kinanalytics.com` right-aligned in Gray 3, Albert Sans, 8pt
- Gray 2 bottom border rule
- Paragraph indent: left 0.7in, right 0.7in

## Title Banner — full-bleed dark block
- Use a **two-column table** (7440 + 4800 DXA) with **both cells** set to `KIN_BLACK`
  fill — this guarantees Google Docs renders it edge-to-edge
- Left cell: eyebrow label (Yellow, 7.5pt, Space Grotesk Bold) + two-line title (white
  line + yellow line, 19pt Space Grotesk Bold) + subtitle (Gray 3, 10pt Albert Sans)
- Right cell: empty, black fill only
- Cell margins: top/bottom 0.55"/0.5", left 0.7", right 0.4"

## Body Layout — two-column table (7440 + 4800 DXA)
- Left column (7440 DXA): white background, body text, section headers
- Right column (4800 DXA): Gray 4 (`#222326`) background, metrics sidebar

## Section Headers (left body column)
- Yellow background fill bar — implemented as a **nested single-row table** inside the body cell
- Width: 5856 DXA (= 7440 − 1008 left margin − 576 right margin)
- Cell: `KIN_YELLOW` fill, margins top/bottom 90, left/right 160
- Text: uppercase, Space Grotesk Bold, 8pt, `KIN_BLACK` — ⚠️ black text on yellow, NOT yellow text on white
- Add spacer paragraph (before: 200–220) above and (before: 100) below the table

## Body text
- Albert Sans, 10pt, `KIN_BLACK`
- Bold labels for key terms use Space Grotesk
- Closing callout: italic Albert Sans, 10.5pt, Gray 4, with yellow left-border stripe

## Sidebar metrics (right dark column)
- Section label "AT A GLANCE": Yellow, 7.5pt, Space Grotesk Bold — ✅ yellow on dark is allowed
- Big stat number: White, 28pt, Space Grotesk Bold
- Metric label: Yellow, 9pt, Space Grotesk Bold — ✅ yellow on dark
- Description: Gray 3, 8.5pt, Albert Sans
- Dividers: dark gray (`#3D3E42`) bottom border rules
- "ABOUT THIS ENGAGEMENT" metadata section: field labels in Gray 2 bold, values in Gray 3

## CTA Footer — full-bleed black block
- Single-column table, `KIN_BLACK` fill, 12240 DXA
- CTA text (white, Space Grotesk Bold, 11pt) + descriptor (Gray 3, 10pt) +
  `kinanalytics.com` (Yellow, 10pt, Albert Sans Bold) — ✅ yellow on black
- Cell margins: top/bottom 0.32", left/right 0.7"

## Page footer
- "© 2026 Kin Analytics · kinanalytics.com · Page N" — Gray 3, 7.5pt, right-aligned (no tagline; add "Leave it to Kin" only if explicitly requested)
- Gray 2 top border rule

## Critical color rules
- ⛔ NEVER use `KIN_YELLOW` (`#E5FF01`) as text color on white/light backgrounds — illegible
- ✅ Yellow text is only allowed on dark surfaces: `KIN_BLACK` or `KIN_GRAY4`
- ✅ Yellow as a graphic/fill element (borders, backgrounds, rules) is fine on any surface
- Section header text on yellow background must use `KIN_BLACK`, not yellow

## Node.js implementation template (key helpers)
```javascript
const KIN_BLACK = "141417"; const KIN_GRAY4 = "222326"; const KIN_GRAY3 = "999EA6";
const KIN_GRAY2 = "D4D5D6"; const KIN_YELLOW = "E5FF01"; const KIN_WHITE = "FFFFFF";
const HEAD_FONT = "Space Grotesk"; const BODY_FONT = "Albert Sans";
const inch = n => n * 1440;  // DXA
const hp = n => n * 2;       // half-points for font size

// Yellow-bg section header — returns array, spread with ...sectionHead(...)
const SECT_W = 5856; // body content width in DXA
const sectionHead = (text, spaceBefore = 220) => [
  new Paragraph({ spacing: { before: spaceBefore, after: 60 }, children: [] }),
  new Table({
    width: { size: SECT_W, type: WidthType.DXA }, columnWidths: [SECT_W],
    rows: [new TableRow({ children: [new TableCell({
      borders: noB(), shading: { fill: KIN_YELLOW, type: ShadingType.CLEAR },
      margins: { top: 90, bottom: 90, left: 160, right: 160 },
      children: [new Paragraph({ spacing: { before: 0, after: 0 }, children: [
        new TextRun({ text: text.toUpperCase(), bold: true, size: hp(8), color: KIN_BLACK, font: HEAD_FONT }),
      ]})],
    })]})]
  }),
  new Paragraph({ spacing: { before: 100, after: 0 }, children: [] }),
];
```

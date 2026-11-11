#!/usr/bin/env python3
"""Build a self-contained one-page Kin brand cheat-sheet (HTML, print-ready -> PDF).
Embeds the bundled fonts, logo, and icons as base64/data-URI so the file works
anywhere with no network. Run from the skill root: python assets/quick-reference/build_cheatsheet.py"""
import base64, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]   # skill dir
A = ROOT / "assets"

def b64(p): return base64.b64encode(pathlib.Path(p).read_bytes()).decode()
def datauri_svg(p): return "data:image/svg+xml;base64," + b64(p)

grotesk = b64(A / "fonts/space-grotesk.woff2")
albert  = b64(A / "fonts/albert-sans.woff2")
logo_dark  = datauri_svg(A / "logos/formal/Kin_Logo_FV_19.svg")   # white+yellow, for dark bg
logo_light = datauri_svg(A / "logos/formal/Kin_Logo_FV_13.svg")   # black+gray, for light bg

ICON_NAMES = ["folder","documents","email","cloud-upload","arrow","search","data-grid","line-chart","bank"]
icons = {n: (A / f"icons/bold/icon-{n}-bold.svg").read_text() for n in ICON_NAMES}

COLORS = [
    ("Kin Yellow", "#E5FF01", "#141417"), ("Black", "#141417", "#FFFFFF"),
    ("Gray 4", "#222326", "#FFFFFF"), ("Gray 3", "#999EA6", "#141417"),
    ("Gray 2", "#D4D5D6", "#141417"), ("Gray 1", "#EFEFEE", "#141417"),
    ("White", "#FFFFFF", "#141417"),
]
swatches = "\n".join(
    f'<div class="sw" style="background:{hx};color:{fg}"><span>{name}</span><span class="hex">{hx}</span></div>'
    for name, hx, fg in COLORS)
icon_row = "\n".join(f'<span class="ic">{icons[n]}</span>' for n in ICON_NAMES)

HTML = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Kin Analytics — Brand Quick Reference</title>
<style>
@font-face {{ font-family:'Space Grotesk'; src:url('data:font/woff2;base64,{grotesk}') format('woff2'); font-weight:300 700; }}
@font-face {{ font-family:'Albert Sans'; src:url('data:font/woff2;base64,{albert}') format('woff2'); font-weight:100 900; }}
:root {{ --y:#E5FF01; --k:#141417; --d:#222326; --g3:#999EA6; --g2:#D4D5D6; --g1:#EFEFEE; }}
* {{ box-sizing:border-box; margin:0; padding:0; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
@page {{ size:Letter; margin:0; }}
body {{ font-family:'Albert Sans',sans-serif; background:var(--k); color:#fff; width:8.5in; min-height:11in; margin:0 auto; padding:0.5in 0.55in; }}
h1,h2,h3,.eyebrow,.disp {{ font-family:'Space Grotesk',sans-serif; }}
.eyebrow {{ color:var(--y); font-weight:600; font-size:9px; letter-spacing:.14em; text-transform:uppercase; }}
header {{ display:flex; justify-content:space-between; align-items:flex-start; border-bottom:2px solid var(--y); padding-bottom:14px; }}
header img {{ height:30px; }}
.tag {{ color:var(--g3); font-size:12px; margin-top:6px; }}
section {{ margin-top:18px; }}
.label {{ color:var(--y); font-family:'Space Grotesk'; font-weight:700; font-size:11px; text-transform:uppercase; letter-spacing:.06em; margin-bottom:8px; }}
.sw-row {{ display:grid; grid-template-columns:repeat(7,1fr); gap:6px; }}
.sw {{ border-radius:8px; padding:10px 8px; height:62px; display:flex; flex-direction:column; justify-content:space-between; font-size:10px; font-weight:600; font-family:'Space Grotesk'; }}
.sw .hex {{ font-weight:400; opacity:.85; }}
.cols {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
.type-card {{ background:var(--d); border-radius:10px; padding:16px; }}
.disp {{ font-size:34px; font-weight:700; line-height:1; }}
.type-meta {{ color:var(--g3); font-size:11px; margin-top:8px; }}
.body-samp {{ font-size:12px; line-height:1.6; margin-top:6px; color:#e9e9e9; }}
.logos {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
.logo-cell {{ border-radius:10px; padding:18px; display:flex; align-items:center; justify-content:center; }}
.logo-cell img {{ height:26px; }}
.logo-note {{ color:var(--g3); font-size:10px; margin-top:6px; text-align:center; }}
.icons {{ display:flex; gap:14px; flex-wrap:wrap; background:var(--d); border-radius:10px; padding:16px; }}
.ic svg {{ width:26px; height:26px; color:var(--y); }}
.dd {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
.dd ul {{ list-style:none; font-size:11.5px; line-height:1.75; }}
.dd .do li::before {{ content:'✓ '; color:var(--y); font-weight:700; }}
.dd .dont li::before {{ content:'✕ '; color:var(--g3); font-weight:700; }}
footer {{ margin-top:22px; border-top:1px solid var(--d); padding-top:10px; display:flex; justify-content:space-between; color:var(--g3); font-size:10px; }}
.site {{ font-family:'Albert Sans'; font-weight:500; letter-spacing:.02em; }}
</style></head><body>
<header>
  <div><img src="{logo_dark}" alt="Kin Analytics"><div class="tag">Say hello to knowing. · Smarter decisions.</div></div>
  <div class="eyebrow" style="text-align:right">Brand Quick<br>Reference</div>
</header>

<section><div class="label">Color</div>
  <div class="sw-row">{swatches}</div>
  <div class="type-meta" style="margin-top:8px">Neutrals carry the layout · Yellow is the accent (~3%, never a dominant surface) · never yellow text on light surfaces.</div>
</section>

<section><div class="cols">
  <div class="type-card"><div class="disp">Aa Bb Cc</div><div class="type-meta"><b style="color:#fff">Space Grotesk</b> — headings, titles, labels, stats · weights 300–700</div></div>
  <div class="type-card"><div class="disp" style="font-family:'Albert Sans';font-weight:400">Aa Bb Cc</div><div class="type-meta"><b style="color:#fff">Albert Sans</b> — body copy · weights 100–900</div><div class="body-samp">The quick brown fox jumps over the lazy dog.</div></div>
</div></section>

<section><div class="label">Logo</div>
  <div class="logos">
    <div><div class="logo-cell" style="background:var(--k);border:1px solid var(--d)"><img src="{logo_dark}"></div><div class="logo-note">On dark — white wordmark + yellow hex</div></div>
    <div><div class="logo-cell" style="background:#fff"><img src="{logo_light}"></div><div class="logo-note">On light — dark wordmark + gray hex</div></div>
  </div>
  <div class="type-meta" style="margin-top:8px">Never recreate, stretch, recolor, or rotate the logo. Keep clear space ≥ the hexagon width.</div>
</section>

<section><div class="label">Icons — geometric line, white or black only</div>
  <div class="icons">{icon_row}</div>
</section>

<section><div class="label">Essentials</div>
  <div class="dd">
    <ul class="do"><li>Keep neutrals dominant, yellow as a pop</li><li>Use exact hex + real logo/font files</li><li>Flat color — geometric, high-contrast</li><li>Hexagons pointy-top, grouped in clusters</li></ul>
    <ul class="dont"><li>No gradients or drop shadows</li><li>No yellow text on white/light</li><li>No off-palette colors or system fonts</li><li>No stretched, recolored, or redrawn logo</li></ul>
  </div>
</section>

<footer><span class="site">kinanalytics.com</span><span>© 2026 Kin Analytics · Visual brand quick reference</span></footer>
</body></html>"""

out = pathlib.Path(__file__).resolve().parent / "Kin_Brand_Cheatsheet.html"
out.write_text(HTML)
print("wrote", out, f"({len(HTML)//1024} KB)")

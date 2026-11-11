#!/usr/bin/env python3
"""Build a self-contained, on-brand Kin landing-page + element showcase (HTML).
Exercises every visual element (palette, type, icons, hexagons, honeycomb, charts,
photography duotone, buttons) across BOTH dark and light themes. Embeds bundled
fonts/logo/icons (base64/data-URI) — no network. Run from skill root:
python assets/templates/build_landing.py"""
import base64, math, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
A = ROOT / "assets"

def b64(p): return base64.b64encode(pathlib.Path(p).read_bytes()).decode()
def datauri(p): return "data:image/svg+xml;base64," + b64(p)

grotesk = b64(A / "fonts/space-grotesk.woff2")
albert  = b64(A / "fonts/albert-sans.woff2")
logo_dark   = datauri(A / "logos/formal/Kin_Logo_FV_19.svg")    # white+yellow (dark bg)
logo_light  = datauri(A / "logos/formal/Kin_Logo_FV_13.svg")    # black+gray (light bg)
def icon(name): return (A / f"icons/bold/icon-{name}-bold.svg").read_text()

ICON_NAMES = ["folder","documents","email","cloud-upload","arrow","search","data-grid","line-chart","bank"]

# ---------- hexagon helpers (pointy-top) ----------
def hexpts(cx, cy, r):
    return " ".join(f"{cx + r*math.cos(math.radians(60*i-90)):.1f},{cy + r*math.sin(math.radians(60*i-90)):.1f}" for i in range(6))

def hero_hex(r=150):
    # single large hexagon, duotone-filled (image-mask demo) — 1 hexagon, accent, per canon
    w=math.sqrt(3)*r; h=2*r
    return (f'<svg viewBox="0 0 {w:.0f} {h:.0f}" width="280" aria-hidden="true">'
            f'<defs><linearGradient id="duo" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="#222326"/><stop offset=".5" stop-color="#3a3b3e"/>'
            f'<stop offset="1" stop-color="#D8D8D5"/></linearGradient></defs>'
            f'<polygon points="{hexpts(w/2,h/2,r-2)}" fill="url(#duo)"/></svg>')

def hex_pair(r=34, w=170, stroke="#2e2f33", sw=2):
    # two touching hexagons — the MAX grouping per canon (no honeycomb wallpaper)
    hw=math.sqrt(3)*r; cy=r+2
    p=[(hw/2+2,cy),(hw*1.5+2,cy)]
    return (f'<svg viewBox="0 0 {hw*2+4:.0f} {2*r+4:.0f}" width="{w}" aria-hidden="true">'
            f'<polygon points="{hexpts(p[0][0],p[0][1],r-2)}" fill="#E5FF01"/>'
            f'<polygon points="{hexpts(p[1][0],p[1][1],r-2)}" fill="none" stroke="{stroke}" stroke-width="{sw}"/></svg>')

def hex_frame(stroke=9):
    r=48; w=math.sqrt(3)*r+stroke*2; h=2*r+stroke*2
    return f'<svg viewBox="0 0 {w:.1f} {h:.1f}"><polygon points="{hexpts(w/2,h/2,r)}" fill="none" stroke="currentColor" stroke-width="{stroke}" stroke-linejoin="round"/></svg>'


# ---------- chart helpers (theme-aware) ----------
def bar_chart(dark=True):
    grid = "#34353a" if dark else "#e2e2dd"
    lab  = "#999EA6" if dark else "#6a6d74"
    black_bar = "#141417" if dark else "#141417"
    groups = [("Q1",[2.0,2.6,3.0,1.4]),("Q2",[1.7,3.4,2.7,0.9]),("Q3",[2.2,2.5,3.3,3.0])]
    series = ["#E5FF01","#FFFFFF" if dark else "#222326","#999EA6","#141417"]
    W,H=420,210; pad=28; base=H-30; maxv=3.6; bw=14; gap=4; gw=bw*4+gap*3
    svg=[f'<svg viewBox="0 0 {W} {H}" width="100%" >']
    for i in range(4):
        y=base-(base-20)*(i/3)
        svg.append(f'<line x1="{pad}" y1="{y:.0f}" x2="{W-10}" y2="{y:.0f}" stroke="{grid}" stroke-width="1"/>')
    gx=pad+18
    span=(W-10-gx)/len(groups)
    for gi,(glabel,vals) in enumerate(groups):
        gx0=gx+gi*span+(span-gw)/2
        tallest=max(range(4),key=lambda k:vals[k])
        for bi,v in enumerate(vals):
            bh=(base-20)*(v/maxv); x=gx0+bi*(bw+gap); y=base-bh
            svg.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{bw}" height="{bh:.0f}" rx="3" fill="{series[bi]}"/>')
            if bi==tallest:
                px,py=x+bw/2,y-20
                svg.append(f'<g><rect x="{px-15:.0f}" y="{py-13:.0f}" width="30" height="18" rx="5" fill="#E5FF01"/>'
                           f'<polygon points="{px-4:.0f},{py+5:.0f} {px+4:.0f},{py+5:.0f} {px:.0f},{py+10:.0f}" fill="#E5FF01"/>'
                           f'<text x="{px:.0f}" y="{py:.0f}" font-family="Space Grotesk" font-size="10" font-weight="700" fill="#141417" text-anchor="middle">{int(v*20)}</text></g>')
        svg.append(f'<text x="{gx0+gw/2:.0f}" y="{base+16:.0f}" font-family="Albert Sans" font-size="11" fill="{lab}" text-anchor="middle">{glabel}</text>')
    svg.append('</svg>')
    return "".join(svg)

def donut():
    segs=[("#E5FF01",45),("#FFFFFF",25),("#999EA6",20),("#141417",10)]
    cum=0; circ=[]
    for col,val in segs:
        circ.append(f'<circle cx="60" cy="60" r="44" fill="none" stroke="{col}" stroke-width="18" pathLength="100" stroke-dasharray="{val} {100-val}" stroke-dashoffset="{-cum}"/>')
        cum+=val
    return f'<svg viewBox="0 0 120 120" width="120" height="120"><g transform="rotate(-90 60 60)">{"".join(circ)}</g></svg>'

def progress(label, pct, dark=True):
    track="#34353a" if dark else "#e2e2dd"; txt="#fff" if dark else "#141417"; sub="#999EA6" if dark else "#6a6d74"
    return (f'<div class="prog"><div class="prow"><span style="color:{txt}">{label}</span><span style="color:{sub}">{pct}%</span></div>'
            f'<div class="track" style="background:{track}"><div class="fill" style="width:{pct}%"></div></div></div>')

COLORS=[("Yellow","#E5FF01","#141417"),("Black","#141417","#fff"),("Gray 4","#222326","#fff"),
        ("Gray 3","#999EA6","#141417"),("Gray 2","#D4D5D6","#141417"),("Gray 1","#EFEFEE","#141417"),("White","#FFFFFF","#141417")]
swatches="".join(f'<div class="sw" style="background:{h};color:{f}"><b>{n}</b><span>{h}</span></div>' for n,h,f in COLORS)
icon_lib="".join(f'<span class="ic" title="{n}">{icon(n)}</span>' for n in ICON_NAMES)

FEATURES=[("line-chart","Decisions, quantified","Turn raw signals into ranked, explainable answers your team can act on the same day."),
          ("search","See what others miss","Surface the patterns buried across your data — not dashboards, the read underneath them."),
          ("cloud-upload","Built for your stack","Connect your sources and ship intelligence into the tools you already run on.")]
def cards(): return "".join(f'<article class="card"><span class="card-ic">{icon(i)}</span><h3>{t}</h3><p>{d}</p></article>' for i,t,d in FEATURES)
STATS=[("3x","faster time-to-decision"),("90%","less manual triage"),("100%","explainable outputs")]
stat_items="".join(f'<div class="stat"><div class="num">{n}</div><div class="lbl">{l}</div></div>' for n,l in STATS)

HTML=f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kin Analytics — Landing & Element Showcase</title>
<style>
@font-face{{font-family:'Space Grotesk';src:url('data:font/woff2;base64,{grotesk}') format('woff2');font-weight:300 700;}}
@font-face{{font-family:'Albert Sans';src:url('data:font/woff2;base64,{albert}') format('woff2');font-weight:100 900;}}
:root{{--y:#E5FF01;--k:#141417;--d:#222326;--g3:#999EA6;--g2:#D4D5D6;--g1:#EFEFEE;--card:#1b1c20;}}
*{{box-sizing:border-box;margin:0;padding:0;}}
html{{scroll-behavior:smooth;}}
body{{font-family:'Albert Sans',sans-serif;background:var(--k);color:#fff;line-height:1.6;}}
h1,h2,h3,.btn,.num,nav a{{font-family:'Space Grotesk',sans-serif;}}
.wrap{{max-width:1100px;margin:0 auto;padding:0 28px;}}
.sec{{padding:72px 0;}}
.eyebrow{{font-family:'Space Grotesk';font-weight:700;font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--y);display:inline-block;}}
/* light-theme eyebrow: NEVER yellow text on light -> dark text + yellow accent bar */
.light .eyebrow{{color:var(--d);border-left:4px solid var(--y);padding-left:8px;}}
h2{{font-size:34px;font-weight:700;margin:12px 0 28px;}}
.btn{{display:inline-block;font-weight:600;font-size:15px;padding:13px 24px;border-radius:10px;text-decoration:none;border:2px solid transparent;}}
.btn-primary{{background:var(--y);color:var(--k);}} .btn-ghost{{border-color:#34353a;color:#fff;}} .btn-dark{{background:var(--k);color:#fff;}}
.light .btn-ghost{{border-color:var(--g2);color:var(--k);}}

header{{position:sticky;top:0;background:rgba(20,20,23,.85);backdrop-filter:blur(8px);border-bottom:1px solid var(--d);z-index:10;}}
.bar{{display:flex;align-items:center;justify-content:space-between;height:68px;}} .bar img{{height:26px;}}
nav{{display:flex;gap:24px;align-items:center;}} nav a{{color:var(--g2);text-decoration:none;font-size:14px;font-weight:500;}} nav a:hover{{color:#fff;}}

.hero{{display:grid;grid-template-columns:1.2fr .8fr;gap:40px;align-items:center;padding:84px 0 64px;}}
.hero h1{{font-size:54px;line-height:1.04;font-weight:700;letter-spacing:-.01em;margin:18px 0 20px;}}
.hero h1 .y{{color:var(--y);display:block;}}
.hero p{{color:var(--g3);font-size:18px;max-width:30em;margin-bottom:28px;}}
.cta{{display:flex;gap:14px;flex-wrap:wrap;}} .art{{display:flex;justify-content:center;}}

.sw-row{{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;}}
.sw{{border-radius:10px;padding:12px 10px;height:74px;display:flex;flex-direction:column;justify-content:space-between;font-family:'Space Grotesk';font-size:11px;font-weight:600;}}
.sw span{{font-weight:400;opacity:.85;}}

.type-grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px;}}
.type-card{{background:var(--d);border-radius:14px;padding:24px;}} .light .type-card{{background:var(--g1);}}
.disp{{font-size:40px;font-weight:700;line-height:1;}} .type-meta{{color:var(--g3);font-size:12px;margin-top:10px;}} .light .type-meta{{color:#5b5e66;}}
.weights{{display:flex;gap:14px;flex-wrap:wrap;margin-top:12px;font-family:'Space Grotesk';}}
.weights span{{font-size:18px;}}

.stats{{background:var(--d);}} .stats .wrap{{display:grid;grid-template-columns:repeat(3,1fr);gap:24px;padding:40px 28px;}}
.num{{color:var(--y);font-size:44px;font-weight:700;line-height:1;}} .lbl{{color:var(--g3);font-size:14px;margin-top:6px;}}

.panels{{display:grid;grid-template-columns:1.4fr 1fr;gap:20px;align-items:start;}}
.panel{{background:var(--d);border-radius:16px;padding:22px;}} .light .panel{{background:var(--g1);}}
.panel h3{{font-size:15px;margin-bottom:14px;}} .panel .menu{{float:right;color:var(--g3);}}
.legend{{display:flex;flex-direction:column;gap:10px;margin-top:6px;font-size:13px;}}
.legend i{{width:12px;height:12px;border-radius:3px;display:inline-block;margin-right:8px;}}
.legend .row{{display:flex;justify-content:space-between;align-items:center;}}
.prog{{margin:14px 0;}} .prow{{display:flex;justify-content:space-between;font-size:13px;margin-bottom:6px;}}
.track{{height:8px;border-radius:5px;overflow:hidden;}} .fill{{height:100%;background:var(--y);border-radius:5px;}}

.grid3{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;}}
.card{{background:var(--card);border:1px solid var(--d);border-radius:16px;padding:26px;}}
.light .card{{background:var(--g1);border-color:var(--g2);color:var(--k);}}
.card-ic svg{{width:30px;height:30px;color:var(--y);}} .light .card-ic svg{{color:var(--k);}}
.card h3{{font-size:19px;margin:16px 0 8px;}} .card p{{color:var(--g3);font-size:14.5px;}} .light .card p{{color:#4a4d54;}}

.hex-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:24px;align-items:center;}}
.hex-text{{position:relative;width:160px;height:184px;margin:0 auto;}}
.hex-text .shape{{width:160px;height:184px;background:var(--y);clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);display:flex;align-items:center;justify-content:center;}}
.hex-text .shape b{{font-family:'Space Grotesk';color:var(--k);font-size:15px;text-align:center;padding:0 24px;}}
.hex-img{{width:160px;height:184px;margin:0 auto;clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);
  background:linear-gradient(135deg,#222326 0%,#3a3b3e 45%,#D8D8D5 100%);}}
.hex-badge{{position:relative;width:140px;height:161px;margin:0 auto;display:flex;align-items:center;justify-content:center;}}
.hex-badge .ring{{position:absolute;inset:0;color:var(--y);}} .hex-badge .ring svg{{width:100%;height:100%;}}
.hex-badge .bic svg{{width:46px;height:46px;color:#fff;position:relative;}}
.cap{{text-align:center;color:var(--g3);font-size:12px;margin-top:10px;}} .light .cap{{color:#5b5e66;}}

.iconlib{{display:flex;gap:18px;flex-wrap:wrap;background:var(--d);border-radius:14px;padding:22px;}}
.iconlib .ic svg{{width:28px;height:28px;color:var(--y);}}

.note{{font-size:13px;color:var(--g3);margin-top:14px;}} .light .note{{color:#5b5e66;}}
.tag-ok{{color:#141417;background:var(--y);border-radius:4px;padding:1px 6px;font-weight:700;font-size:12px;}}

.cta-band{{background:var(--y);color:var(--k);}}
.cta-band .wrap{{padding:56px 28px;display:flex;align-items:center;justify-content:space-between;gap:24px;flex-wrap:wrap;}}
.cta-band h2{{font-size:32px;font-weight:700;max-width:16em;margin:0;}}

footer{{padding:46px 0 40px;border-top:1px solid var(--d);}}
footer .wrap{{display:flex;justify-content:space-between;align-items:center;gap:20px;flex-wrap:wrap;}}
footer img{{height:22px;}} .site{{font-family:'Albert Sans';font-weight:500;letter-spacing:.02em;color:var(--g3);font-size:13px;}}
.foot-tag{{color:var(--g3);font-size:13px;}}
@media(max-width:820px){{.hero,.stats .wrap,.grid3,.sw-row,.type-grid,.panels,.hex-row{{grid-template-columns:1fr;}}.hero h1{{font-size:40px;}}.art{{display:none;}}.sw-row{{grid-template-columns:repeat(3,1fr);}}}}
</style></head><body>

<header><div class="wrap bar">
  <img src="{logo_dark}" alt="Kin Analytics">
  <nav><a href="#color">Color</a><a href="#type">Type</a><a href="#charts">Charts</a><a href="#hex">Hexagons</a><a href="#light">Light</a>
    <a class="btn btn-primary" href="#cta" style="padding:9px 18px;font-size:14px">Book a demo</a></nav>
</div></header>

<main>
  <!-- HERO -->
  <section class="wrap hero">
    <div><span class="eyebrow">Analytical intelligence</span>
      <h1>The read underneath your data.<span class="y">Smarter decisions.</span></h1>
      <p>Kin turns the signals scattered across your business into ranked, explainable
         decisions — built for how your team actually operates.</p>
      <div class="cta"><a class="btn btn-primary" href="#cta">Book a demo</a>
        <a class="btn btn-ghost" href="#charts">See how it works</a></div></div>
    <div class="art">{hex_pair(r=70, w=320, stroke="#34353a", sw=2.5)}</div>
  </section>

  <!-- COLOR -->
  <section id="color" class="wrap sec"><span class="eyebrow">Color</span>
    <h2>The palette</h2><div class="sw-row">{swatches}</div>
    <p class="note">Neutrals carry the layout · Yellow is the accent (~3%, never a dominant surface) · never yellow text on light surfaces.</p>
  </section>

  <!-- TYPOGRAPHY -->
  <section id="type" class="wrap sec"><span class="eyebrow">Typography</span>
    <h2>Space Grotesk + Albert Sans</h2>
    <div class="type-grid">
      <div class="type-card"><div class="disp">Aa Bb Cc 123</div>
        <div class="type-meta"><b style="color:#fff">Space Grotesk</b> — headings, labels, stats</div>
        <div class="weights"><span style="font-weight:300">Light</span><span style="font-weight:400">Regular</span><span style="font-weight:500">Medium</span><span style="font-weight:700">Bold</span></div></div>
      <div class="type-card"><div class="disp" style="font-family:'Albert Sans';font-weight:400">Aa Bb Cc 123</div>
        <div class="type-meta"><b style="color:#fff">Albert Sans</b> — body copy (weights 100–900)</div>
        <p style="margin-top:10px;color:#e9e9e9;font-size:14px">The quick brown fox jumps over the lazy dog while the data speaks for itself.</p></div>
    </div>
  </section>

  <!-- STATS -->
  <section class="stats"><div class="wrap">{stat_items}</div></section>

  <!-- CHARTS -->
  <section id="charts" class="wrap sec"><span class="eyebrow">Data visualization</span>
    <h2>Charts, the Kin way</h2>
    <div class="panels">
      <div class="panel"><span class="menu">···</span><h3>Volume by quarter</h3>{bar_chart(dark=True)}</div>
      <div class="panel"><span class="menu">···</span><h3>Deals by stage</h3>
        <div style="display:flex;gap:18px;align-items:center"><div>{donut()}</div>
          <div class="legend">
            <div class="row"><span><i style="background:#E5FF01"></i>Funded</span><b>$135M</b></div>
            <div class="row"><span><i style="background:#fff"></i>Approved</span><b>$21M</b></div>
            <div class="row"><span><i style="background:#999EA6"></i>Review</span><b>$7M</b></div>
            <div class="row"><span><i style="background:#141417;border:1px solid #34353a"></i>Terminated</span><b>$39M</b></div>
          </div></div></div>
    </div>
    <div class="panel" style="margin-top:20px"><h3>Pipeline health</h3>
      {progress("Delivered",80)}{progress("In review",54)}{progress("Stalled",22)}</div>
    <p class="note">Series order: Yellow → White → Gray → Black · yellow callout pills with black text · flat color, no gradients.</p>
  </section>

  <!-- HEXAGONS -->
  <section id="hex" class="wrap sec"><span class="eyebrow">Hexagons</span>
    <h2>One motif, many jobs</h2>
    <div class="hex-row">
      <div><div class="hex-text"><div class="shape"><b>Text container</b></div></div><div class="cap">Copy inside a solid hexagon</div></div>
      <div><div class="hex-img"></div><div class="cap">Image container · duotone (#222326 → #D8D8D5)</div></div>
      <div><div class="hex-badge"><span class="ring">{hex_frame()}</span><span class="bic">{icon('search')}</span></div><div class="cap">Badge / icon frame</div></div>
      <div><div class="art">{hex_pair()}</div><div class="cap">Accent pair — 1–2 max, never wallpaper</div></div>
    </div>
    <p class="note">All pointy-top · reusable files in <code>assets/hexagons/</code>.</p>
  </section>

  <!-- FEATURES + ICON LIBRARY -->
  <section class="wrap sec"><span class="eyebrow">Why Kin</span>
    <h2>Not another dashboard. The decision behind it.</h2>
    <div class="grid3">{cards()}</div>
    <h3 style="margin:34px 0 14px;font-size:16px;color:var(--g2)">Icon set — geometric line, white or black only</h3>
    <div class="iconlib">{icon_lib}</div>
  </section>

  <!-- LIGHT THEME -->
  <section id="light" class="sec light" style="background:#fff;color:var(--k)">
    <div class="wrap"><span class="eyebrow">Light theme</span>
      <h2 style="color:var(--k)">The same brand, on white</h2>
      <p style="color:#4a4d54;max-width:34em;margin-bottom:28px">On light surfaces the logo switches to the dark wordmark, text is black/gray, and
         yellow appears only as a <span class="tag-ok">graphic accent</span> — bars, fills, shapes — never as text.</p>
      <div class="grid3">
        <article class="card"><span class="card-ic">{icon('data-grid')}</span><h3>Structured</h3><p>Black text on white, generous whitespace, yellow used as a rule or bar.</p></article>
        <article class="card"><span class="card-ic">{icon('search')}</span><h3>Legible</h3><p>Albert Sans body in a darker gray keeps long copy comfortable to read.</p></article>
        <article class="card"><span class="card-ic">{icon('bank')}</span><h3>Consistent</h3><p>Same icons, same hexagon motif — only the color roles flip for contrast.</p></article>
      </div>
      <div class="panel" style="margin-top:20px"><span class="menu" style="color:#6a6d74">···</span><h3 style="color:var(--k)">Volume by quarter</h3>{bar_chart(dark=False)}</div>
      <div style="margin-top:22px">{progress("Delivered",80,dark=False)}{progress("In review",54,dark=False)}</div>
      <div class="cta" style="margin-top:26px"><a class="btn btn-primary" href="#cta">Primary</a><a class="btn btn-ghost" href="#">Secondary</a></div>
    </div>
  </section>

  <!-- CTA -->
  <section id="cta" class="cta-band"><div class="wrap"><h2>Say hello to knowing.</h2><a class="btn btn-dark" href="#">Book a demo</a></div></section>
</main>

<footer><div class="wrap">
  <img src="{logo_dark}" alt="Kin Analytics">
  <span class="foot-tag">Say hello to knowing.</span>
  <span class="site">kinanalytics.com · © 2026 Kin Analytics</span>
</div></footer>
</body></html>"""

out = pathlib.Path(__file__).resolve().parent / "Kin_Landing_Starter.html"
out.write_text(HTML)
print("wrote", out, f"({len(HTML)//1024} KB)")

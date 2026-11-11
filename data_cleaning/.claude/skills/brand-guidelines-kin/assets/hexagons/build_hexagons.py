#!/usr/bin/env python3
"""Generate a starter set of reusable Kin hexagon SVGs (pointy-top).
Recolorable via currentColor (single-color shapes) so one file works on any
background; the accent cluster keeps the center yellow as the brand focal.
Run from skill root: python assets/hexagons/build_hexagons.py"""
import math, pathlib

OUT = pathlib.Path(__file__).resolve().parent / "patterns"
OUT.mkdir(parents=True, exist_ok=True)

def pts(cx, cy, r):
    return " ".join(f"{cx + r*math.cos(math.radians(60*i-90)):.2f},{cy + r*math.sin(math.radians(60*i-90)):.2f}" for i in range(6))

def svg(vb_w, vb_h, body, extra=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:.1f} {vb_h:.1f}" '
            f'width="{vb_w:.0f}" height="{vb_h:.0f}"{extra}>\n  {body}\n</svg>\n')

files = {}
r = 48; w = math.sqrt(3)*r; h = 2*r; cx, cy = w/2, h/2

# 1. solid single hexagon — fill currentColor
files["hex-solid.svg"] = svg(w, h, f'<polygon points="{pts(cx,cy,r)}" fill="currentColor"/>')

# 2. outline single hexagon — stroke currentColor
files["hex-outline.svg"] = svg(w+8, h+8, f'<polygon points="{pts((w+8)/2,(h+8)/2,r)}" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/>')

# 3. thick frame / badge ring
files["hex-frame.svg"] = svg(w+16, h+16, f'<polygon points="{pts((w+16)/2,(h+16)/2,r)}" fill="none" stroke="currentColor" stroke-width="9" stroke-linejoin="round"/>')

# 4-5. accent pair — two touching hexagons (the MAX grouping per canon; no wallpaper)
hw = math.sqrt(3)*r
pair = [(hw/2+1, r+1), (hw*1.5+1, r+1)]
vbw, vbh = hw*2+2, 2*r+2
files["hex-cluster.svg"] = svg(vbw, vbh, "".join(
    f'<polygon points="{pts(x,y,r-2)}" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/>' for x,y in pair))
files["hex-cluster-accent.svg"] = svg(vbw, vbh,
    f'<polygon points="{pts(pair[0][0],pair[0][1],r-2)}" fill="#E5FF01"/>'
    + f'<polygon points="{pts(pair[1][0],pair[1][1],r-2)}" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/>')
# NOTE: intentionally NO honeycomb wallpaper/tile asset — hexagons are an accent (1-2 max) per canon.

for name, content in files.items():
    (OUT / name).write_text(content)
print("wrote", len(files), "hexagon svgs:", ", ".join(files))

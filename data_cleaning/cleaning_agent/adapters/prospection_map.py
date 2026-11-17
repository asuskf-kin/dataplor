"""Prospection map (one HTML): canvas on the free Esri World Light Gray basemap.

The map follows the team's kin-hexmap reference (light street basemap, H3 hexagons in a
navy -> teal -> yellow -> orange -> red quintile ramp, red/blue points with a black
border, dark tooltip). That reference uses CARTO Positron, which now answers "API key
required"; the user asked for a free source instead (2026-11-17), so the canvas draws
the Esri World Light Gray tiles (no key): the base under the hexagons, the street and
place names over them. The tiles are the only network use; no library or CDN is loaded
and without internet the data still works on a plain background. Hexagon resolution
follows the zoom (6 region, 7 city, 8 neighbourhood). Sidebar fonts, tokens and logo
are embedded (skill brand-guidelines-kin).

Navigation is built for field and sales teams: pick a province or a city and the map
flies there; any filter can be framed with one click; small selections show their
points right away; keyboard and touch (pinch) work.

Two audiences, same map: "bottler" shows names (prospects and clients); "ko" shows no
name of any point or client.
"""

import json
from typing import Any

import h3
import polars as pl

from cleaning_agent.adapters.brand import LOGO_FORMAL_DARK, PAGE_CSS, KinBrand
from cleaning_agent.domain.gold_package import canonical_names
from cleaning_agent.domain.models import ClientColumns

CATEGORICAL = (
    ("prioridad", "Prioridad (área · existencia)"),
    ("area", "Área (300 m de un cliente)"),
    ("probability_existence_cat", "Existencia"),
    ("pop_density", "Densidad de población"),
    ("car_mobility", "Movilidad en auto"),
    ("walk_mobility", "Movilidad a pie"),
)
NUMERIC = (
    ("dist_to_main_road", "Distancia a vía principal"),
    ("dist_to_bus_stop", "Distancia a parada de bus"),
)


def _codes(series: pl.Series) -> tuple[list[int], list[str]]:
    values = series.fill_null("").cast(pl.Utf8).to_list()
    uniq = sorted(set(values))
    index = {v: i for i, v in enumerate(uniq)}
    return [index[v] for v in values], uniq


def _canonical(series: pl.Series) -> pl.Series:
    values = series.fill_null("").cast(pl.Utf8).to_list()
    names = canonical_names(values)
    return pl.Series(series.name, [names[v] for v in values])


# Colours of the map canvas only, from the team's kin-hexmap skill (user decision
# 2026-11-17: "solo mapa"); the sidebar, fonts and logo stay on the Kin brand.
MAP_PALETTE: dict[str, Any] = {
    # One colour per quintile of prospects per hexagon, fewest -> most
    "hex": ["#0d3b66", "#2DE1C2", "#E5FF01", "#FF9F45", "#e5484d"],
    "hex_opacity": 0.62,
    "background": "#eef0f2",
    "outline": "#141417",
    "high": "#e5484d",
    "moderate": "#2b7fff",
    "low": "#999EA6",
    "client": "#141417",
    "density": "#0d3b66",
}

# H3 resolution per zoom band of the map: region, city, neighbourhood
MAP_RESOLUTIONS = (6, 7, 8, 9)


def _cells_at(prospects: pl.DataFrame, res: int) -> list[str]:
    """Each prospect's H3 cell at ``res``, from the package's hex_7/hex_8 columns."""
    if f"hex_{res}" in prospects.columns:
        return [str(c) for c in prospects.get_column(f"hex_{res}").to_list()]
    return [
        h3.cell_to_parent(str(c), res) for c in prospects.get_column("hex_7").to_list()
    ]


def _grid(
    cells: list[str], client_lat: list[float], client_lon: list[float], res: int
) -> dict[str, Any]:
    """One resolution: prospect -> cell index, cell outlines, client -> cell (or -1)."""
    ids = sorted(set(cells))
    index = {c: i for i, c in enumerate(ids)}
    return {
        "r": res,
        "hex": [index[c] for c in cells],
        "cells": [
            [[round(a, 5), round(b, 5)] for a, b in h3.cell_to_boundary(c)] for c in ids
        ],
        # Only a count per cell reaches the tooltip, never a client's data
        "clients": [
            index.get(h3.latlng_to_cell(a, b, res), -1)
            for a, b in zip(client_lat, client_lon, strict=True)
        ],
    }


def _es(n: int) -> str:
    """Spanish thousands separator: 46812 -> 46.812, as the map's own counters."""
    return f"{n:,}".replace(",", ".")


def map_prospects(prospects: pl.DataFrame) -> pl.DataFrame:
    """Prospects the map draws: with city, province and a score above 0.

    User decision 2026-11-17: a point without its place or without a priorización
    score has nothing to show in the selectors or the tooltip, so the map leaves it
    out. The package CSVs keep every row; only the map is affected.
    """
    filled = [
        pl.col(c).cast(pl.Utf8).str.strip_chars().fill_null("") != ""
        for c in ("city", "state")
    ]
    score = pl.col("weighted_combined_score").cast(pl.Float64, strict=False)
    return prospects.filter(*filled, score.fill_null(0) > 0)


def _payload(
    prospects: pl.DataFrame,
    clients: pl.DataFrame,
    territory: list[list[list[float]]],
    audience: str,
    columns: ClientColumns,
) -> dict[str, Any]:
    lat = prospects.get_column("latitude").cast(pl.Float64).round(5).to_list()
    lon = prospects.get_column("longitude").cast(pl.Float64).round(5).to_list()
    client_lat = clients.get_column("_lat").to_list()
    client_lon = clients.get_column("_lon").to_list()
    cats, u_cats = _codes(prospects.get_column("business_category"))
    # One entry per place in the selectors, whatever spelling Dataplor used
    cities, u_cities = _codes(_canonical(prospects.get_column("city")))
    states, u_states = _codes(_canonical(prospects.get_column("state")))
    data: dict[str, Any] = {
        "lat": lat,
        "lon": lon,
        "cat": cats,
        "uCat": u_cats,
        "city": cities,
        "uCity": u_cities,
        "state": states,
        "uState": u_states,
        "score": prospects.get_column("weighted_combined_score")
        .cast(pl.Float64, strict=False)
        .round(3)
        .to_list(),
        "res": [
            _grid(_cells_at(prospects, r), client_lat, client_lon, r)
            for r in MAP_RESOLUTIONS
        ],
        "xcat": [],
        "xnum": [],
        "territory": territory,
        "cLat": clients.get_column("_lat").round(5).to_list(),
        "cLon": clients.get_column("_lon").round(5).to_list(),
        "names": [],
        "cNames": [],
    }
    for key, label in CATEGORICAL:
        if key in prospects.columns:
            codes, uniq = _codes(prospects.get_column(key))
            data["xcat"].append(
                {"key": key, "label": label, "codes": codes, "uniq": uniq}
            )
    for key, label in NUMERIC:
        if key in prospects.columns:
            values = (
                prospects.get_column(key)
                .cast(pl.Float64, strict=False)
                .fill_null(0)
                .round(0)
                .cast(pl.Int64)
                .to_list()
            )
            data["xnum"].append(
                {"key": key, "label": label, "vals": values, "max": max(values or [0])}
            )
    if audience == "bottler":
        # Names only in the bottler's own map; the KO map carries no name at all
        data["names"] = prospects.get_column("name").fill_null("").to_list()
        name_column = next((c for c in columns.reference if "name" in c.lower()), None)
        if name_column and name_column in clients.columns:
            data["cNames"] = clients.get_column(name_column).fill_null("").to_list()
    return data


MAP_CSS = """
html,body{height:100%}
body{display:flex;background:var(--ka-color-black);color:var(--ka-color-white);overflow:hidden}
#side{width:22rem;flex:none;overflow-y:auto;padding:1.25rem 1.25rem 2rem;background:var(--ka-color-gray-4)}
#side .kin-logo{height:1.5rem;margin-bottom:1.25rem}
#side h1{font-family:var(--ka-font-display);font-size:var(--ka-size-h3);font-weight:var(--ka-weight-bold);margin:.25rem 0 .25rem;line-height:var(--ka-lh-tight)}
#side .sub{color:var(--ka-color-gray-3);font-size:var(--ka-size-caption);margin:0 0 1rem}
.eyebrow{font-size:var(--ka-size-overline);letter-spacing:var(--ka-tracking-eyebrow);text-transform:uppercase;color:var(--ka-color-yellow);font-weight:var(--ka-weight-semibold)}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:.5rem;margin-bottom:.75rem}
.stat{background:var(--ka-color-black);border-radius:var(--ka-radius-box);padding:.75rem}
.stat .num{font-family:var(--ka-font-display);font-size:var(--ka-size-h3);font-weight:var(--ka-weight-bold)}
.stat .num.key{color:var(--ka-color-yellow)}
.stat .lbl{font-size:var(--ka-size-caption);color:var(--ka-color-gray-3)}
.sec{font-family:var(--ka-font-display);font-weight:var(--ka-weight-medium);margin:1.25rem 0 .5rem;padding-left:.5rem;border-left:.25rem solid var(--ka-color-yellow)}
label.f{display:block;font-size:var(--ka-size-caption);color:var(--ka-color-gray-3);margin:.75rem 0 .25rem}
.chips{display:flex;flex-wrap:wrap;gap:.25rem}
.chip{cursor:pointer;border:.0625rem solid var(--ka-color-gray-3);border-radius:var(--ka-radius-pill);padding:.125rem .5rem;font-size:var(--ka-size-caption);user-select:none}
.chip:hover{border-color:var(--ka-color-white)}
.chip.on{background:var(--ka-color-yellow);color:var(--ka-color-black);border-color:var(--ka-color-yellow)}
input.txt,select.sel{width:100%;background:var(--ka-color-black);color:var(--ka-color-white);border:.0625rem solid var(--ka-color-gray-3);border-radius:var(--ka-radius-base);padding:.5rem;font-family:var(--ka-font-body);font-size:var(--ka-size-caption)}
select.sel:focus,input.txt:focus{outline:.125rem solid var(--ka-color-yellow);outline-offset:0}
input[type=range]{width:100%;accent-color:var(--ka-color-yellow)}
.row{display:flex;align-items:center;gap:.5rem;font-size:var(--ka-size-caption);margin:.25rem 0}
.dot{width:.75rem;height:.75rem;border-radius:50%;display:inline-block;border:.125rem solid var(--ka-color-black)}
.sq{width:.75rem;height:.75rem;display:inline-block;background:var(--ka-color-yellow)}
.toggle{margin-left:auto;cursor:pointer;flex:none;width:2.125rem;height:1.125rem;border-radius:var(--ka-radius-pill);background:var(--ka-color-black);position:relative}
.toggle::after{content:'';position:absolute;top:.1875rem;left:.1875rem;width:.75rem;height:.75rem;border-radius:50%;background:var(--ka-color-gray-3);transition:left .15s}
.toggle.on{background:var(--ka-color-yellow)}.toggle.on::after{left:1.1875rem;background:var(--ka-color-black)}
#layers .row{margin:.5rem 0}
.seg{display:flex;background:var(--ka-color-black);border-radius:var(--ka-radius-pill);padding:.1875rem;gap:.125rem}
.seg span{flex:1;text-align:center;cursor:pointer;border-radius:var(--ka-radius-pill);padding:.3125rem .25rem;font-size:var(--ka-size-caption);color:var(--ka-color-gray-2);user-select:none}
.seg span:hover{color:var(--ka-color-white)}
.seg span.on{background:var(--ka-color-yellow);color:var(--ka-color-black);font-weight:var(--ka-weight-semibold)}
.help{color:var(--ka-color-gray-3);font-size:var(--ka-size-caption);margin:.375rem 0 0;line-height:1.4}
#legend{position:absolute;right:1rem;bottom:1.75rem;width:15rem;background:rgba(20,20,23,.94);color:var(--ka-color-white);border:.0625rem solid rgba(255,255,255,.08);border-radius:.75rem;padding:.75rem .875rem;font-size:var(--ka-size-caption)}
#legend .lh{display:flex;align-items:center;justify-content:space-between;cursor:pointer;font-family:var(--ka-font-display);font-weight:var(--ka-weight-bold);font-size:.8125rem}
#legend .lh small{font-family:var(--ka-font-body);font-weight:400;color:var(--ka-color-gray-3)}
#legend .lt{font-size:.6875rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ka-color-gray-3);margin:.625rem 0 .3125rem}
#legend .lr{display:grid;grid-template-columns:1.375rem 1fr auto;align-items:center;gap:.5rem;margin:.1875rem 0}
#legend .sw{width:1.375rem;height:.75rem;border-radius:.1875rem}
#legend .v{font-family:var(--ka-font-display);font-variant-numeric:tabular-nums;text-align:right}
#legend .n{color:var(--ka-color-gray-3);font-variant-numeric:tabular-nums}
#legend .pd{width:.75rem;height:.75rem;border-radius:50%;border:.0625rem solid var(--ka-color-black);justify-self:center}
#legend .cs{width:.6875rem;height:.6875rem;border:.0625rem solid var(--ka-color-white);justify-self:center}
#legend.min .body{display:none}
#tip .sw{display:inline-block;width:.625rem;height:.625rem;border-radius:.125rem;margin-right:.375rem;vertical-align:baseline}
.actions{display:flex;gap:.5rem;margin:.5rem 0 0}
.btn{flex:1;cursor:pointer;border-radius:var(--ka-radius-base);padding:.5rem;font-family:var(--ka-font-body);font-size:var(--ka-size-caption);font-weight:var(--ka-weight-semibold);border:.0625rem solid var(--ka-color-gray-3);background:var(--ka-color-black);color:var(--ka-color-white)}
.btn.primary{background:var(--ka-color-yellow);color:var(--ka-color-black);border-color:var(--ka-color-yellow)}
.btn:hover{border-color:var(--ka-color-white)}
#active{font-size:var(--ka-size-caption);color:var(--ka-color-gray-2);margin:.5rem 0 0;min-height:1rem}
#wrap{position:relative;flex:1;touch-action:none}
canvas{display:block;width:100%;height:100%;cursor:grab}
#tip,#pop{position:absolute;pointer-events:none;background:rgba(20,20,23,.96);color:var(--ka-color-white);border:.0625rem solid rgba(255,255,255,.08);border-radius:.5rem;padding:.5rem .75rem;font-size:var(--ka-size-caption);display:none;max-width:20rem}
#tip{padding:.75rem .875rem;min-width:16rem}
#tip .tt-h{font-family:var(--ka-font-display);font-weight:var(--ka-weight-bold);margin-bottom:.5rem}
#tip .tt{display:grid;grid-template-columns:1fr auto;gap:.25rem 1.25rem}
#tip .v{text-align:right;font-family:var(--ka-font-display);font-variant-numeric:tabular-nums}
#tip .key{color:var(--ka-color-yellow)}
#tip .tt-f{margin-top:.5rem;color:var(--ka-color-gray-3)}
#osm{position:absolute;right:0;bottom:0;background:var(--ka-color-white);color:var(--ka-color-black);opacity:.85;font-size:.6875rem;padding:.125rem .5rem;border-top-left-radius:var(--ka-radius-base)}
#pop{pointer-events:auto;box-shadow:0 .25rem 1rem var(--ka-color-black)}
#pop .nm{font-family:var(--ka-font-display);font-weight:var(--ka-weight-bold);margin-bottom:.25rem;padding-right:1.25rem}
#pop .x{position:absolute;right:.375rem;top:.25rem;cursor:pointer;color:var(--ka-color-gray-3)}
#crumb{position:absolute;left:1rem;top:1rem;background:var(--ka-color-gray-4);border-radius:var(--ka-radius-pill);padding:.375rem .875rem;font-size:var(--ka-size-caption);color:var(--ka-color-gray-2)}
#crumb b{color:var(--ka-color-yellow);font-weight:var(--ka-weight-semibold)}
#zoom{position:absolute;right:1rem;top:1rem;z-index:2;display:flex;flex-direction:column;gap:.25rem}
#zoom button{width:2.25rem;height:2.25rem;background:var(--ka-color-gray-4);color:var(--ka-color-white);border:.0625rem solid var(--ka-color-gray-3);border-radius:var(--ka-radius-base);cursor:pointer;font-size:var(--ka-size-body)}
#zoom button:hover{border-color:var(--ka-color-yellow)}
#hint{position:absolute;left:50%;bottom:1.75rem;transform:translateX(-50%);background:var(--ka-color-gray-4);padding:.375rem .875rem;border-radius:var(--ka-radius-pill);font-size:var(--ka-size-caption);color:var(--ka-color-gray-2)}
.ka-site{color:var(--ka-color-gray-3)}
@media (max-width:48rem){body{flex-direction:column}#side{width:auto;max-height:45vh}}
"""

MAP_JS = r"""
const tok=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const K={y:tok('--ka-color-yellow'),b:tok('--ka-color-black'),w:tok('--ka-color-white'),g1:tok('--ka-color-gray-1'),g2:tok('--ka-color-gray-2'),g3:tok('--ka-color-gray-3'),g4:tok('--ka-color-gray-4')};
// Hexagon classes on the light basemap: five steps of Black, Kin Yellow for the top class
const N=D.lat.length,POINT_ZOOM=12.5,FEW_POINTS=6000;
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
// 8574 -> 8.574 (the 'es' locale leaves 4-digit numbers ungrouped)
const fmt=n=>String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g,'.');
const $=id=>document.getElementById(id);
const num2=v=>v.toFixed(2).replace('.',',');
const cv=$('cv'),ctx=cv.getContext('2d'),tip=$('tip'),pop=$('pop');
// Web Mercator in "world pixels" at zoom 0 (256 px world), the same grid as the XYZ tiles
const px=lon=>(lon+180)/360*256,py=lat=>{const s=Math.sin(lat*Math.PI/180);return (0.5-Math.log((1+s)/(1-s))/(4*Math.PI))*256};
const X=Float64Array.from(D.lon,px),Y=Float64Array.from(D.lat,py);
const CX=Float64Array.from(D.cLon,px),CY=Float64Array.from(D.cLat,py);
// One H3 grid per resolution: 6 at regional scale, 7 at city scale, 8 at neighbourhood scale
const RES=D.res.map(R=>{const cells=R.cells.map(r=>r.map(([la,lo])=>[px(lo),py(la)]));
  const cc=cells.map(r=>[r.reduce((s,p)=>s+p[0],0)/r.length,r.reduce((s,p)=>s+p[1],0)/r.length]);
  const w=cells.length?Math.max(...cells[0].map(p=>p[0]))-Math.min(...cells[0].map(p=>p[0])):0;
  const clients=new Map();R.clients.forEach(c=>{if(c>=0)clients.set(c,(clients.get(c)||0)+1)});
  return {r:R.r,hex:R.hex,cells,cc,w,clients}});
// 'auto' follows the zoom (6 region, 7 city, 8 neighbourhood); a chip fixes one resolution
let resMode='auto';
const resFor=z=>resMode!=='auto'?resMode:z<10?0:z<12?1:2;
const TERR=D.territory.map(r=>r.map(([la,lo])=>[px(lo),py(la)]));
let view={x:128,y:128,z:4},W=0,H=0,dpr=1,anim=null;
const sx=x=>(x-view.x)*2**view.z+W/2,sy=y=>(y-view.y)*2**view.z+H/2;
const wx=x=>(x-W/2)/2**view.z+view.x,wy=y=>(y-H/2)/2**view.z+view.y;

// ---- basemap: Esri World Light Gray raster tiles, free and keyless (the only network use)
const tiles=new Map();let tileFrame=0,tilesOk=0,tilesBad=0;
const tileUrl=(lay,z,x,y)=>`https://server.arcgisonline.com/ArcGIS/rest/services/${lay}/MapServer/tile/${z}/${y}/${x}`;
function tile(lay,z,x,y){const k=lay+'/'+z+'/'+x+'/'+y;let t=tiles.get(k);
  if(!t){if(tiles.size>900)tiles.delete(tiles.keys().next().value);t=new Image();t.ok=false;
    t.onload=()=>{t.ok=true;tilesOk++;if(!tileFrame)tileFrame=requestAnimationFrame(()=>{tileFrame=0;draw()})};
    t.onerror=()=>{tilesBad++;if(!tilesOk&&tilesBad>6)$('osm').textContent='Sin conexión: el mapa base no cargó (los datos siguen completos)'};
    t.src=tileUrl(lay,z,x,y);tiles.set(k,t)}return t}
const TILE_MAX_Z=16; // the Light Gray canvas stops at level 16: deeper zooms stretch it
function drawTiles(lay){const tz=Math.max(0,Math.min(TILE_MAX_Z,Math.round(view.z))),n=2**tz,ts=256/n,size=ts*2**view.z+.5;
  const x0=Math.floor(wx(0)/ts),x1=Math.floor(wx(W)/ts),y0=Math.max(0,Math.floor(wy(0)/ts)),y1=Math.min(n-1,Math.floor(wy(H)/ts));
  for(let ty=y0;ty<=y1;ty++)for(let tx=x0;tx<=x1;tx++){const ux=((tx%n)+n)%n,X0=sx(tx*ts),Y0=sy(ty*ts),t=tile(lay,tz,ux,ty);
    if(t.ok){ctx.drawImage(t,X0,Y0,size,size);continue}
    // While a tile loads, stretch the closest loaded parent so the map never flashes blank
    for(let d=1;d<=5&&tz-d>=0;d++){const f=2**d,p=tiles.get(lay+'/'+(tz-d)+'/'+Math.floor(ux/f)+'/'+Math.floor(ty/f));
      if(p&&p.ok){const s=p.naturalWidth/f;ctx.drawImage(p,(ux%f)*s,(ty%f)*s,s,s,X0,Y0,size,size);break}}}}

// ---- framing: robust bounds (2-98 percentile) so one stray point never zooms out
function quantile(a,q){if(!a.length)return 0;const s=Float64Array.from(a).sort();return s[Math.min(s.length-1,Math.max(0,Math.floor(q*(s.length-1))))]}
function boundsOf(idx){if(!idx.length)return null;const xs=idx.map(i=>X[i]),ys=idx.map(i=>Y[i]);
  const lo=idx.length>50?.02:0,hi=idx.length>50?.98:1;return [quantile(xs,lo),quantile(ys,lo),quantile(xs,hi),quantile(ys,hi)]}
function targetFor(b){const w=Math.max(b[2]-b[0],2e-4),h=Math.max(b[3]-b[1],2e-4);
  const z=Math.min(16,Math.max(2,Math.log2(Math.min((W*.85)/w,(H*.85)/h))));return {x:(b[0]+b[2])/2,y:(b[1]+b[3])/2,z}}
function flyTo(t,ms=650){cancelAnimationFrame(anim);const s={...view},t0=performance.now();pop.style.display='none';tip.style.display='none';
  const ease=k=>k<.5?2*k*k:1-Math.pow(-2*k+2,2)/2;
  const step=now=>{const k=Math.min(1,(now-t0)/ms),e=ease(k);view.x=s.x+(t.x-s.x)*e;view.y=s.y+(t.y-s.y)*e;view.z=s.z+(t.z-s.z)*e;draw();if(k<1)anim=requestAnimationFrame(step)};
  anim=requestAnimationFrame(step)}
const ALL=[...Array(N).keys()];
const fitAll=(ms)=>{const b=boundsOf(ALL);if(b)flyTo(targetFor(b),ms)};
const fitVisible=()=>{const b=boundsOf(vis);if(b)flyTo(targetFor(b));};

// ---- filters
const fX=D.xcat.map(()=>new Set()),fMax=D.xnum.map(x=>x.max);let fCat=-1,fCity=-1,fState=-1,fText='';
function visible(i){
  if(fState>=0&&D.state[i]!==fState)return false;if(fCity>=0&&D.city[i]!==fCity)return false;if(fCat>=0&&D.cat[i]!==fCat)return false;
  for(let k=0;k<D.xcat.length;k++)if(fX[k].size&&!fX[k].has(D.xcat[k].codes[i]))return false;
  for(let k=0;k<D.xnum.length;k++)if(fMax[k]<D.xnum[k].max&&D.xnum[k].vals[i]>fMax[k])return false;
  if(fText&&!(D.names[i]||'').toLowerCase().includes(fText)&&!D.uCat[D.cat[i]].toLowerCase().includes(fText))return false;
  return true}
let vis=[],hexCount=RES.map(()=>new Map()),hexScore=RES.map(()=>new Map()),breaks=RES.map(()=>[1,2,3,4]),ptBreaks=[0,0,0,0],hover=-1;
// What colours the hexagons and the points: the priorización score by default
let hexMetric='score',ptMetric='exist';
const hexValue=(k,c)=>hexMetric==='score'?hexScore[k].get(c)/hexCount[k].get(c):hexCount[k].get(c);
const quint=v=>{v.sort((a,b)=>a-b);return v.length?[.2,.4,.6,.8].map(q=>v[Math.min(v.length-1,Math.floor(q*v.length))]):[0,0,0,0]};
function rebreak(){breaks=hexCount.map((m,k)=>quint([...m.keys()].map(c=>hexValue(k,c))));ptBreaks=quint(vis.map(i=>D.score[i]))}
function refilter(){vis=[];hexCount=RES.map(()=>new Map());hexScore=RES.map(()=>new Map());
  for(let i=0;i<N;i++)if(visible(i)){vis.push(i);const s=D.score[i]||0;RES.forEach((R,k)=>{const c=R.hex[i];hexCount[k].set(c,(hexCount[k].get(c)||0)+1);hexScore[k].set(c,(hexScore[k].get(c)||0)+s)})}
  rebreak();hover=-1;tip.style.display='none';$('st-vis').textContent=fmt(vis.length);if(typeof updateLegend==='function')updateLegend();updateCrumb();updateActive();draw()}
const classOf=(v,b)=>{for(let i=0;i<4;i++)if(v<=b[i])return i;return 4};
const hexClass=(v,k)=>classOf(v,breaks[k]);
const ptColor=i=>ptMetric==='score'?P.hex[classOf(D.score[i],ptBreaks)]:existColor(i);
const layers={base:true,hex:true,points:true,clients:D.cLat.length>0,territory:D.territory.length>0};
const xcat=key=>D.xcat.find(x=>x.key===key);
const EXIST=xcat('probability_existence_cat'),AREA=xcat('area');
const existColor=i=>{if(!EXIST)return P.high;const v=EXIST.uniq[EXIST.codes[i]];return v==='high'?P.high:v==='moderate'?P.moderate:P.low};
const showPoints=()=>view.z>=POINT_ZOOM||vis.length<=FEW_POINTS;

// ---- drawing
function path(r){ctx.beginPath();r.forEach(([x,y],j)=>j?ctx.lineTo(sx(x),sy(y)):ctx.moveTo(sx(x),sy(y)));ctx.closePath()}
function draw(){
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle=P.background;ctx.fillRect(0,0,W,H);
  if(layers.base)drawTiles('Canvas/World_Light_Gray_Base');
  if(layers.territory&&TERR.length){
    // Outside the territory is slightly dimmed; inside the basemap stays clean
    ctx.beginPath();ctx.rect(0,0,W,H);TERR.forEach(r=>r.forEach(([x,y],j)=>j?ctx.lineTo(sx(x),sy(y)):ctx.moveTo(sx(x),sy(y))));
    ctx.fillStyle=P.outline;ctx.globalAlpha=.07;ctx.fill('evenodd');ctx.globalAlpha=1;
    ctx.strokeStyle=P.outline;ctx.lineWidth=1.5;TERR.forEach(r=>{path(r);ctx.stroke()})}
  const pts=showPoints(),k=resFor(view.z),R=RES[k],hexPx=R.w*2**view.z,near=pts&&view.z>=POINT_ZOOM;
  if(k!==legendK)updateLegend();
  // At country scale a cell is smaller than a pixel: density dots instead of an empty map
  if(layers.hex&&hexPx<3&&!pts){ctx.fillStyle=P.density;ctx.globalAlpha=.6;for(const i of vis){const x=sx(X[i]),y=sy(Y[i]);if(x<0||y<0||x>W||y>H)continue;ctx.fillRect(x-1,y-1,2.5,2.5)}ctx.globalAlpha=1}
  else if(layers.hex){const pad=hexPx+20;
    hexCount[k].forEach((n,c)=>{const x0=sx(R.cc[c][0]),y0=sy(R.cc[c][1]);if(x0<-pad||y0<-pad||x0>W+pad||y0>H+pad)return;
      // Near street level the points carry the detail: hexagons fade so the streets stay readable
      const cls=hexClass(hexValue(k,c),k);path(R.cells[c]);ctx.fillStyle=P.hex[cls];ctx.globalAlpha=near?P.hex_opacity*.45:P.hex_opacity;ctx.fill();
      ctx.globalAlpha=.45;ctx.strokeStyle=P.hex[cls];ctx.lineWidth=.4;ctx.stroke()});ctx.globalAlpha=1;
    if(hover>=0&&hexCount[k].has(hover)){path(R.cells[hover]);ctx.strokeStyle=K.b;ctx.lineWidth=2.5;ctx.stroke();ctx.strokeStyle=K.w;ctx.lineWidth=1.25;ctx.stroke()}}
  // Street and place names stay readable above the hexagons
  if(layers.base)drawTiles('Canvas/World_Light_Gray_Reference');
  $('hint').style.display=pts||!vis.length?'none':'block';
  // Current clients: dark squares, so they never read as a prospect
  if(view.z>=POINT_ZOOM&&layers.clients){ctx.fillStyle=P.client;ctx.strokeStyle=K.w;ctx.lineWidth=1;for(let i=0;i<CX.length;i++){const x=sx(CX[i]),y=sy(CY[i]);if(x<0||y<0||x>W||y>H)continue;ctx.fillRect(x-3.5,y-3.5,7,7);ctx.strokeRect(x-3.5,y-3.5,7,7)}}
  if(pts&&layers.points){ctx.strokeStyle=K.b;ctx.lineWidth=1;ctx.globalAlpha=.95;const r=view.z>=POINT_ZOOM?5:3.5;for(const i of vis){const x=sx(X[i]),y=sy(Y[i]);if(x<0||y<0||x>W||y>H)continue;ctx.fillStyle=ptColor(i);ctx.beginPath();ctx.arc(x,y,r,0,7);ctx.fill();ctx.stroke()}ctx.globalAlpha=1}
}
function resize(){const r=cv.parentElement.getBoundingClientRect();dpr=window.devicePixelRatio||1;W=r.width;H=r.height;cv.width=W*dpr;cv.height=H*dpr;draw()}

// ---- interaction: mouse, wheel, touch (pinch), keyboard
function zoomAt(f,mx,my){cancelAnimationFrame(anim);const ax=wx(mx),ay=wy(my);view.z=Math.min(18,Math.max(2,view.z+f));view.x=ax-(mx-W/2)/2**view.z;view.y=ay-(my-H/2)/2**view.z;pop.style.display='none';tip.style.display='none';draw()}
const pointers=new Map();let drag=null,pinch=null;
const local=e=>{const r=cv.getBoundingClientRect();return [e.clientX-r.left,e.clientY-r.top]};
cv.addEventListener('pointerdown',e=>{cv.setPointerCapture(e.pointerId);pointers.set(e.pointerId,local(e));cancelAnimationFrame(anim);
  if(pointers.size===1){const [mx,my]=local(e);drag={mx,my,vx:view.x,vy:view.y,moved:false};cv.style.cursor='grabbing'}
  else if(pointers.size===2){const [a,b]=[...pointers.values()];pinch={d:Math.hypot(a[0]-b[0],a[1]-b[1]),z:view.z};drag=null}});
cv.addEventListener('pointermove',e=>{if(!pointers.has(e.pointerId)){hoverAt(e);return}pointers.set(e.pointerId,local(e));
  if(pinch&&pointers.size===2){const [a,b]=[...pointers.values()];const d=Math.hypot(a[0]-b[0],a[1]-b[1]);const mx=(a[0]+b[0])/2,my=(a[1]+b[1])/2;const ax=wx(mx),ay=wy(my);
    view.z=Math.min(18,Math.max(2,pinch.z+Math.log2(d/pinch.d)));view.x=ax-(mx-W/2)/2**view.z;view.y=ay-(my-H/2)/2**view.z;draw();return}
  if(drag){const [mx,my]=local(e),dx=mx-drag.mx,dy=my-drag.my;if(Math.abs(dx)+Math.abs(dy)>4)drag.moved=true;
    if(drag.moved){view.x=drag.vx-dx/2**view.z;view.y=drag.vy-dy/2**view.z;pop.style.display='none';tip.style.display='none';draw()}}});
const endPointer=e=>{const wasDrag=drag&&!drag.moved&&pointers.size===1;pointers.delete(e.pointerId);if(pointers.size<2)pinch=null;
  if(wasDrag)clickAt(e);if(!pointers.size){drag=null;cv.style.cursor='grab'}};
cv.addEventListener('pointerup',endPointer);cv.addEventListener('pointercancel',e=>{pointers.delete(e.pointerId);pinch=null;drag=null});
cv.addEventListener('pointerleave',()=>{tip.style.display='none';if(hover>=0){hover=-1;draw()}});
cv.addEventListener('wheel',e=>{e.preventDefault();const [mx,my]=local(e);zoomAt(e.deltaY<0?.4:-.4,mx,my)},{passive:false});
cv.addEventListener('dblclick',e=>{const [mx,my]=local(e);const ax=wx(mx),ay=wy(my);flyTo({x:ax,y:ay,z:Math.min(18,view.z+1.5)},350)});
window.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT'||e.target.tagName==='SELECT')return;
  if(e.key==='+'||e.key==='=')zoomAt(1,W/2,H/2);else if(e.key==='-')zoomAt(-1,W/2,H/2);else if(e.key==='0')fitAll();else if(e.key==='Escape'){pop.style.display='none'}});
$('zin').onclick=()=>zoomAt(1,W/2,H/2);$('zout').onclick=()=>zoomAt(-1,W/2,H/2);$('zfit').onclick=()=>fitAll();

function inPoly(x,y,r){let c=false;for(let i=0,j=r.length-1;i<r.length;j=i++){const [xi,yi]=r[i],[xj,yj]=r[j];if((yi>y)!==(yj>y)&&x<(xj-xi)*(y-yi)/(yj-yi)+xi)c=!c}return c}
function hexAt(mx,my){const k=resFor(view.z),R=RES[k],x=wx(mx),y=wy(my),radius=R.w;let hit=-1;
  hexCount[k].forEach((n,c)=>{if(hit>=0)return;if(Math.abs(R.cc[c][0]-x)>radius||Math.abs(R.cc[c][1]-y)>radius)return;if(inPoly(x,y,R.cells[c]))hit=c});return hit}
// What a hexagon holds, from the visible prospects only (it follows the filters)
function hexSummary(k,c){const R=RES[k],ex={},cats=new Map(),cities=new Map();let n=0,inside=0,score=0,scored=0;
  for(const i of vis){if(R.hex[i]!==c)continue;n++;
    if(EXIST){const v=EXIST.uniq[EXIST.codes[i]]||'(sin dato)';ex[v]=(ex[v]||0)+1}
    if(AREA&&AREA.uniq[AREA.codes[i]]==='dentro')inside++;
    const s=D.score[i];if(s!==null&&!isNaN(s)){score+=s;scored++}
    cats.set(D.cat[i],(cats.get(D.cat[i])||0)+1);cities.set(D.city[i],(cities.get(D.city[i])||0)+1)}
  const top=m=>[...m.entries()].sort((a,b)=>b[1]-a[1])[0]?.[0];
  return {n,ex,inside,score:scored?score/scored:null,cat:top(cats),city:top(cities),clients:R.clients.get(c)||0}}
function hexTip(k,c){const s=hexSummary(k,c),pct=vis.length?s.n/vis.length*100:0;
  const row=(l,v,key,col)=>`<span class="${key?'key':''}">${col?`<i class="sw" style="background:${col}"></i>`:''}${l}</span><span class="${key?'key':''} v">${v}</span>`;
  // The metric that colours the hexagon comes first, with its colour
  const col=P.hex[hexClass(hexValue(k,c),k)],sc=s.score!==null?num2(s.score):'—';
  const prosp=`${fmt(s.n)} (${pct<1?pct.toFixed(1).replace('.',','):fmt(pct)}%)`;
  const rows=hexMetric==='score'?[row('Score promedio',sc,true,col),row('Prospectos visibles',prosp)]:[row('Prospectos visibles',prosp,true,col),row('Score promedio',sc)];
  if(EXIST)['high','moderate','low'].forEach(e=>rows.push(row(`Existencia ${e}`,fmt(s.ex[e]||0))));
  if(AREA){rows.push(row('A ≤300 m de un cliente',fmt(s.inside)));rows.push(row('Fuera de cobertura',fmt(s.n-s.inside)))}
  rows.push(row('Clientes actuales',fmt(s.clients)));
  if(s.cat!==undefined)rows.push(row('Categoría principal',esc(D.uCat[s.cat])));
  return `<div class="tt-h">Hexágono · resolución ${RES[k].r}${s.city!==undefined&&D.uCity[s.city]?' · '+esc(D.uCity[s.city]):''}</div><div class="tt">${rows.join('')}</div><div class="tt-f">Clic para acercar</div>`}
let hoverFrame=0;
function hoverAt(e){if(hoverFrame)return;hoverFrame=requestAnimationFrame(()=>{hoverFrame=0;const [mx,my]=local(e);
  const off=!layers.hex||showPoints()&&view.z>=POINT_ZOOM||R0px()<3;
  const c=off?-1:hexAt(mx,my);
  if(c!==hover){hover=c;draw();if(c>=0)tip.innerHTML=hexTip(resFor(view.z),c)}
  if(c<0){tip.style.display='none';cv.style.cursor='grab';return}
  cv.style.cursor='zoom-in';tip.style.display='block';
  // Flip to the other side of the cursor when the tooltip would leave the map
  const tw=tip.offsetWidth,th=tip.offsetHeight;tip.style.left=(mx+16+tw>W?Math.max(8,mx-16-tw):mx+16)+'px';tip.style.top=(my+16+th>H?Math.max(8,my-16-th):my+16)+'px'})}
const R0px=()=>RES[resFor(view.z)].w*2**view.z;
function nearestPoint(mx,my){let best=-1,bd=100;for(const i of vis){const dx=sx(X[i])-mx,dy=sy(Y[i])-my,d=dx*dx+dy*dy;if(d<bd){bd=d;best=i}}return [best,bd]}
function clickAt(e){const [mx,my]=local(e);
  if(showPoints()&&layers.points){const [best,bd]=nearestPoint(mx,my);
    let client=-1,cd=bd;if(layers.clients&&view.z>=POINT_ZOOM)for(let i=0;i<CX.length;i++){const dx=sx(CX[i])-mx,dy=sy(CY[i])-my,d=dx*dx+dy*dy;if(d<cd){cd=d;client=i}}
    if(client>=0||best>=0){showPopup(client>=0?-1:best,client,mx,my);return}}
  const k=resFor(view.z),c=layers.hex&&R0px()>=3?hexAt(mx,my):-1;
  if(c>=0){const r=RES[k].cells[c];const xs=r.map(p=>p[0]),ys=r.map(p=>p[1]);
    // One level down: res 6 -> city scale (res 7), res 7 -> neighbourhood (res 8), res 8 -> points
    const t=targetFor([Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)]);t.z=[10.75,12.75,POINT_ZOOM+1.25,POINT_ZOOM+2.5][k];flyTo(t);return}
  pop.style.display='none'}
function showPopup(best,client,mx,my){let h;tip.style.display='none';
  if(best>=0){const rows=[`Categoría: ${esc(D.uCat[D.cat[best]])}`,`Ciudad: ${esc(D.uCity[D.city[best]])} · ${esc(D.uState[D.state[best]])}`,`Score: <i class="sw" style="display:inline-block;width:.625rem;height:.625rem;border-radius:.125rem;background:${P.hex[classOf(D.score[best],ptBreaks)]}"></i> <b>${num2(D.score[best])}</b>`];
    D.xcat.forEach(x=>rows.push(`${x.label}: ${esc(x.uniq[x.codes[best]])}`));D.xnum.forEach(x=>rows.push(`${x.label}: ${fmt(x.vals[best])} m`));
    h=`<span class="x" title="Cerrar">✕</span><div class="nm">${esc(D.names[best]||D.uCat[D.cat[best]])}</div>${rows.join('<br>')}`}
  else h=`<span class="x" title="Cerrar">✕</span><div class="nm">${esc(D.cNames[client]||'Cliente actual')}</div>Cliente actual del bottler`;
  pop.innerHTML=h;pop.querySelector('.x').onclick=()=>pop.style.display='none';
  pop.style.left=Math.max(8,Math.min(mx+14,W-330))+'px';pop.style.top=Math.max(8,Math.min(my+14,H-300))+'px';pop.style.display='block'}

// ---- sidebar: location (flies there), category, chips, ranges, search
function countsOf(codes,keep){const c=new Map();for(let i=0;i<N;i++)if(keep(i))c.set(codes[i],(c.get(codes[i])||0)+1);return c}
function fillSelect(sel,uniq,counts,label){const opts=[...counts.entries()].filter(([k])=>uniq[k]).sort((a,b)=>b[1]-a[1]);
  sel.innerHTML=`<option value="-1">${label} (${fmt(opts.reduce((s,o)=>s+o[1],0))})</option>`+opts.map(([k,n])=>`<option value="${k}">${esc(uniq[k]||'(sin dato)')} · ${fmt(n)}</option>`).join('')}
const selState=$('f-state'),selCity=$('f-city'),selCat=$('f-cat');
function refreshCities(){fillSelect(selCity,D.uCity,countsOf(D.city,i=>fState<0||D.state[i]===fState),'Todas las ciudades');selCity.value=String(fCity)}
fillSelect(selState,D.uState,countsOf(D.state,()=>true),'Todas las provincias');refreshCities();
fillSelect(selCat,D.uCat,countsOf(D.cat,()=>true),'Todas las categorías');
selState.onchange=()=>{fState=+selState.value;fCity=-1;refreshCities();refilter();fState>=0?fitVisible():fitAll()};
selCity.onchange=()=>{fCity=+selCity.value;if(fCity>=0&&fState<0){const i=D.city.indexOf(fCity);fState=D.state[i];selState.value=String(fState);refreshCities();selCity.value=String(fCity)}
  refilter();fCity>=0?fitVisible():(fState>=0?fitVisible():fitAll())};
selCat.onchange=()=>{fCat=+selCat.value;refilter()};
function chips(title,uniq,set){const b=document.createElement('div');b.innerHTML=`<label class="f">${esc(title)}</label>`;const c=document.createElement('div');c.className='chips';
  uniq.forEach((u,j)=>{if(!u)return;const ch=document.createElement('span');ch.className='chip';ch.textContent=u||'(vacío)';ch.onclick=()=>{set.has(j)?set.delete(j):set.add(j);ch.classList.toggle('on');refilter()};c.appendChild(ch)});b.appendChild(c);return b}
const F=$('filters');
D.xcat.forEach((x,k)=>F.appendChild(chips(x.label,x.uniq,fX[k])));
D.xnum.forEach((x,k)=>{const b=document.createElement('div');b.innerHTML=`<label class="f">${x.label}: <span>todas</span></label><input type="range" min="0" max="${x.max}" step="10" value="${x.max}">`;
  b.querySelector('input').oninput=e=>{fMax[k]=+e.target.value;b.querySelector('span').textContent=fMax[k]>=x.max?'todas':`≤ ${fmt(fMax[k])} m`;refilter()};F.appendChild(b)});
let searchTimer=0;$('search').oninput=e=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{fText=e.target.value.trim().toLowerCase();refilter()},180)};
$('b-fit').onclick=()=>fitVisible();
$('b-clear').onclick=()=>{fState=fCity=fCat=-1;fText='';$('search').value='';selState.value='-1';selCat.value='-1';refreshCities();
  fX.forEach(s=>s.clear());document.querySelectorAll('#filters .chip.on').forEach(c=>c.classList.remove('on'));
  D.xnum.forEach((x,k)=>{fMax[k]=x.max});document.querySelectorAll('#filters input[type=range]').forEach((r,k)=>{r.value=D.xnum[k].max;r.previousElementSibling.querySelector('span').textContent='todas'});
  refilter();fitAll()};
function updateCrumb(){const parts=['Territorio'];if(fState>=0)parts.push(D.uState[fState]);if(fCity>=0)parts.push(D.uCity[fCity]);
  $('crumb').innerHTML=parts.map(esc).join(' › ')+` · <b>${fmt(vis.length)}</b> prospectos`}
function updateActive(){const n=(fState>=0)+(fCity>=0)+(fCat>=0)+(fText?1:0)+fX.reduce((s,x)=>s+(x.size?1:0),0)+fMax.reduce((s,m,k)=>s+(m<D.xnum[k].max?1:0),0);
  $('active').textContent=n?`${n} filtro${n>1?'s':''} activo${n>1?'s':''}`:'Sin filtros: todo el territorio'}
const LAY=[['base','Mapa base (calles y lugares)'],['hex','Hexágonos'],['points','Prospectos'],['clients',`Clientes actuales (${fmt(D.cLat.length)})`],['territory','Territorio']].filter(([k])=>k!=='territory'||D.territory.length);
$('layers').innerHTML=LAY.map(([k,t])=>`<div class="row"><span>${t}</span><span class="toggle${layers[k]?' on':''}" data-k="${k}" role="switch" aria-label="${t}"></span></div>`).join('');
document.querySelectorAll('.toggle').forEach(t=>t.onclick=()=>{const k=t.dataset.k;layers[k]=!layers[k];t.classList.toggle('on');
  if(k==='base')$('osm').style.display=layers.base?'block':'none';draw()});
$('st-total').textContent=fmt(N);
function seg(id,opts,get,set){const box=$(id);opts.forEach(([v,t,help])=>{const o=document.createElement('span');o.textContent=t;if(help)o.title=help;if(get()===v)o.className='on';
  o.onclick=()=>{set(v);box.querySelectorAll('span').forEach(x=>x.classList.remove('on'));o.classList.add('on');hover=-1;tip.style.display='none';rebreak();updateLegend();draw()};box.appendChild(o)})}
seg('seg-hex',[['score','Score promedio','Promedio del score de priorización de los prospectos del hexágono'],['count','N.º de prospectos','Cantidad de prospectos visibles en el hexágono']],()=>hexMetric,v=>{hexMetric=v});
seg('seg-pt',[['exist','Existencia'],['score','Score']],()=>ptMetric,v=>{ptMetric=v});
seg('seg-res',[['auto','Auto','La resolución sigue el zoom: 6 región, 7 ciudad, 8 barrio'],[0,'6'],[1,'7'],[2,'8'],[3,'9']],()=>resMode,v=>{resMode=v});
// Floating legend: the colour scale with the real value ranges of what is on screen
let legendK=-1;
function rangeText(b,i,isInt){const f=isInt?(v=>fmt(v)):num2;const lo=i?b[i-1]:null,hi=i<4?b[i]:null;
  if(lo===null)return `≤ ${f(hi)}`;if(hi===null)return `> ${f(lo)}`;if(isInt&&Math.floor(lo)+1>=hi)return f(hi);return `${isInt?f(Math.floor(lo)+1):f(lo)} – ${f(hi)}`}
function updateLegend(){const k=resFor(view.z);legendK=k;const isInt=hexMetric==='count',b=breaks[k];
  const cnt=[0,0,0,0,0];hexCount[k].forEach((n,c)=>cnt[hexClass(hexValue(k,c),k)]++);
  const title=hexMetric==='score'?'Score promedio':'Prospectos por hexágono';
  let h=`<div class="lh"><span>${title}</span><small>H3 res ${RES[k].r}${resMode==='auto'?' · auto':''} ▾</small></div><div class="body">`;
  h+=`<div class="lt">Hexágonos (quintiles · n.º de hexágonos)</div>`;
  for(let i=4;i>=0;i--)h+=`<div class="lr"><span class="sw" style="background:${P.hex[i]};opacity:${P.hex_opacity+.2}"></span><span class="v">${rangeText(b,i,isInt)}</span><span class="n">${fmt(cnt[i])}</span></div>`;
  h+=`<div class="lt">Prospectos (puntos)</div>`;
  if(ptMetric==='score')for(let i=4;i>=0;i--)h+=`<div class="lr"><span class="pd" style="background:${P.hex[i]}"></span><span class="v">${rangeText(ptBreaks,i,false)}</span><span></span></div>`;
  else [['high','Existencia high'],['moderate','Existencia moderate'],['low','Existencia low']].forEach(([e,t])=>{h+=`<div class="lr"><span class="pd" style="background:${P[e]}"></span><span>${t}</span><span></span></div>`});
  if(D.cLat.length)h+=`<div class="lr"><span class="cs" style="background:${P.client}"></span><span>Cliente actual del bottler</span><span></span></div>`;
  $('legend').innerHTML=h+'</div>';$('legend').querySelector('.lh').onclick=()=>$('legend').classList.toggle('min')}
window.addEventListener('resize',resize);resize();refilter();fitAll(1);
"""


def render_map(
    prospects: pl.DataFrame,
    clients: pl.DataFrame,
    territory: list[list[list[float]]],
    brand: KinBrand,
    title: str,
    audience: str,
    columns: ClientColumns,
) -> str:
    shown = map_prospects(prospects)
    hidden = prospects.height - shown.height
    data = _payload(shown, clients, territory, audience, columns)
    version = "Versión KO · sin nombres" if audience == "ko" else "Versión Bottler"
    search = (
        "Buscar nombre o categoría" if audience == "bottler" else "Buscar categoría"
    )
    # </script> inside a JSON string would close the tag: escape the slash
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    return f"""<!doctype html>
<html lang="es" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>{brand.head_css}
{PAGE_CSS}
{MAP_CSS}</style></head><body>
<aside id="side">{brand.logo(LOGO_FORMAL_DARK)}
<div class="eyebrow">Mapa de prospección</div><h1>{title}</h1>
<p class="sub">{version} · {_es(len(data["lat"]))} prospectos{f" ({_es(hidden)} sin ciudad, provincia o score no se muestran)" if hidden else ""} · <span class="ka-site">kinanalytics.com</span></p>
<div class="stats"><div class="stat"><div class="num" id="st-total"></div><div class="lbl">Prospectos</div></div>
<div class="stat"><div class="num key" id="st-vis"></div><div class="lbl">Visibles</div></div></div>
<div class="sec">Vista</div>
<label class="f">Color de hexágonos</label><div class="seg" id="seg-hex"></div>
<label class="f">Color de puntos</label><div class="seg" id="seg-pt"></div>
<label class="f">Resolución H3</label><div class="seg" id="seg-res"></div>
<p class="help">Auto: 6 en región, 7 en ciudad y 8 en barrio. La leyenda del mapa muestra los rangos de lo visible.</p>
<div class="sec">Ubicación</div>
<label class="f" for="f-state">Provincia</label><select class="sel" id="f-state"></select>
<label class="f" for="f-city">Ciudad</label><select class="sel" id="f-city"></select>
<div class="actions"><button class="btn primary" id="b-fit">Encuadrar resultados</button><button class="btn" id="b-clear">Limpiar filtros</button></div>
<div id="active"></div>
<div class="sec">Filtros</div>
<label class="f" for="f-cat">Categoría</label><select class="sel" id="f-cat"></select>
<label class="f" for="search">Buscar</label><input class="txt" id="search" placeholder="{search}">
<div id="filters"></div>
<div class="sec">Capas</div><div id="layers"></div>
<p class="help" style="margin-top:1.25rem">Arrastra para moverte · rueda o pellizco para zoom · doble clic acerca · teclas + − 0 · Esc cierra</p>
</aside>
<div id="wrap"><canvas id="cv"></canvas><div id="tip"></div><div id="pop"></div>
<div id="crumb"></div>
<div id="zoom"><button id="zin" title="Acercar (+)">+</button><button id="zout" title="Alejar (−)">−</button><button id="zfit" title="Ver todo el territorio (0)">⤢</button></div>
<div id="legend"></div>
<div id="osm">Mapa base: Esri, HERE, Garmin, © colaboradores de OpenStreetMap</div>
<div id="hint">Elige una provincia o ciudad, o haz clic en un hexágono para acercarte</div></div>
<script>const D={payload};const P={json.dumps(MAP_PALETTE)};</script>
<script>{MAP_JS}</script>
</body></html>"""

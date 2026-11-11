"""Offline prospection map (one self-contained HTML): no tiles, no CDN, no API.

The user rule is that maps never call an API, and the brand forbids internet imports,
so the map is drawn on a <canvas> with its own Web Mercator projection: H3 hexagons
(more yellow = more prospects), the prospects, the current clients and the territory
outline from the run's GeoJSON as geographic context. Fonts, tokens and the logo are
embedded (skill brand-guidelines-kin).

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


def _payload(
    prospects: pl.DataFrame,
    clients: pl.DataFrame,
    territory: list[list[list[float]]],
    audience: str,
    columns: ClientColumns,
) -> dict[str, Any]:
    lat = prospects.get_column("latitude").cast(pl.Float64).round(5).to_list()
    lon = prospects.get_column("longitude").cast(pl.Float64).round(5).to_list()
    hexes = prospects.get_column("hex_8").to_list()
    cell_ids = sorted(set(hexes))
    cell_index = {c: i for i, c in enumerate(cell_ids)}
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
        "hex": [cell_index[h] for h in hexes],
        "cells": [
            [[round(a, 5), round(b, 5)] for a, b in h3.cell_to_boundary(c)]
            for c in cell_ids
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
.toggle{margin-left:auto;cursor:pointer;color:var(--ka-color-gray-3)}
.toggle.on{color:var(--ka-color-yellow)}
.actions{display:flex;gap:.5rem;margin:.5rem 0 0}
.btn{flex:1;cursor:pointer;border-radius:var(--ka-radius-base);padding:.5rem;font-family:var(--ka-font-body);font-size:var(--ka-size-caption);font-weight:var(--ka-weight-semibold);border:.0625rem solid var(--ka-color-gray-3);background:var(--ka-color-black);color:var(--ka-color-white)}
.btn.primary{background:var(--ka-color-yellow);color:var(--ka-color-black);border-color:var(--ka-color-yellow)}
.btn:hover{border-color:var(--ka-color-white)}
#active{font-size:var(--ka-size-caption);color:var(--ka-color-gray-2);margin:.5rem 0 0;min-height:1rem}
#wrap{position:relative;flex:1;touch-action:none}
canvas{display:block;width:100%;height:100%;cursor:grab}
#tip,#pop{position:absolute;pointer-events:none;background:var(--ka-color-black);color:var(--ka-color-white);border:.0625rem solid var(--ka-color-gray-3);border-radius:var(--ka-radius-base);padding:.5rem .75rem;font-size:var(--ka-size-caption);display:none;max-width:20rem}
#pop{pointer-events:auto;box-shadow:0 .25rem 1rem var(--ka-color-black)}
#pop .nm{font-family:var(--ka-font-display);font-weight:var(--ka-weight-bold);margin-bottom:.25rem;padding-right:1.25rem}
#pop .x{position:absolute;right:.375rem;top:.25rem;cursor:pointer;color:var(--ka-color-gray-3)}
#crumb{position:absolute;left:1rem;top:1rem;background:var(--ka-color-gray-4);border-radius:var(--ka-radius-pill);padding:.375rem .875rem;font-size:var(--ka-size-caption);color:var(--ka-color-gray-2)}
#crumb b{color:var(--ka-color-yellow);font-weight:var(--ka-weight-semibold)}
#zoom{position:absolute;right:1rem;top:1rem;display:flex;flex-direction:column;gap:.25rem}
#zoom button{width:2.25rem;height:2.25rem;background:var(--ka-color-gray-4);color:var(--ka-color-white);border:.0625rem solid var(--ka-color-gray-3);border-radius:var(--ka-radius-base);cursor:pointer;font-size:var(--ka-size-body)}
#zoom button:hover{border-color:var(--ka-color-yellow)}
#hint{position:absolute;left:50%;bottom:1rem;transform:translateX(-50%);background:var(--ka-color-gray-4);padding:.375rem .875rem;border-radius:var(--ka-radius-pill);font-size:var(--ka-size-caption);color:var(--ka-color-gray-2)}
.ka-site{color:var(--ka-color-gray-3)}
@media (max-width:48rem){body{flex-direction:column}#side{width:auto;max-height:45vh}}
"""

MAP_JS = r"""
const tok=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const K={y:tok('--ka-color-yellow'),b:tok('--ka-color-black'),w:tok('--ka-color-white'),g2:tok('--ka-color-gray-2'),g3:tok('--ka-color-gray-3'),g4:tok('--ka-color-gray-4')};
const N=D.lat.length,HEX_OP=[.18,.32,.48,.64,.82,1],POINT_ZOOM=12.5,FEW_POINTS=6000;
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
// 8574 -> 8.574 (the 'es' locale leaves 4-digit numbers ungrouped)
const fmt=n=>String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g,'.');
const $=id=>document.getElementById(id);
const cv=$('cv'),ctx=cv.getContext('2d'),tip=$('tip'),pop=$('pop');
// Web Mercator in "world pixels" at zoom 0 (256 px world): no tiles, no API
const px=lon=>(lon+180)/360*256,py=lat=>{const s=Math.sin(lat*Math.PI/180);return (0.5-Math.log((1+s)/(1-s))/(4*Math.PI))*256};
const X=Float64Array.from(D.lon,px),Y=Float64Array.from(D.lat,py);
const CX=Float64Array.from(D.cLon,px),CY=Float64Array.from(D.cLat,py);
const CELLS=D.cells.map(r=>r.map(([la,lo])=>[px(lo),py(la)]));
const CC=CELLS.map(r=>[r.reduce((s,p)=>s+p[0],0)/r.length,r.reduce((s,p)=>s+p[1],0)/r.length]);
const TERR=D.territory.map(r=>r.map(([la,lo])=>[px(lo),py(la)]));
// Width of one H3 cell in world pixels at zoom 0 (all cells share the resolution)
const CELL_W=CELLS.length?Math.max(...CELLS[0].map(p=>p[0]))-Math.min(...CELLS[0].map(p=>p[0])):0;
let view={x:128,y:128,z:4},W=0,H=0,dpr=1,anim=null;
const sx=x=>(x-view.x)*2**view.z+W/2,sy=y=>(y-view.y)*2**view.z+H/2;
const wx=x=>(x-W/2)/2**view.z+view.x,wy=y=>(y-H/2)/2**view.z+view.y;

// ---- framing: robust bounds (2-98 percentile) so one stray point never zooms out
function quantile(a,q){if(!a.length)return 0;const s=Float64Array.from(a).sort();return s[Math.min(s.length-1,Math.max(0,Math.floor(q*(s.length-1))))]}
function boundsOf(idx){if(!idx.length)return null;const xs=idx.map(i=>X[i]),ys=idx.map(i=>Y[i]);
  const lo=idx.length>50?.02:0,hi=idx.length>50?.98:1;return [quantile(xs,lo),quantile(ys,lo),quantile(xs,hi),quantile(ys,hi)]}
function targetFor(b){const w=Math.max(b[2]-b[0],2e-4),h=Math.max(b[3]-b[1],2e-4);
  const z=Math.min(16,Math.max(2,Math.log2(Math.min((W*.85)/w,(H*.85)/h))));return {x:(b[0]+b[2])/2,y:(b[1]+b[3])/2,z}}
function flyTo(t,ms=650){cancelAnimationFrame(anim);const s={...view},t0=performance.now();pop.style.display='none';
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
let vis=[],hexCount=new Map(),breaks=[1,2,3,4,5];
function refilter(){vis=[];hexCount=new Map();for(let i=0;i<N;i++)if(visible(i)){vis.push(i);hexCount.set(D.hex[i],(hexCount.get(D.hex[i])||0)+1)}
  const v=[...hexCount.values()].sort((a,b)=>a-b);if(v.length)breaks=[.2,.4,.6,.8,.95].map(q=>v[Math.min(v.length-1,Math.floor(q*v.length))]);
  $('st-vis').textContent=fmt(vis.length);updateCrumb();updateActive();draw()}
const hexClass=n=>{for(let i=0;i<5;i++)if(n<=breaks[i])return i;return 5};
const layers={hex:true,points:true,clients:D.cLat.length>0,territory:D.territory.length>0};
const EXIST=D.xcat.find(x=>x.key==='probability_existence_cat');
const existColor=i=>{if(!EXIST)return K.y;const v=EXIST.uniq[EXIST.codes[i]];return v==='high'?K.y:v==='moderate'?K.w:K.g3};
const showPoints=()=>view.z>=POINT_ZOOM||vis.length<=FEW_POINTS;

// ---- drawing
function path(r){ctx.beginPath();r.forEach(([x,y],j)=>j?ctx.lineTo(sx(x),sy(y)):ctx.moveTo(sx(x),sy(y)));ctx.closePath()}
function draw(){
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle=K.b;ctx.fillRect(0,0,W,H);
  if(layers.territory){ctx.strokeStyle=K.g3;ctx.lineWidth=1;ctx.fillStyle=K.g4;TERR.forEach(r=>{path(r);ctx.globalAlpha=.55;ctx.fill();ctx.globalAlpha=1;ctx.stroke()})}
  const pts=showPoints();
  // At country scale an H3 cell is smaller than a pixel: show density dots instead,
  // so the map is never empty before the person zooms in
  const hexPx=CELL_W*2**view.z;
  if(layers.hex&&hexPx<3&&!pts){ctx.fillStyle=K.y;ctx.globalAlpha=.35;for(const i of vis){const x=sx(X[i]),y=sy(Y[i]);if(x<0||y<0||x>W||y>H)continue;ctx.fillRect(x-1,y-1,2.5,2.5)}ctx.globalAlpha=1}
  else if(layers.hex){ctx.lineWidth=.5;ctx.strokeStyle=K.b;hexCount.forEach((n,c)=>{const x0=sx(CC[c][0]),y0=sy(CC[c][1]);if(x0<-80||y0<-80||x0>W+80||y0>H+80)return;
    path(CELLS[c]);ctx.globalAlpha=HEX_OP[hexClass(n)]*(pts&&view.z>=POINT_ZOOM?.45:1);ctx.fillStyle=K.y;ctx.fill();ctx.globalAlpha=1;ctx.stroke()})}
  $('hint').style.display=pts||!vis.length?'none':'block';
  // Current clients: light-gray squares, so they never read as a low-existence prospect
  if(view.z>=POINT_ZOOM&&layers.clients){ctx.fillStyle=K.g2;ctx.strokeStyle=K.b;ctx.lineWidth=1;for(let i=0;i<CX.length;i++){const x=sx(CX[i]),y=sy(CY[i]);if(x<0||y<0||x>W||y>H)continue;ctx.fillRect(x-3.5,y-3.5,7,7);ctx.strokeRect(x-3.5,y-3.5,7,7)}}
  if(pts&&layers.points){ctx.strokeStyle=K.b;ctx.lineWidth=1;const r=view.z>=POINT_ZOOM?4.5:3;for(const i of vis){const x=sx(X[i]),y=sy(Y[i]);if(x<0||y<0||x>W||y>H)continue;ctx.fillStyle=existColor(i);ctx.beginPath();ctx.arc(x,y,r,0,7);ctx.fill();ctx.stroke()}}
}
function resize(){const r=cv.parentElement.getBoundingClientRect();dpr=window.devicePixelRatio||1;W=r.width;H=r.height;cv.width=W*dpr;cv.height=H*dpr;draw()}

// ---- interaction: mouse, wheel, touch (pinch), keyboard
function zoomAt(f,mx,my){cancelAnimationFrame(anim);const ax=wx(mx),ay=wy(my);view.z=Math.min(18,Math.max(2,view.z+f));view.x=ax-(mx-W/2)/2**view.z;view.y=ay-(my-H/2)/2**view.z;pop.style.display='none';draw()}
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
cv.addEventListener('pointerleave',()=>{tip.style.display='none'});
cv.addEventListener('wheel',e=>{e.preventDefault();const [mx,my]=local(e);zoomAt(e.deltaY<0?.4:-.4,mx,my)},{passive:false});
cv.addEventListener('dblclick',e=>{const [mx,my]=local(e);const ax=wx(mx),ay=wy(my);flyTo({x:ax,y:ay,z:Math.min(18,view.z+1.5)},350)});
window.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT'||e.target.tagName==='SELECT')return;
  if(e.key==='+'||e.key==='=')zoomAt(1,W/2,H/2);else if(e.key==='-')zoomAt(-1,W/2,H/2);else if(e.key==='0')fitAll();else if(e.key==='Escape'){pop.style.display='none'}});
$('zin').onclick=()=>zoomAt(1,W/2,H/2);$('zout').onclick=()=>zoomAt(-1,W/2,H/2);$('zfit').onclick=()=>fitAll();

function inPoly(x,y,r){let c=false;for(let i=0,j=r.length-1;i<r.length;j=i++){const [xi,yi]=r[i],[xj,yj]=r[j];if((yi>y)!==(yj>y)&&x<(xj-xi)*(y-yi)/(yj-yi)+xi)c=!c}return c}
function hexAt(mx,my){const x=wx(mx),y=wy(my);const radius=48/2**view.z;let hit=-1;
  hexCount.forEach((n,c)=>{if(hit>=0)return;if(Math.abs(CC[c][0]-x)>radius||Math.abs(CC[c][1]-y)>radius)return;if(inPoly(x,y,CELLS[c]))hit=c});return hit}
let hoverFrame=0;
function hoverAt(e){if(hoverFrame)return;hoverFrame=requestAnimationFrame(()=>{hoverFrame=0;const [mx,my]=local(e);
  if(!layers.hex||showPoints()&&view.z>=POINT_ZOOM){tip.style.display='none';cv.style.cursor='grab';return}
  const c=hexAt(mx,my);if(c<0){tip.style.display='none';cv.style.cursor='grab';return}
  cv.style.cursor='zoom-in';tip.innerHTML=`<b>${fmt(hexCount.get(c))}</b> prospectos · clic para acercar`;tip.style.left=(mx+14)+'px';tip.style.top=(my+14)+'px';tip.style.display='block'})}
function nearestPoint(mx,my){let best=-1,bd=100;for(const i of vis){const dx=sx(X[i])-mx,dy=sy(Y[i])-my,d=dx*dx+dy*dy;if(d<bd){bd=d;best=i}}return [best,bd]}
function clickAt(e){const [mx,my]=local(e);
  if(showPoints()&&layers.points){const [best,bd]=nearestPoint(mx,my);
    let client=-1,cd=bd;if(layers.clients&&view.z>=POINT_ZOOM)for(let i=0;i<CX.length;i++){const dx=sx(CX[i])-mx,dy=sy(CY[i])-my,d=dx*dx+dy*dy;if(d<cd){cd=d;client=i}}
    if(client>=0||best>=0){showPopup(client>=0?-1:best,client,mx,my);return}}
  const c=layers.hex?hexAt(mx,my):-1;
  if(c>=0){const r=CELLS[c];const xs=r.map(p=>p[0]),ys=r.map(p=>p[1]);
    // Neighbourhood view around the cell: points visible, the cell's surroundings too
    const t=targetFor([Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)]);t.z=POINT_ZOOM+1.25;flyTo(t);return}
  pop.style.display='none'}
function showPopup(best,client,mx,my){let h;
  if(best>=0){const rows=[`Categoría: ${esc(D.uCat[D.cat[best]])}`,`Ciudad: ${esc(D.uCity[D.city[best]])} · ${esc(D.uState[D.state[best]])}`,`Score: ${D.score[best]}`];
    D.xcat.forEach(x=>rows.push(`${x.label}: ${esc(x.uniq[x.codes[best]])}`));D.xnum.forEach(x=>rows.push(`${x.label}: ${fmt(x.vals[best])} m`));
    h=`<span class="x" title="Cerrar">✕</span><div class="nm">${esc(D.names[best]||D.uCat[D.cat[best]])}</div>${rows.join('<br>')}`}
  else h=`<span class="x" title="Cerrar">✕</span><div class="nm">${esc(D.cNames[client]||'Cliente actual')}</div>Cliente actual del bottler`;
  pop.innerHTML=h;pop.querySelector('.x').onclick=()=>pop.style.display='none';
  pop.style.left=Math.max(8,Math.min(mx+14,W-330))+'px';pop.style.top=Math.max(8,Math.min(my+14,H-300))+'px';pop.style.display='block'}

// ---- sidebar: location (flies there), category, chips, ranges, search
function countsOf(codes,keep){const c=new Map();for(let i=0;i<N;i++)if(keep(i))c.set(codes[i],(c.get(codes[i])||0)+1);return c}
function fillSelect(sel,uniq,counts,label){const opts=[...counts.entries()].sort((a,b)=>b[1]-a[1]);
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
  uniq.forEach((u,j)=>{const ch=document.createElement('span');ch.className='chip';ch.textContent=u||'(vacío)';ch.onclick=()=>{set.has(j)?set.delete(j):set.add(j);ch.classList.toggle('on');refilter()};c.appendChild(ch)});b.appendChild(c);return b}
const F=$('filters');
D.xcat.forEach((x,k)=>F.appendChild(chips(x.label,x.uniq,fX[k])));
D.xnum.forEach((x,k)=>{const b=document.createElement('div');b.innerHTML=`<label class="f">${x.label}: <span>todas</span></label><input type="range" min="0" max="${x.max}" step="10" value="${x.max}">`;
  b.querySelector('input').oninput=e=>{fMax[k]=+e.target.value;b.querySelector('span').textContent=fMax[k]>=x.max?'todas':`≤ ${fmt(fMax[k])} m`;refilter()};F.appendChild(b)});
let searchTimer=0;$('search').oninput=e=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{fText=e.target.value.trim().toLowerCase();refilter()},180)};
$('b-fit').onclick=()=>fitVisible();
$('b-clear').onclick=()=>{fState=fCity=fCat=-1;fText='';$('search').value='';selState.value='-1';selCat.value='-1';refreshCities();
  fX.forEach(s=>s.clear());document.querySelectorAll('.chip.on').forEach(c=>c.classList.remove('on'));
  D.xnum.forEach((x,k)=>{fMax[k]=x.max});document.querySelectorAll('#filters input[type=range]').forEach((r,k)=>{r.value=D.xnum[k].max;r.previousElementSibling.querySelector('span').textContent='todas'});
  refilter();fitAll()};
function updateCrumb(){const parts=['Territorio'];if(fState>=0)parts.push(D.uState[fState]);if(fCity>=0)parts.push(D.uCity[fCity]);
  $('crumb').innerHTML=parts.map(esc).join(' › ')+` · <b>${fmt(vis.length)}</b> prospectos`}
function updateActive(){const n=(fState>=0)+(fCity>=0)+(fCat>=0)+(fText?1:0)+fX.reduce((s,x)=>s+(x.size?1:0),0)+fMax.reduce((s,m,k)=>s+(m<D.xnum[k].max?1:0),0);
  $('active').textContent=n?`${n} filtro${n>1?'s':''} activo${n>1?'s':''}`:'Sin filtros: todo el territorio'}
const LAY=[['hex','Hexágonos'],['points','Prospectos'],['clients',`Clientes actuales (${fmt(D.cLat.length)})`],['territory','Territorio']].filter(([k])=>k!=='territory'||D.territory.length);
$('layers').innerHTML=LAY.map(([k,t])=>`<div class="row"><span>${t}</span><span class="toggle${layers[k]?' on':''}" data-k="${k}">${layers[k]?'●':'○'}</span></div>`).join('');
document.querySelectorAll('.toggle').forEach(t=>t.onclick=()=>{const k=t.dataset.k;layers[k]=!layers[k];t.classList.toggle('on');t.textContent=layers[k]?'●':'○';draw()});
$('st-total').textContent=fmt(N);
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
    data = _payload(prospects, clients, territory, audience, columns)
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
<p class="sub">{version} · {len(data["lat"]):,} prospectos · <span class="ka-site">kinanalytics.com</span></p>
<div class="stats"><div class="stat"><div class="num" id="st-total"></div><div class="lbl">Prospectos</div></div>
<div class="stat"><div class="num key" id="st-vis"></div><div class="lbl">Visibles</div></div></div>
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
<div class="sec">Leyenda</div>
<div class="row"><span class="dot" style="background:var(--ka-color-yellow)"></span>Existencia high</div>
<div class="row"><span class="dot" style="background:var(--ka-color-white)"></span>Existencia moderate</div>
<div class="row"><span class="dot" style="background:var(--ka-color-gray-3)"></span>Existencia low</div>
<div class="row"><span class="sq" style="background:var(--ka-color-gray-2)"></span>Cliente actual del bottler</div>
<div class="row"><span class="sq"></span>Hexágono: más amarillo = más prospectos</div>
<p class="sub" style="margin-top:1rem">Arrastra para moverte · rueda o pellizco para zoom · doble clic acerca · teclas + − 0 · Esc cierra</p>
</aside>
<div id="wrap"><canvas id="cv"></canvas><div id="tip"></div><div id="pop"></div>
<div id="crumb"></div>
<div id="zoom"><button id="zin" title="Acercar (+)">+</button><button id="zout" title="Alejar (−)">−</button><button id="zfit" title="Ver todo el territorio (0)">⤢</button></div>
<div id="hint">Elige una provincia o ciudad, o haz clic en un hexágono para acercarte</div></div>
<script>const D={payload};</script>
<script>{MAP_JS}</script>
</body></html>"""

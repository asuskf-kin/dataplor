"""Mapas de puntos del QA de prospección (un HTML, sin librerías ni CDN).

Misma regla que los mapas de prospección: la única red son las teselas gratuitas de Esri
World Light Gray (sin clave); el lienzo usa la paleta ``MAP_PALETTE``. Cada capa se
prende y apaga, y un clic en un punto abre su ficha. Los pares (falso negativo ↔
cliente) se unen con una línea punteada.

Estos mapas llevan nombres y coordenadas de clientes: se quedan en el espejo local y
nunca entran en una lista de subida.
"""

import json
from dataclasses import dataclass, field

from cleaning_agent.adapters.brand import LOGO_FORMAL_DARK, PAGE_CSS, KinBrand
from cleaning_agent.adapters.prospection_map import MAP_PALETTE
from cleaning_agent.adapters.qa_html import esc


@dataclass
class MapLayer:
    """Una capa: puntos [lat, lon] y la ficha de cada uno (lista de pares clave-valor)."""

    label: str
    color: str
    radius: float
    points: list[tuple[float, float]] = field(default_factory=list)
    info: list[list[tuple[str, str]]] = field(default_factory=list)


CSS = """
html,body{margin:0;height:100%;overflow:hidden;background:var(--ka-color-black)}
#side{position:absolute;left:0;top:0;bottom:0;width:20rem;overflow:auto;padding:1.25rem;box-sizing:border-box;
 background:var(--ka-color-black);color:var(--ka-color-white);font-family:var(--ka-font-body)}
#side h1{font-family:var(--ka-font-display);font-size:1.35rem;margin:.75rem 0 .25rem}
#side .sub{color:#b9bcc2;font-size:.85rem;margin:0 0 1rem}
#side svg,#side img{height:28px;width:auto}
.row{display:flex;align-items:center;gap:.6rem;margin:.5rem 0;cursor:pointer;font-size:.9rem}
.dot{width:.85rem;height:.85rem;border-radius:50%;flex:none;border:1px solid #fff4}
.row.off{opacity:.4}
#wrap{position:absolute;left:20rem;right:0;top:0;bottom:0}
canvas{display:block;width:100%;height:100%;cursor:grab}
#pop{position:absolute;display:none;max-width:22rem;background:#fff;color:#141417;border-radius:8px;padding:.6rem .8rem;
 font:13px/1.35 var(--ka-font-body);box-shadow:0 4px 18px #0004;pointer-events:auto}
#pop b{font-family:var(--ka-font-display)}#pop table{border-collapse:collapse}#pop td{padding:1px 6px 1px 0;vertical-align:top}
#osm{position:absolute;right:6px;bottom:4px;font:11px var(--ka-font-body);color:#444;background:#fff9;padding:1px 4px}
@media (max-width:48rem){#side{position:static;width:auto;height:auto}#wrap{left:0;top:auto;height:70vh;position:relative}html,body{overflow:auto}}
"""

JS = r"""
const cv=document.getElementById('cv'),ctx=cv.getContext('2d'),pop=document.getElementById('pop');
let W=0,H=0,dpr=1;const view={x:0,y:0,z:3};
const lx=lon=>(lon+180)/360,ly=lat=>{const s=Math.sin(lat*Math.PI/180);return .5-Math.log((1+s)/(1-s))/(4*Math.PI)};
const sc=()=>256*2**view.z,sx=x=>(x-view.x)*sc()+W/2,sy=y=>(y-view.y)*sc()+H/2,wx=px=>(px-W/2)/sc()+view.x,wy=py=>(py-H/2)/sc()+view.y;
D.layers.forEach(l=>{l.on=true;l.xy=l.points.map(([a,o])=>[lx(o),ly(a)])});
const tiles=new Map();
function tile(z,x,y){const k=z+'/'+x+'/'+y;let t=tiles.get(k);if(!t){if(tiles.size>600)tiles.delete(tiles.keys().next().value);
 t=new Image();t.onload=()=>{t.ok=true;draw()};t.src=`https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/${z}/${y}/${x}`;tiles.set(k,t)}return t}
function draw(){ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle=P.background;ctx.fillRect(0,0,W,H);
 const tz=Math.max(0,Math.min(16,Math.round(view.z))),n=2**tz,ts=1/n,size=ts*sc()+.5;
 for(let ty=Math.max(0,Math.floor(wy(0)/ts));ty<=Math.min(n-1,Math.floor(wy(H)/ts));ty++)
  for(let tx=Math.floor(wx(0)/ts);tx<=Math.floor(wx(W)/ts);tx++){const t=tile(tz,((tx%n)+n)%n,ty);if(t.ok)ctx.drawImage(t,sx(tx*ts),sy(ty*ts),size,size)}
 if(D.pairs.length&&D.layers.every(l=>l.on)){ctx.strokeStyle='#8a8f98';ctx.lineWidth=2;ctx.setLineDash([5,4]);ctx.beginPath();
  D.pairs.forEach(([a,b,c,d])=>{ctx.moveTo(sx(lx(b)),sy(ly(a)));ctx.lineTo(sx(lx(d)),sy(ly(c)))});ctx.stroke();ctx.setLineDash([])}
 const k=Math.min(1,Math.max(.35,(view.z-4)/9));
 D.layers.forEach(l=>{if(!l.on)return;ctx.fillStyle=l.color;ctx.strokeStyle='#fff';ctx.lineWidth=.8;const r=l.radius*k;
  l.xy.forEach(([x,y])=>{const X=sx(x),Y=sy(y);if(X<-r||Y<-r||X>W+r||Y>H+r)return;ctx.beginPath();ctx.arc(X,Y,r,0,7);ctx.fill();if(r>3)ctx.stroke()})})}
function resize(){dpr=devicePixelRatio||1;W=cv.clientWidth;H=cv.clientHeight;cv.width=W*dpr;cv.height=H*dpr;draw()}
function fit(){let x0=1,x1=0,y0=1,y1=0;D.layers.forEach(l=>l.xy.forEach(([x,y])=>{x0=Math.min(x0,x);x1=Math.max(x1,x);y0=Math.min(y0,y);y1=Math.max(y1,y)}));
 if(x1<x0)return;view.x=(x0+x1)/2;view.y=(y0+y1)/2;view.z=Math.min(16,Math.log2(Math.min(W/((x1-x0)||1e-6),H/((y1-y0)||1e-6))/256)-.2)}
let drag=null;cv.onmousedown=e=>{drag={x:e.clientX,y:e.clientY,vx:view.x,vy:view.y,moved:false}};
addEventListener('mousemove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>3)drag.moved=true;
 view.x=drag.vx-dx/sc();view.y=drag.vy-dy/sc();pop.style.display='none';draw()});
addEventListener('mouseup',e=>{if(drag&&!drag.moved)pick(e);drag=null});
cv.onwheel=e=>{e.preventDefault();const r=cv.getBoundingClientRect(),px=e.clientX-r.left,py=e.clientY-r.top,bx=wx(px),by=wy(py);
 view.z=Math.max(2,Math.min(19,view.z-e.deltaY*.0015));view.x=bx-(px-W/2)/sc();view.y=by-(py-H/2)/sc();pop.style.display='none';draw()};
function pick(e){const r=cv.getBoundingClientRect(),px=e.clientX-r.left,py=e.clientY-r.top;let best=null,bd=144;
 D.layers.forEach(l=>{if(!l.on)return;l.xy.forEach(([x,y],i)=>{const d=(sx(x)-px)**2+(sy(y)-py)**2;if(d<bd){bd=d;best=[l,i]}})});
 if(!best){pop.style.display='none';return}const [l,i]=best;
 pop.innerHTML=`<b>${esc(l.label)}</b><table>${l.info[i].map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join('')}</table>`;
 pop.style.left=Math.min(px+12,W-300)+'px';pop.style.top=Math.min(py+12,H-160)+'px';pop.style.display='block'}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
document.getElementById('layers').innerHTML=D.layers.map((l,i)=>`<div class="row" data-i="${i}"><span class="dot" style="background:${l.color}"></span><span>${esc(l.label)} (${l.points.length.toLocaleString('es')})</span></div>`).join('');
document.querySelectorAll('.row').forEach(r=>r.onclick=()=>{const l=D.layers[+r.dataset.i];l.on=!l.on;r.classList.toggle('off',!l.on);pop.style.display='none';draw()});
addEventListener('resize',resize);resize();fit();draw();
"""


def render_point_map(
    brand: KinBrand,
    title: str,
    subtitle: str,
    layers: list[MapLayer],
    pairs: list[tuple[float, float, float, float]] | None = None,
) -> str:
    data = {
        "layers": [
            {
                "label": layer.label,
                "color": layer.color,
                "radius": layer.radius,
                "points": [[round(a, 6), round(o, 6)] for a, o in layer.points],
                "info": layer.info,
            }
            for layer in layers
        ],
        "pairs": [[round(v, 6) for v in p] for p in pairs or []],
    }
    # </script> inside a JSON string would close the tag: escape the slash
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>{brand.head_css}{PAGE_CSS}{CSS}</style></head><body>
<aside id="side">{brand.logo(LOGO_FORMAL_DARK)}<h1>{esc(title)}</h1><p class="sub">{esc(subtitle)}</p>
<div id="layers"></div>
<p class="sub" style="margin-top:1rem">Clic en una capa para prenderla o apagarla · clic en un punto para ver su ficha ·
arrastra para moverte · rueda para zoom. Uso interno: trae nombres y coordenadas de clientes.</p></aside>
<div id="wrap"><canvas id="cv"></canvas><div id="pop"></div>
<div id="osm">Mapa base: Esri, HERE, Garmin, © colaboradores de OpenStreetMap</div></div>
<script>const D={payload};const P={json.dumps(MAP_PALETTE)};</script>
<script>{JS}</script></body></html>"""

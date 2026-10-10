"""Self-contained preview page for the canonical shared borders.

One HTML file (no fetches, plain JS, canvas): pastel demo-state fills,
canonical borders (dashed inside a state, thicker solid between states),
thin dark coasts, wheel zoom + drag, a ``show old double contours``
checkbox and stroke/dash sliders.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..svgpath import format_number


def _line_d(pts, closed=False):
    s = "M " + " ".join(
        f"{format_number(x)} {format_number(y)}" for x, y in pts
    )
    return s + (" Z" if closed else "")


def _arcs_d(arcs):
    return "".join(_line_d(a.pts, a.closed) for a in arcs)


_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>borders proto preview</title>
<style>
html,body{margin:0;height:100%;background:#1a1a1a;overflow:hidden;
 font:13px/1.4 system-ui,sans-serif;color:#ccc}
#ui{position:fixed;top:8px;left:8px;background:#0009;padding:8px 10px;
 border-radius:6px;user-select:none}
#ui label{display:flex;gap:6px;align-items:center;white-space:nowrap}
#ui input[type=range]{width:110px}
canvas{display:block;cursor:grab}
</style></head><body>
<canvas id="cv"></canvas>
<div id="ui">
 <label><input type="checkbox" id="old"> show old double contours</label>
 <label>internal w <input id="wIn" type="range" min="0.3" max="5"
  step="0.1" value="1.0"><span id="wInV">1.0</span></label>
 <label>state w <input id="wOut" type="range" min="0.3" max="8"
  step="0.1" value="2.2"><span id="wOutV">2.2</span></label>
 <label>coast w <input id="wCoast" type="range" min="0.3" max="5"
  step="0.1" value="1.2"><span id="wCoastV">1.2</span></label>
 <label>dash <input id="dash" type="range" min="1" max="20"
  step="0.5" value="5"><span id="dashV">5</span></label>
 <label>gap <input id="gap" type="range" min="1" max="20"
  step="0.5" value="3.5"><span id="gapV">3.5</span></label>
 <div id="scale" style="margin-top:4px;color:#889"></div>
</div>
<script>
const DATA = __DATA__;
const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
const W = DATA.view[2], H = DATA.view[3];
let scale = 1, tx = 0, ty = 0;
function fit(){
  cv.width = innerWidth; cv.height = innerHeight;
  const s0 = Math.min(cv.height / H, cv.width / W);
  if (!fit.done){ scale = s0; tx = (cv.width - W*s0)/2;
    ty = (cv.height - H*s0)/2; fit.done = true; }
  draw();
}
function parseD(d){
  const rings = [];
  for (const chunk of d.split('M')){
    const t = chunk.trim();
    if (!t) continue;
    const closed = /Z\\s*$/.test(t);
    const nums = t.replace(/Z/g, '').trim().split(/\\s+/).map(Number);
    const pts = [];
    for (let i = 0; i + 1 < nums.length; i += 2)
      pts.push([nums[i], nums[i+1]]);
    if (pts.length >= 2) rings.push({pts, closed});
  }
  return rings;
}
const fills = {}, coasts = {}, borders = {};
for (const [id, d] of Object.entries(DATA.paths))
  fills[id] = parseD(d);
for (const [id, d] of Object.entries(DATA.coasts))
  coasts[id] = parseD(d);
for (const [k, d] of Object.entries(DATA.borders))
  borders[k] = parseD(d);
const outside = parseD(DATA.outside);
const seaWater = DATA.sea_water ? parseD(DATA.sea_water) : [];
const ST = DATA.states;
function pastel(i){
  const h = (i * 0.61803398875) % 1;
  return `hsl(${Math.round(h*360)},45%,72%)`;
}
const statePaths = {};
for (const [id, rings] of Object.entries(fills)){
  const s = ST[id] === undefined ? -1 : ST[id];
  (statePaths[s] ||= []).push(...rings);
}
function drawRings(rings){
  ctx.beginPath();
  for (const r of rings){
    ctx.moveTo(r.pts[0][0], r.pts[0][1]);
    for (const pt of r.pts) ctx.lineTo(pt[0], pt[1]);
    if (r.closed) ctx.closePath();
  }
  ctx.stroke();
}
function fillRings(rings, color){
  ctx.fillStyle = color;
  ctx.beginPath();
  for (const r of rings){
    ctx.moveTo(r.pts[0][0], r.pts[0][1]);
    for (const pt of r.pts) ctx.lineTo(pt[0], pt[1]);
    ctx.closePath();
  }
  ctx.fill('nonzero');
}
function draw(){
  ctx.setTransform(1,0,0,1,0,0);
  ctx.fillStyle = '#1E3547'; ctx.fillRect(0,0,cv.width,cv.height);
  ctx.setTransform(scale,0,0,scale,tx,ty);
  ctx.lineJoin = 'round'; ctx.lineCap = 'round';
  fillRings(seaWater, '#1E3547');
  fillRings(outside, '#2A2A2A');
  for (const [s, rings] of Object.entries(statePaths))
    fillRings(rings, s === '-1' ? '#8C8C8C' : pastel(+s));
  const px = v => v / scale;
  if (document.getElementById('old').checked){
    ctx.strokeStyle = '#3A3A3A'; ctx.lineWidth = px(1);
    ctx.setLineDash([]);
    ctx.beginPath();
    for (const rings of Object.values(fills))
      for (const r of rings){
        ctx.moveTo(r.pts[0][0], r.pts[0][1]);
        for (const pt of r.pts) ctx.lineTo(pt[0], pt[1]);
        ctx.closePath();
      }
    ctx.stroke();
  }
  const wIn = +document.getElementById('wIn').value;
  const wOut = +document.getElementById('wOut').value;
  const wCoast = +document.getElementById('wCoast').value;
  const dash = +document.getElementById('dash').value;
  const gap = +document.getElementById('gap').value;
  ctx.strokeStyle = '#161A1F'; ctx.lineWidth = px(wCoast);
  ctx.setLineDash([]);
  for (const rings of Object.values(coasts)) drawRings(rings);
  for (const [k, rings] of Object.entries(borders)){
    const [a,b] = k.split('_').map(Number);
    const internal = ST[a] !== undefined && ST[a] === ST[b] && ST[a] >= 0;
    ctx.strokeStyle = internal ? '#232327' : '#0C0C0E';
    ctx.lineWidth = px(internal ? wIn : wOut);
    ctx.setLineDash(internal ? [px(dash), px(gap)] : []);
    drawRings(rings);
  }
  document.getElementById('scale').textContent =
    Math.round(scale*100)/100 + ' px/u (40 px/u = ' +
    (scale >= 40 ? 'at/above' : 'below') + ' reference)';
}
let drag = null;
cv.addEventListener('mousedown', e => { drag = {x:e.clientX-tx,
 y:e.clientY-ty}; cv.style.cursor='grabbing'; });
addEventListener('mouseup', () => { drag=null; cv.style.cursor='grab'; });
addEventListener('mousemove', e => {
  if (drag){ tx = e.clientX - drag.x; ty = e.clientY - drag.y; draw(); }});
cv.addEventListener('wheel', e => {
  e.preventDefault();
  const f = Math.exp(-e.deltaY * 0.0015);
  const ns = Math.min(80, Math.max(0.5, scale * f));
  tx = e.clientX - (e.clientX - tx) * ns / scale;
  ty = e.clientY - (e.clientY - ty) * ns / scale;
  scale = ns; draw();
}, {passive:false});
for (const id of ['wIn','wOut','wCoast','dash','gap'])
  document.getElementById(id).addEventListener('input', e => {
    document.getElementById(id+'V').textContent = e.target.value;
    draw(); });
document.getElementById('old').addEventListener('change', draw);
addEventListener('resize', fit);
fit();
</script></body></html>
"""


def write_preview(
    path: Path, manifest, geometry, nodes, border_map, coast_arcs,
    state, method: str,
) -> int:
    paths = {
        str(nid): geometry["paths"][str(nid)]
        for nid in sorted(nodes)
    }
    borders = {
        f"{a}_{b}": _arcs_d(arcs)
        for (a, b), arcs in sorted(border_map.items())
        if arcs
    }
    coasts = {
        str(nid): _arcs_d(arcs)
        for nid, arcs in sorted(coast_arcs.items())
        if arcs
    }
    data = {
        "view": manifest["view_box"],
        "method": method,
        "paths": paths,
        "borders": borders,
        "coasts": coasts,
        "states": {str(k): v for k, v in state.items()},
        "outside": geometry["outside"],
        "sea_water": geometry.get("sea_water", ""),
    }
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    html = _PAGE.replace("__DATA__", blob)
    path.write_text(html, encoding="utf-8")
    return path.stat().st_size

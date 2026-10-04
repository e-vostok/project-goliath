"""§3.3 Build the self-contained preview page.

Writes ``reference/relief_preview.html``: plain JS + SVG, no libraries,
all geometry embedded, textures referenced as sibling files
(``relief_texture_16.webp`` / ``relief_texture_16_dim.webp``).  Opens by
double-click.  View state is read from the URL hash
(#cx=&cy=&w=&preset=) so headless Chromium can take the screenshots.

Run after bake.py:  python -m tools.map_pipeline.relief_proto.make_preview
"""
from __future__ import annotations

import json
import sys
from collections import deque
from pathlib import Path

import numpy as np
from shapely.geometry import box
from shapely.ops import unary_union

from tools.map_pipeline.svgpath import dumps, parse_path

from . import proto_common as pc
from .bake import FRAME_MARGIN

CLIP_MARGIN = 9.0          # geometry kept this far beyond the texture
FREE_CAP = 55              # max provinces per demo nation

# 14 demo nations: seed point in lon/lat + colour
NATIONS = [
    ((-2.0, 52.5), "#c0392b"),   # England
    ((2.0, 47.0), "#2980b9"),    # France
    ((-4.0, 40.0), "#e2c044"),   # Iberia
    ((13.0, 42.5), "#27ae60"),   # Italy
    ((10.5, 51.0), "#7f8c8d"),   # Germany
    ((20.0, 52.0), "#8e44ad"),   # Poland
    ((15.5, 62.0), "#16a085"),   # Scandinavia
    ((37.0, 56.0), "#d35400"),   # Russia
    ((21.0, 44.0), "#da8bc3"),   # Balkans
    ((32.0, 39.0), "#c9a227"),   # Anatolia
    ((31.0, 30.0), "#b9770e"),   # Egypt
    ((3.0, 34.0), "#5d6d7e"),    # Maghreb
    ((45.0, 34.0), "#a93226"),   # Persia
    ((-6.5, 53.3), "#1e8449"),   # Ireland
]


def clip_geom(polys, clip):
    out = []
    for p in polys:
        try:
            g = p.intersection(clip)
        except Exception:
            continue
        if g.is_empty:
            continue
        out.append(g)
    return out


def dump_geom(geoms) -> str:
    """Clip result -> canonical path string (skip non-polygons)."""
    parts = []
    for g in geoms:
        if g.is_empty:
            continue
        if g.geom_type == "Polygon":
            parts.append(g)
        elif g.geom_type in ("MultiPolygon", "GeometryCollection"):
            parts.extend(
                x for x in g.geoms if x.geom_type == "Polygon")
    parts = [p.buffer(0) for p in parts]  # clean intersection artefacts
    parts = [p for p in parts if not p.is_empty and p.area > 1e-4]
    if not parts:
        return ""
    return dumps(unary_union(parts))


def build_nations(manifest):
    """Contiguous demo nations via multi-source BFS over land edges."""
    kinds = pc.node_kinds(manifest)
    land_ids = {i for i, k in kinds.items() if k == "LAND"}
    adj = {i: set() for i in land_ids}
    for e in manifest["edges"]:
        if e["type"] != "land":
            continue
        a, b = str(e["a"]), str(e["b"])
        if a in land_ids and b in land_ids:
            adj[a].add(b)
            adj[b].add(a)
    georef = manifest["georef"]
    anchors = {str(n["id"]): n["anchor"] for n in manifest["nodes"]
               if str(n["id"]) in land_ids}

    def nearest_node(lon, lat):
        bx, by = pc.lonlat_to_base(np.array([lon]), np.array([lat]),
                                 georef)
        bx, by = float(bx[0]), float(by[0])
        return min(
            land_ids,
            key=lambda i: (anchors[i][0] - bx) ** 2
            + (anchors[i][1] - by) ** 2,
        )

    owner = {}
    queues = []
    for (lon, lat), _color in NATIONS:
        seed = nearest_node(lon, lat)
        if seed not in owner:
            owner[seed] = len(queues)
            queues.append(deque([seed]))
    active = True
    grown = [1] * len(queues)
    while active:
        active = False
        for ni, q in enumerate(queues):
            if q and grown[ni] < FREE_CAP:
                node = q.popleft()
                grown[ni] += 1
                for nb in adj.get(node, ()):
                    if nb not in owner:
                        owner[nb] = ni
                        q.append(nb)
                        active = True
    return owner


def main(argv=None) -> int:
    geometry = pc.load_geometry()
    manifest = pc.load_manifest()
    cfg = pc.load_map_config()
    colors = cfg["colors"]
    frame = cfg["view"]["frame"]

    x0 = frame["x"] - CLIP_MARGIN
    y0 = frame["y"] - CLIP_MARGIN
    clip = box(x0, y0, frame["x"] + frame["width"] + CLIP_MARGIN,
               frame["y"] + frame["height"] + CLIP_MARGIN)

    kinds = pc.node_kinds(manifest)
    paths_out: dict[str, str] = {}
    for key, d in geometry["paths"].items():
        polys = clip_geom(parse_path(d), clip)
        if not polys:
            continue
        dd = dump_geom(polys)
        if dd:
            paths_out[key] = dd
    sea_water_d = dump_geom(
        clip_geom(parse_path(geometry["sea_water"]), clip))

    land_polys = []
    for key, d in geometry["paths"].items():
        if kinds.get(key) == "LAND" and key in paths_out:
            land_polys.extend(clip_geom(parse_path(d), clip))
    land_polys += clip_geom(parse_path(geometry["outside"]), clip)
    land_union = unary_union(land_polys).buffer(0)
    outline_d = dump_geom([land_union])  # union boundary only

    owner = build_nations(manifest)
    nation_colors = [c for _, c in NATIONS]

    # darken the sea colour for inactive (unexplored / outside) water
    def hex_scale(hexcol, f):
        v = [int(hexcol[i:i + 2], 16) for i in (1, 3, 5)]
        return "#" + "".join(f"{min(255, int(c * f)):02X}" for c in v)

    data = {
        "frame": [frame["x"], frame["y"], frame["width"],
                  frame["height"]],
        "viewBox": manifest["view_box"],
        "textureRect": [frame["x"] - FRAME_MARGIN,
                        frame["y"] - FRAME_MARGIN,
                        frame["width"] + 2 * FRAME_MARGIN,
                        frame["height"] + 2 * FRAME_MARGIN],
        "colors": {
            "sea": colors["sea"],
            "outside": colors["outside"],
            "border": colors["province_border"],
            "neutral": colors["neutral_province"],
            "inactiveSea": hex_scale(colors["sea"], 0.55),
        },
        "zoomMax": cfg["view"]["zoom_max"],
        "paths": paths_out,
        "kinds": {k: (0 if kinds.get(k) == "LAND" else 1)
                  for k in paths_out},
        "nations": {i: n for i, n in owner.items() if i in paths_out},
        "nationColors": nation_colors,
        "seaWater": sea_water_d,
        "landOutline": outline_d,
    }
    html = TEMPLATE.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    out = pc.REF_DIR / "relief_preview.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")
    return 0


TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>relief prototype - map_polish_5</title>
<style>
html,body{margin:0;height:100%;background:#16191d;overflow:hidden}
svg{display:block;width:100vw;height:100vh}
#panel{position:fixed;top:8px;left:8px;z-index:5;background:#1d222add;
color:#cfd6dd;font:12px/1.5 system-ui,sans-serif;padding:10px 12px;
border-radius:8px;min-width:230px}
#panel label{display:flex;justify-content:space-between;gap:8px}
#panel input[type=range]{width:120px}
button{margin-right:6px;cursor:pointer}
.dim{color:#8899aa;font-size:11px}
</style></head><body>
<div id="panel">
<b>relief prototype</b><br>
<label>relief <input id="relief" type="range" min="0" max="1" step="0.01"></label>
<label>owner <input id="own" type="range" min="0" max="1" step="0.01"></label>
<label>dim <input id="dim" type="range" min="0" max="1" step="0.01"></label>
<label>glow <input id="glow" type="range" min="0" max="1" step="0.01"></label>
<label>multiply <input id="blend" type="checkbox"></label>
<div><button id="pPol">Политическая</button>
<button id="pRel">Рельеф</button></div>
<span class="dim">wheel = zoom, drag = pan</span>
</div>
<svg id="map" preserveAspectRatio="xMidYMid meet"></svg>
<script>
var D = __DATA__;
var NS = "http://www.w3.org/2000/svg";
var svg = document.getElementById("map");
var F = D.frame;                       // [x, y, w, h]
var TR = D.textureRect;                // texture rect, same units
var st = {cx: F[0] + F[2] / 2, cy: F[1] + F[3] / 2, w: F[3] * 1.35,
          relief: 0.75, own: 0.55, dim: 1.0, glow: 0.7, blend: true};

function el(name, attrs, parent) {
    var e = document.createElementNS(NS, name);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    (parent || svg).appendChild(e); return e;
}
function setView() {
    var h = st.w * innerHeight / innerWidth;
    svg.setAttribute("viewBox",
        (st.cx - st.w / 2) + " " + (st.cy - h / 2) + " " + st.w + " " + h);
}
function apply() {
    tex.style.opacity = st.relief;
    texD.style.opacity = st.relief * st.dim;
    gNat.style.opacity = st.own;
    gNat.style.mixBlendMode = st.blend ? "multiply" : "normal";
    glowP.style.opacity = st.glow;
    ["relief","own","dim","glow"].forEach(function(k){
        document.getElementById(k).value = st[k]; });
    document.getElementById("blend").checked = st.blend;
}
// layers ----------------------------------------------------------------
// inactive (unexplored / outside) sea = darkened sea colour, everywhere;
// playable seas are repainted in the normal sea colour on top.
var seaBg = el("rect", {x: D.viewBox[0], y: D.viewBox[1],
    width: D.viewBox[2], height: D.viewBox[3],
    fill: D.colors.inactiveSea});
var defs = el("defs", {});
var filt = el("filter", {id: "soft",
    x: "-40%", y: "-40%", width: "180%", height: "180%"}, defs);
el("feGaussianBlur", {stdDeviation: 0.9}, filt);
var gSea = el("g", {fill: D.colors.sea});
var keys = Object.keys(D.paths);
for (var i = 0; i < keys.length; i++)
    if (D.kinds[keys[i]] === 1)
        el("path", {d: D.paths[keys[i]]}, gSea);
el("path", {d: D.seaWater, fill: D.colors.sea}, gSea);
var glowP = el("path", {d: D.landOutline, fill: "none",
    stroke: "#9fc6dd", "stroke-width": 1.6, filter: "url(#soft)",
    opacity: st.glow});
var tex = el("image", {href: "relief_texture_16.webp",
    x: TR[0], y: TR[1], width: TR[2], height: TR[3],
    preserveAspectRatio: "none", opacity: st.relief});
var texD = el("image", {href: "relief_texture_16_dim.webp",
    x: TR[0], y: TR[1], width: TR[2], height: TR[3],
    preserveAspectRatio: "none", opacity: st.relief * st.dim});
var gNat = el("g", {opacity: st.own});
gNat.style.mixBlendMode = "multiply";
var gFree = el("g", {});
for (i = 0; i < keys.length; i++) {
    var id = keys[i];
    if (D.kinds[id] !== 0) continue;
    var n = D.nations[id];
    var col = n === undefined ? D.colors.neutral : D.nationColors[n];
    el("path", {d: D.paths[id], fill: col},
       n === undefined ? gFree : gNat);
}
gFree.setAttribute("opacity", 0.55);
var gBorder = el("g", {fill: "none", stroke: D.colors.border,
    "stroke-width": 1});
for (i = 0; i < keys.length; i++)
    el("path", {d: D.paths[keys[i]],
        "vector-effect": "non-scaling-stroke"}, gBorder);
// interaction ------------------------------------------------------------
var drag = null;
svg.addEventListener("pointerdown", function(e) {
    drag = {x: e.clientX, y: e.clientY, cx: st.cx, cy: st.cy};
    svg.setPointerCapture(e.pointerId); });
svg.addEventListener("pointermove", function(e) {
    if (!drag) return;
    var h = st.w * innerHeight / innerWidth;
    st.cx = drag.cx - (e.clientX - drag.x) * st.w / innerWidth;
    st.cy = drag.cy - (e.clientY - drag.y) * h / innerHeight;
    setView(); });
svg.addEventListener("pointerup", function() { drag = null; });
svg.addEventListener("wheel", function(e) {
    e.preventDefault();
    var z = Math.pow(1.0015, -e.deltaY);
    var r = svg.getBoundingClientRect();
    var fx = (e.clientX - r.left) / r.width, fy = (e.clientY - r.top) / r.height;
    var h = st.w * innerHeight / innerWidth;
    var px = st.cx - st.w / 2 + fx * st.w, py = st.cy - h / 2 + fy * h;
    var wMin = F[3] / D.zoomMax, wMax = F[3] * 1.6;
    st.w = Math.min(wMax, Math.max(wMin, st.w / z));
    var h2 = st.w * innerHeight / innerWidth;
    st.cx = px + (fx - 0.5) * st.w; st.cy = py + (fy - 0.5) * h2;
    setView(); }, {passive: false});
["relief","own","dim","glow"].forEach(function(k){
    document.getElementById(k).addEventListener("input", function(e){
        st[k] = parseFloat(e.target.value); apply(); }); });
document.getElementById("blend").addEventListener("change", function(e){
    st.blend = e.target.checked; apply(); });
var PRESETS = {
    pol:  {relief: 0.4,  own: 0.85, dim: 0.9,  glow: 0.35, blend: true},
    rel:  {relief: 1.0,  own: 0.18, dim: 0.55, glow: 0.85, blend: true}};
function preset(name) {
    for (var k in PRESETS[name]) st[k] = PRESETS[name][k]; apply(); }
document.getElementById("pPol").onclick = function(){ preset("pol"); };
document.getElementById("pRel").onclick = function(){ preset("rel"); };
// url hash: #cx=&cy=&w=&preset=pol|rel -----------------------------------
(function(){
    var h = location.hash.slice(1), kv = {};
    h.split("&").forEach(function(p){ var a = p.split("=");
        if (a.length === 2) kv[a[0]] = a[1]; });
    if (kv.preset) preset(kv.preset === "pol" ? "pol" : "rel");
    ["cx","cy","w"].forEach(function(k){ if (kv[k]) st[k] = +kv[k]; });
    ["relief","own","dim","glow"].forEach(function(k){
        if (kv[k] !== undefined) st[k] = +kv[k]; });
    if (kv.blend !== undefined) st.blend = kv.blend === "1";
    apply(); setView();
})();
window.addEventListener("resize", setView);
setView(); apply();
</script></body></html>
"""

if __name__ == "__main__":
    sys.exit(main())

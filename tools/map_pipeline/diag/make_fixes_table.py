"""map2_9b — export ``map_fixes_table.xlsx``, the decision table for the
Project Owner (straits, island links, detached clusters, seams).

Read-only: recomputes every figure from the current ``data/map/`` files and
writes ``tools/map_pipeline/reference/map_fixes_table.xlsx``. Same workbook
conventions as ``export_names.py`` (Cyrillic sheets, frozen header,
autofilter, yellow fill-in columns).

Run from the repository root::

    python -m tools.map_pipeline.diag.make_fixes_table
"""
from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from shapely import STRtree
from shapely.geometry import MultiPolygon, Point
from shapely.ops import nearest_points, unary_union

from tools.map_pipeline.diag.common import (
    REF,
    load_geometry,
    load_manifest,
    node_geom,
    node_parts,
    nodes_by_id,
    sea_name,
)

OUT = REF / "map_fixes_table.xlsx"

KM_PER_U = 23.0
MAX_GAP = 1.5          # candidate scan window, u
MEDIUM_MAX = 0.8       # medium class upper bound
CLUSTER_GAP = 0.5      # parts closer than this form one cluster
FAR_CLUSTER = 3.0      # cluster "far from main body"
TOUCH_EPS = 0.05       # gap <= this counts as touching
SEAM_EPS = 0.03        # boundaries closer than this count as coincident
SEAM_MIN_LEN = 0.05    # shared run must be at least this long

_HEADER_FILL = PatternFill("solid", fgColor="D9E1F2")
_YELLOW_HEADER = PatternFill("solid", fgColor="FFD966")
_YELLOW_CELL = PatternFill("solid", fgColor="FFF2CC")

APPROVED_PAIRS = {
    frozenset(("constantinople", "kocaeli")),
    frozenset(("dardanelles", "biga")),
    frozenset(("cafa", "taman")),
}

# Owner decisions already taken (map2_9 report).
PREFILL_DETACH = {  # (node_key, discriminating sea zone) -> new names
    ("northern_isles", "Море у Фарер"): ("отделить", "Faroe Islands", "Торсхавн"),
}
PREFILL_TRANSFER = {  # cluster of this node touching this target -> target name
    ("lancashire", "teviotdale"): "Хоик",
    ("lancashire", "northumberland"): "Ньюкасл-апон-Тайн",
}


def _u(geom_a, geom_b) -> float:
    return geom_a.distance(geom_b)


def _shared_len(a, b, eps: float = SEAM_EPS) -> float:
    return b.boundary.intersection(a.boundary.buffer(eps)).length


def _water_at(midpoint, sea_geoms, land_geoms, own_ids):
    for nid, geom in sea_geoms.items():
        if geom.distance(midpoint) == 0:
            return ("sea", nid)
    for nid, geom in land_geoms.items():
        if nid in own_ids:
            continue
        if geom.distance(midpoint) == 0:
            return ("land", nid)
    best = min(
        ((g.distance(midpoint), nid) for nid, g in sea_geoms.items()),
        default=None,
    )
    if best and best[0] <= 1.0:
        return ("sea", best[1])
    return ("none", None)


def _seas_touched(geom, sea_geoms, by_id, eps: float = 0.5):
    return {
        sea_name(by_id[nid])
        for nid, g in sea_geoms.items()
        if geom.distance(g) <= eps
    }


def _cluster_parts(parts, gap: float = CLUSTER_GAP):
    """Group polygon parts: two parts closer than ``gap`` share a cluster."""
    clusters: list[list[int]] = []
    for i in range(len(parts)):
        placed = False
        for cl in clusters:
            if any(parts[i].distance(parts[j]) <= gap for j in cl):
                cl.append(i)
                placed = True
                break
        if not placed:
            clusters.append([i])
    # transitive merge (A-B and B-C share a cluster even if A-C > gap)
    merged = True
    while merged:
        merged = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                if any(
                    parts[a].distance(parts[b]) <= gap
                    for a in clusters[i]
                    for b in clusters[j]
                ):
                    clusters[i] += clusters[j]
                    del clusters[j]
                    merged = True
                    break
            if merged:
                break
    return clusters


def _style_sheet(ws, headers, widths, fill_cols, rows, note=None):
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)
        cell.fill = _YELLOW_HEADER if header in fill_cols else _HEADER_FILL
        ws.column_dimensions[get_column_letter(col)].width = widths.get(
            header, 16
        )
    for row_idx, row in enumerate(rows, start=2):
        for col, value in enumerate(row, start=1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            if headers[col - 1] in fill_cols:
                cell.fill = _YELLOW_CELL
            if isinstance(value, float):
                cell.number_format = "0.00"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = (
        f"A1:{get_column_letter(len(headers))}{max(1, len(rows) + 1)}"
    )
    if note:
        ws.cell(row=len(rows) + 3, column=1, value=note)


def main() -> int:
    manifest = load_manifest()
    geometry = load_geometry()
    by_id = nodes_by_id(manifest)
    by_key = {n["key"]: n for n in manifest["nodes"]}
    edges = {(e["a"], e["b"]): e for e in manifest["edges"]}

    land_ids = [n["id"] for n in manifest["nodes"] if n["kind"] == "LAND"]
    sea_ids = [n["id"] for n in manifest["nodes"] if n["kind"] == "SEA"]
    land_geoms = {i: node_geom(geometry, i) for i in land_ids}
    sea_geoms = {i: node_geom(geometry, i) for i in sea_ids}

    # ------------------------------------------------ sheet 1: Проливы
    straits_rows = []
    tree = STRtree(list(land_geoms.values()))
    id_list = list(land_geoms)
    for i, nid in enumerate(id_list):
        for j in tree.query(
            land_geoms[nid], predicate="dwithin", distance=MAX_GAP
        ):
            oid = id_list[j]
            if oid <= nid:
                continue
            e = edges.get((nid, oid))
            if e is not None and e["type"] == "land":
                continue
            d = land_geoms[nid].distance(land_geoms[oid])
            if d > MEDIUM_MAX:
                continue  # wide pairs are not on this decision sheet
            pa, pb = nearest_points(land_geoms[nid], land_geoms[oid])
            mid = Point((pa.x + pb.x) / 2, (pa.y + pb.y) / 2)
            kind, wid = _water_at(mid, sea_geoms, land_geoms, {nid, oid})
            if kind != "sea":
                continue
            a, b = by_id[nid], by_id[oid]
            cls = "narrow" if d <= 0.3 else "medium"
            pair = frozenset((a["key"], b["key"]))
            already = e is not None and e["type"] == "strait"
            if pair in APPROVED_PAIRS:
                add, comment = "да", "одобрено (Босфор/Дарданеллы/Керчь)"
            elif already:
                add, comment = "нет", "связь уже есть в overrides.yaml"
            elif cls == "narrow":
                add, comment = "да", ""
            else:
                add, comment = "", ""
            straits_rows.append(
                [
                    a["key"], a.get("name_ru") or a["name"] or "",
                    b["key"], b.get("name_ru") or b["name"] or "",
                    sea_name(by_id[wid]),
                    round(d, 3),
                    int(round(d * KM_PER_U)),
                    cls,
                    "да" if already else "нет",
                    add,
                    "",
                    comment,
                ]
            )
    straits_rows.sort(key=lambda r: (r[6] != "narrow", r[5]))
    n_pairs = len(straits_rows)

    # islands without any land/strait edge
    connected = set()
    for e in manifest["edges"]:
        if e["type"] in ("land", "strait"):
            connected.add(e["a"])
            connected.add(e["b"])
    island_rows = []
    for n in manifest["nodes"]:
        if n["kind"] != "LAND" or n["id"] in connected:
            continue
        g = land_geoms[n["id"]]
        best = min(
            (
                (g.distance(land_geoms[o]), o)
                for o in land_ids
                if o != n["id"]
            )
        )
        d, oid = best
        o = by_id[oid]
        pa, pb = nearest_points(g, land_geoms[oid])
        mid = Point((pa.x + pb.x) / 2, (pa.y + pb.y) / 2)
        kind, wid = _water_at(mid, sea_geoms, land_geoms, {n["id"], oid})
        island_rows.append(
            [
                n["key"], n.get("name_ru") or n["name"] or "",
                o["key"], o.get("name_ru") or o["name"] or "",
                sea_name(by_id[wid]) if kind == "sea" else "-",
                round(d, 3),
                int(round(d * KM_PER_U)),
                "wide" if d > MEDIUM_MAX else "narrow" if d <= 0.3 else "medium",
                "нет",
                "",
                "",
                "ОСТРОВ без связей — сейчас недоступен для стартовой группы",
            ]
        )
    island_rows.sort(key=lambda r: r[5])

    straits_header = [
        "key1", "name_ru1", "key2", "name_ru2", "water", "distance_u",
        "distance_km", "class", "already_strait", "добавить (да/нет)",
        "штраф (необязательно)", "comment",
    ]
    widths1 = {
        "key1": 20, "name_ru1": 22, "key2": 20, "name_ru2": 22,
        "water": 22, "distance_u": 11, "distance_km": 12, "class": 10,
        "already_strait": 13, "добавить (да/нет)": 16,
        "штраф (необязательно)": 20, "comment": 40,
    }
    all_rows = straits_rows + [
        ["— ОСТРОВА БЕЗ СВЯЗЕЙ —"] + [""] * (len(straits_header) - 1)
    ] + island_rows

    # ------------------------------------------------ sheet 2: Куски
    parts_rows = []
    for n in manifest["nodes"]:
        if n["kind"] != "LAND":
            continue
        parts = node_parts(geometry, n["id"])
        if len(parts) < 2:
            continue
        clusters = _cluster_parts(parts)
        if len(clusters) < 2:
            continue
        cluster_geom = {
            ci: unary_union([parts[i] for i in cl])
            for ci, cl in enumerate(clusters)
        }
        clusters = {ci: cl for ci, cl in enumerate(clusters)}
        areas = {ci: g.area for ci, g in cluster_geom.items()}
        main_ci = max(areas, key=lambda ci: (areas[ci], -ci))
        main_geom = cluster_geom[main_ci]
        main_seas = _seas_touched(main_geom, sea_geoms, by_id)
        cluster_no = {
            ci: rank + 1
            for rank, ci in enumerate(
                sorted(areas, key=lambda ci: (-areas[ci], ci))
            )
        }
        for ci, cl in clusters.items():
            if ci == main_ci:
                continue
            g = cluster_geom[ci]
            dist_main = g.distance(main_geom)
            seas = _seas_touched(g, sea_geoms, by_id)
            if dist_main < FAR_CLUSTER and seas <= main_seas:
                continue  # cluster is close and in the same seas — normal
            # best neighbour: max shared boundary, else nearest
            scored = []
            for oid in land_ids:
                if oid == n["id"]:
                    continue
                og = land_geoms[oid]
                gap = g.distance(og)
                if gap > MAX_GAP:
                    continue
                scored.append(
                    (min(_shared_len(g, og), _shared_len(og, g)), -gap, oid)
                )
            scored.sort(key=lambda t: (-t[0], t[1], t[2]))
            if scored:
                shared, neg_gap, best_id = scored[0]
            else:
                best_id = min(
                    (o for o in land_ids if o != n["id"]),
                    key=lambda o: (g.distance(land_geoms[o]), o),
                )
                shared = 0.0
                neg_gap = -g.distance(land_geoms[best_id])
            gap = -neg_gap
            best = by_id[best_id]
            rp = max(
                (parts[i] for i in cl), key=lambda p: p.area
            ).representative_point()
            decision, target, new_lat, new_ru = "", "", "", ""
            for (k, sea_ru), (dec, lat, ru) in PREFILL_DETACH.items():
                if n["key"] == k and sea_ru in seas:
                    decision, new_lat, new_ru = dec, lat, ru
            for (k, tkey), tname in PREFILL_TRANSFER.items():
                if n["key"] == k and best["key"] == tkey:
                    decision, target = "передать", tname
            comment = ""
            if decision == "передать" and gap > TOUCH_EPS:
                comment = f"НЕ касается цели, зазор {gap:.2f} u"
            parts_rows.append(
                [
                    n["key"], n.get("name_ru") or n["name"] or "",
                    cluster_no[ci], len(cl),
                    round(g.area, 3), round(main_geom.area, 3),
                    round(dist_main, 2),
                    "; ".join(sorted(seas)) or "-",
                    f"({rp.x:.2f}; {rp.y:.2f})",
                    best["key"], best.get("name_ru") or best["name"] or "",
                    round(shared, 3), round(gap, 3),
                    "да" if gap <= TOUCH_EPS else "нет",
                    decision, target, new_lat, new_ru, comment,
                ]
            )
    parts_rows.sort(key=lambda r: r[4])  # area_u2 ascending

    parts_header = [
        "key", "name_ru", "cluster_no", "parts", "area_u2",
        "main_body_area_u2", "distance_to_main_u", "sea_zones",
        "representative_point", "best_neighbour_key",
        "best_neighbour_name_ru", "shared_len_u", "gap_to_best_u",
        "touches_best", "решение", "кому передать (название)",
        "новое название (лат.)", "новое название (рус.)", "comment",
    ]
    widths2 = {
        "key": 20, "name_ru": 22, "cluster_no": 11, "parts": 8,
        "area_u2": 10, "main_body_area_u2": 17, "distance_to_main_u": 18,
        "sea_zones": 34, "representative_point": 20,
        "best_neighbour_key": 20, "best_neighbour_name_ru": 22,
        "shared_len_u": 12, "gap_to_best_u": 13, "touches_best": 12,
        "решение": 14, "кому передать (название)": 24,
        "новое название (лат.)": 20, "новое название (рус.)": 20,
        "comment": 36,
    }

    # ------------------------------------------------ sheet 3: Швы
    seam_rows = []
    for n in manifest["nodes"]:
        if n["kind"] != "LAND":
            continue
        parts = node_parts(geometry, n["id"])
        if len(parts) < 2:
            continue
        best = 0.0
        for i in range(len(parts)):
            for j in range(i + 1, len(parts)):
                best = max(
                    best,
                    _shared_len(parts[i], parts[j]),
                    _shared_len(parts[j], parts[i]),
                )
        if best >= SEAM_MIN_LEN:
            seam_rows.append(
                [
                    n["key"], n.get("name_ru") or n["name"] or "",
                    round(best, 3), len(parts),
                ]
            )
    seam_rows.sort(key=lambda r: -r[2])
    seam_header = ["key", "name_ru", "seam_len_u", "parts"]
    widths3 = {"key": 22, "name_ru": 24, "seam_len_u": 12, "parts": 8}

    # ------------------------------------------------ sheet 4: Как заполнять
    help_lines = [
        "Жёлтые столбцы заполняете вы; остальные — справочно.",
        "Лист «Проливы»: «добавить» = да/нет — добавить ли переправу через пролив; «штраф» — число 0.05–1.0, пусто = стандартный штраф 0.5 (как у 16 существующих проливов).",
        "Ниже разделителя — острова без связей: без пролива они недоступны для стартовой группы; «key2» — ближайший сосед, предложенный автоматически.",
        "Лист «Куски»: «решение» = оставить / отделить / передать. «Отделить» — кусок станет новой провинцией (тогда заполните «новое название» лат. и рус.). «Передать» — кусок уйдёт соседу (тогда заполните «кому передать» русским названием).",
        "«best_neighbour_*», «shared_len_u», «gap_to_best_u», «touches_best» — сосед, с которым у куска самая длинная общая граница; touches_best=«нет» означает зазор — передача потребует уточнения границы.",
        "Лист «Швы» — только для сведения: эти узлы чинит пайплайн автоматически, заполнять не нужно.",
        "Когда закончите — прикрепите этот файл в чат; Lead Developer напишет задачи на правку.",
    ]
    help_rows = [[line] for line in help_lines]

    # ------------------------------------------------ write workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Проливы"
    _style_sheet(
        ws, straits_header, widths1,
        {"добавить (да/нет)", "штраф (необязательно)"},
        all_rows,
    )
    ws2 = wb.create_sheet("Куски")
    _style_sheet(
        ws2, parts_header, widths2,
        {"решение", "кому передать (название)", "новое название (лат.)",
         "новое название (рус.)"},
        parts_rows,
    )
    ws3 = wb.create_sheet("Швы")
    _style_sheet(
        ws3, seam_header, widths3, set(), seam_rows,
        note="Эти узлы исправляются автоматически правкой пайплайна "
             "(map2_9, Issue C: части одного узла, чьи границы совпадают "
             "≥ 0.05 u, станут одним кольцом). Заполнять ничего не нужно.",
    )
    ws4 = wb.create_sheet("Как заполнять")
    ws4.column_dimensions["A"].width = 140
    for i, (line,) in enumerate(help_rows, start=1):
        ws4.cell(row=i, column=1, value=line)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)

    print(f"Проливы: {n_pairs} пар + {len(island_rows)} островов")
    print(f"Куски: {len(parts_rows)} кластеров")
    print(f"Швы: {len(seam_rows)} узлов")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

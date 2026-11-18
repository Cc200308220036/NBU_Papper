"""从 build_dataset.py 提取并冻结的 V0.1 几何判定逻辑，不执行数据读写。"""
from __future__ import annotations
import copy, math, statistics, hashlib, json
from time import perf_counter
from collections import defaultdict, Counter
from typing import Any, Iterable
def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def digest(value: Any, length: int = 16) -> str:
    raw = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]

def overlap_1d(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))

def footprint_overlap(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, tuple[float, float, float, float] | None]:
    x0 = max(a["x0"], b["x0"])
    x1 = min(a["x1"], b["x1"])
    y0 = max(a["y0"], b["y0"])
    y1 = min(a["y1"], b["y1"])
    if x1 <= x0 or y1 <= y0:
        return 0.0, None
    return (x1 - x0) * (y1 - y0), (x0, x1, y0, y1)

def rectangle_union_area(rectangles: Iterable[tuple[float, float, float, float]]) -> float:
    rectangles = list(rectangles)
    if not rectangles:
        return 0.0
    xs = sorted({r[0] for r in rectangles} | {r[1] for r in rectangles})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        if right <= left:
            continue
        intervals = sorted((r[2], r[3]) for r in rectangles if r[0] < right and r[1] > left)
        covered = 0.0
        if intervals:
            lo, hi = intervals[0]
            for start, end in intervals[1:]:
                if start > hi:
                    covered += hi - lo
                    lo, hi = start, end
                else:
                    hi = max(hi, end)
            covered += hi - lo
        area += (right - left) * covered
    return area

def boxes_overlap_3d(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (
        overlap_1d(a["x0"], a["x1"], b["x0"], b["x1"]) > 0
        and overlap_1d(a["y0"], a["y1"], b["y0"], b["y1"]) > 0
        and overlap_1d(a["z0"], a["z1"], b["z0"], b["z1"]) > 0
    )

def propagate_load(
    support_fractions: list[tuple[str, float]],
    load_kg: float,
    placed_by_id: dict[str, dict[str, Any]],
    increments: defaultdict[str, float],
) -> None:
    for support_id, fraction in support_fractions:
        amount = load_kg * fraction
        increments[support_id] += amount
        support = placed_by_id[support_id]
        propagate_load(support["supports"], amount, placed_by_id, increments)

def candidate_points(placed: list[dict[str, Any]], box_l: int, box_w: int, c: dict[str, Any]) -> list[tuple[float, float, float]]:
    xmin, ymin = -c["length_mm"] / 2, -c["width_mm"] / 2
    xmax, ymax = c["length_mm"] / 2, c["width_mm"] / 2
    z_levels = {0.0} | {p["z1"] for p in placed}
    result: set[tuple[float, float, float]] = set()
    for z in z_levels:
        if z == 0:
            xs = {xmin, xmax - box_l}
            ys = {ymin, ymax - box_w}
            for p in placed:
                xs.update((p["x1"], p["x0"] - box_l))
                ys.update((p["y1"], p["y0"] - box_w))
        else:
            supports = [p for p in placed if p["z1"] == z]
            if not supports:
                continue
            xs = {xmin, xmax - box_l}
            ys = {ymin, ymax - box_w}
            for p in supports:
                xs.update((p["x0"], p["x1"] - box_l, p["x1"], p["x0"] - box_l))
                ys.update((p["y0"], p["y1"] - box_w, p["y1"], p["y0"] - box_w))
        for x0 in xs:
            for y0 in ys:
                result.add((x0, y0, z))
    return sorted(result)

def evaluate_pose(
    item: dict[str, Any],
    placed: list[dict[str, Any]],
    x0: float,
    y0: float,
    z0: float,
    box_l: int,
    box_w: int,
    yaw: int,
    config: dict[str, Any],
    _timing: dict | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    started = perf_counter()
    def reject(reason):
        if _timing is not None:
            _timing["filter"] = perf_counter() - started
        return None, reason
    c = config["container"]
    box_h = item["dimensions"][2]
    record = {
        "item_id": item["item_id"],
        "item": item,
        "x0": x0,
        "x1": x0 + box_l,
        "y0": y0,
        "y1": y0 + box_w,
        "z0": z0,
        "z1": z0 + box_h,
        "yaw": yaw,
        "supports": [],
        "supported_load_kg": 0.0,
    }
    xmin, ymin = -c["length_mm"] / 2, -c["width_mm"] / 2
    xmax, ymax = c["length_mm"] / 2, c["width_mm"] / 2
    if z0 < 0 or record["x0"] < xmin or record["x1"] > xmax or record["y0"] < ymin or record["y1"] > ymax or record["z1"] > c["max_height_mm"]:
        return reject("out_of_bounds")
    if sum(p["item"]["mass_kg"] for p in placed) + item["mass_kg"] > c["max_payload_kg"]:
        return reject("over_payload")
    if any(boxes_overlap_3d(record, p) for p in placed):
        return reject("overlap")

    support_ratio = 1.0
    com_margin = min(box_l, box_w) / 2
    support_ids: list[str] = []
    support_fractions: list[tuple[str, float]] = []
    increments: defaultdict[str, float] = defaultdict(float)
    if z0 > 0:
        support_data = []
        for p in placed:
            if p["z1"] != z0:
                continue
            area, rect = footprint_overlap(record, p)
            if area > 0 and rect is not None:
                support_data.append((p, area, rect))
        union_area = rectangle_union_area(x[2] for x in support_data)
        support_ratio = union_area / (box_l * box_w)
        if support_ratio + 1e-9 < config["support_ratio_min"]:
            return reject("insufficient_support")
        cx, cy = x0 + box_l / 2, y0 + box_w / 2
        containing = [rect for _, _, rect in support_data if rect[0] <= cx <= rect[1] and rect[2] <= cy <= rect[3]]
        if not containing:
            return reject("com_outside_support")
        com_margin = max(min(cx - r[0], r[1] - cx, cy - r[2], r[3] - cy) for r in containing)
        if any(not p["item"]["stackable"] for p, _, _ in support_data):
            return reject("non_stackable_support")
        total_overlap = sum(area for _, area, _ in support_data)
        support_fractions = [(p["item_id"], area / total_overlap) for p, area, _ in support_data]
        support_ids = [x[0] for x in support_fractions]
        placed_by_id = {p["item_id"]: p for p in placed}
        propagate_load(support_fractions, item["mass_kg"], placed_by_id, increments)
        for support_id, extra in increments.items():
            support = placed_by_id[support_id]
            if support["supported_load_kg"] + extra > support["item"]["top_load_limit_kg_synthetic"] + 1e-9:
                return reject("overload")

    record["supports"] = support_fractions
    after = [copy.deepcopy(p) for p in placed]
    after_by_id = {p["item_id"]: p for p in after}
    for support_id, extra in increments.items():
        after_by_id[support_id]["supported_load_kg"] += extra
    after.append(copy.deepcopy(record))

    filtered = perf_counter()
    if _timing is not None:
        _timing["filter"] = filtered - started
    total_volume = sum(math.prod(p["item"]["dimensions"]) for p in after)
    min_x, max_x = min(p["x0"] for p in after), max(p["x1"] for p in after)
    min_y, max_y = min(p["y0"] for p in after), max(p["y1"] for p in after)
    max_z = max(p["z1"] for p in after)
    envelope_volume = max((max_x - min_x) * (max_y - min_y) * max_z, 1.0)
    compactness = min(1.0, total_volume / envelope_volume)
    height_score = max(0.0, 1.0 - max_z / c["max_height_mm"])
    total_mass = sum(p["item"]["mass_kg"] for p in after)
    com_x = sum(((p["x0"] + p["x1"]) / 2) * p["item"]["mass_kg"] for p in after) / total_mass
    com_y = sum(((p["y0"] + p["y1"]) / 2) * p["item"]["mass_kg"] for p in after) / total_mass
    com_offset = math.hypot(com_x, com_y)
    max_offset = math.hypot(c["length_mm"] / 2, c["width_mm"] / 2)
    balance = max(0.0, 1.0 - com_offset / max_offset)
    stability = min(1.0, support_ratio)
    components = {
        "compactness": round(compactness, 6),
        "height": round(height_score, 6),
        "stability": round(stability, 6),
        "balance": round(balance, 6),
    }
    weights = config["candidate_generator"]["geometry_score_weights"]
    geometry_score = sum(components[k] * weights[k] for k in weights)
    remaining = [
        after_by_id[sid]["item"]["top_load_limit_kg_synthetic"]
        - after_by_id[sid]["supported_load_kg"]
        for sid in support_ids
    ]
    fingerprint_payload = {"item": item["item_id"], "x0": x0, "y0": y0, "z0": z0, "yaw": yaw}
    fp = digest(fingerprint_payload, 24)
    visible = {
        "candidate_id": f"cand_{fp[:12]}",
        "candidate_fingerprint": fp,
        "pick_item_id": item["item_id"],
        "pose": {
            "x_mm": round(x0 + box_l / 2, 3),
            "y_mm": round(y0 + box_w / 2, 3),
            "z_base_mm": round(z0, 3),
            "yaw_deg": yaw,
        },
        "oriented_size_mm": [box_l, box_w, box_h],
        "ems": {"ems_id": f"ems_{digest((x0, y0, z0), 10)}", "ems_type": "floor_space" if z0 == 0 else "supported_space"},
        "support": {
            "support_item_ids": support_ids,
            "support_ratio": round(support_ratio, 6),
            "com_margin_mm": round(com_margin, 3),
        },
        "load": {
            "downward_load_kg": 0.0,
            "minimum_remaining_capacity_kg": round(min(remaining), 3) if remaining else None,
        },
        "resulting_geometry": {
            "max_height_mm": round(max_z, 3),
            "volume_utilization": round(total_volume / (c["length_mm"] * c["width_mm"] * c["max_height_mm"]), 6),
            "center_of_mass_offset_mm": round(com_offset, 3),
        },
        "geometry_score_components": components,
        "physical_valid": True,
        "physical_rejection_reasons": [],
    }
    if _timing is not None:
        _timing["score"] = perf_counter() - filtered
    return {
        "visible": visible,
        "geometry_score": round(geometry_score, 9),
        "stratum": (
            "floor" if z0 == 0 else "upper",
            "center" if abs(visible["pose"]["x_mm"]) < c["length_mm"] / 4 and abs(visible["pose"]["y_mm"]) < c["width_mm"] / 4 else "edge",
            min(len(support_ids), 2),
            item["item_id"],
        ),
        "record": record,
        "load_increments": dict(increments),
        "result_state": after,
    }, None

def pareto_front(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = ("compactness", "height", "stability", "balance")
    result = []
    for candidate in candidates:
        a = candidate["visible"]["geometry_score_components"]
        dominated = False
        for other in candidates:
            if other is candidate:
                continue
            b = other["visible"]["geometry_score_components"]
            if all(b[k] >= a[k] for k in keys) and any(b[k] > a[k] for k in keys):
                dominated = True
                break
        if not dominated:
            result.append(candidate)
    return result

def select_diverse_topk(candidates: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    ordered = sorted(candidates, key=lambda x: (-x["geometry_score"], x["visible"]["candidate_id"]))
    best_by_stratum: dict[tuple[Any, ...], dict[str, Any]] = {}
    for candidate in ordered:
        best_by_stratum.setdefault(candidate["stratum"], candidate)
    selected = sorted(best_by_stratum.values(), key=lambda x: -x["geometry_score"])[:k]
    selected_ids = {id(x) for x in selected}
    for candidate in ordered:
        if len(selected) >= k:
            break
        if id(candidate) not in selected_ids:
            selected.append(candidate)
            selected_ids.add(id(candidate))
    return selected

def commit_candidate(candidate: dict[str, Any], placed: list[dict[str, Any]]) -> None:
    by_id = {p["item_id"]: p for p in placed}
    for support_id, extra in candidate["load_increments"].items():
        by_id[support_id]["supported_load_kg"] += extra
    placed.append(copy.deepcopy(candidate["record"]))

def visible_placed(placed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for p in placed:
        record = public_item(p["item"])
        record.update(
            {
                "item_id": p["item_id"],
                "pose": {
                    "x_mm": round((p["x0"] + p["x1"]) / 2, 3),
                    "y_mm": round((p["y0"] + p["y1"]) / 2, 3),
                    "z_base_mm": round(p["z0"], 3),
                    "yaw_deg": p["yaw"],
                },
                "oriented_size_mm": [round(p["x1"] - p["x0"], 3), round(p["y1"] - p["y0"], 3), round(p["z1"] - p["z0"], 3)],
                "supported_load_kg": round(p["supported_load_kg"], 3),
                "support_fractions": [
                    {"item_id": support_id, "fraction": round(fraction, 9)}
                    for support_id, fraction in p["supports"]
                ],
            }
        )
        result.append(record)
    return result

def public_item(item: dict[str, Any]) -> dict[str, Any]:
    l, w, h = item["dimensions"]
    return {
        "item_id": item["item_id"],
        "geometry_id": item["geometry_id"],
        "dimensions_mm": {"length": l, "width": w, "height": h},
        "mass_kg": item["mass_kg"],
        "weight_class": item["weight_class"],
        "material": item["material"],
        "fragile": item["fragile"],
        "stackable": item["stackable"],
        "top_load_limit_kg_synthetic": item["top_load_limit_kg_synthetic"],
        "product_category": item["product_category"],
    }

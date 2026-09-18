#!/usr/bin/env python3
"""生成可复现的语义码垛数据集 MVD-v0.1。

本实现只依赖Python标准库。它是一个可审计的基准候选生成器，并不表示复现了
完整GOPT算法。程序从EMS-style极值点产生几何候选，再按照数据集设计中的通用
物理约束进行过滤。
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import shutil
import statistics
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
DEFAULT_CONFIG = ROOT / "configs" / "mvd_v0.1.json"
DEFAULT_BED = WORKSPACE / "raw" / "bed_bpp" / "bed-bpp_v1.json"
DEFAULT_MIXED = (
    WORKSPACE
    / "raw"
    / "mixed_pallet_boxes"
    / "MixedPalletBoxes-v1.0"
)
GENERATED_DIRS = (
    "catalog",
    "tasks",
    "candidates",
    "annotations",
    "streams",
    "splits",
    "statistics",
    "provenance",
)

MATERIALS = ["Cardboard", "Plastic", "Wood", "Metal", "Composite"]
MATERIAL_WEIGHTS = [0.55, 0.25, 0.10, 0.05, 0.05]
THICKNESS_OPTIONS = {
    "Cardboard": [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50],
    "Plastic": [0.20, 0.40, 0.60],
    "Wood": [0.30, 0.60, 1.00],
    "Metal": [0.10, 0.20, 0.30],
    "Composite": [0.20, 0.40, 0.60, 0.80],
}
FRAGILE_PROBS = {
    "Cardboard": 0.30,
    "Plastic": 0.10,
    "Wood": 0.10,
    "Metal": 0.10,
    "Composite": 0.30,
}
STACKABLE_PROBS = {
    "Cardboard": 0.65,
    "Plastic": 0.85,
    "Wood": 0.75,
    "Metal": 0.95,
    "Composite": 0.65,
}
LOAD_MULTIPLIERS = {
    "Cardboard": 2.5,
    "Plastic": 5.5,
    "Wood": 6.5,
    "Metal": 12.0,
    "Composite": 8.0,
}

RULES = [
    {
        "rule_type": "heavy_low",
        "target_attribute": "weight_class=heavy",
        "priority": 1,
        "hard_or_soft": "soft",
        "thresholds": {},
        "canonical": "重物应尽量放在较低层。",
        "paraphrases": ["优先把较重的箱子安排在底部附近。", "请避免将重箱码放得过高。"],
    },
    {
        "rule_type": "heavy_center",
        "target_attribute": "weight_class=heavy",
        "priority": 1,
        "hard_or_soft": "soft",
        "thresholds": {},
        "canonical": "重物应尽量靠近托盘底面中心。",
        "paraphrases": ["把较重货物优先放到码垛区中央。", "重箱不要过度偏向托盘边缘。"],
    },
    {
        "rule_type": "fragile_protect",
        "target_attribute": "fragile=true",
        "priority": 1,
        "hard_or_soft": "soft",
        "thresholds": {},
        "canonical": "易碎箱应尽量不承载其他箱体，并优先放在较高层。",
        "paraphrases": ["保护易碎品，尽量别在它们上面压货。", "易碎货物宜放高一些并减少顶部载荷。"],
    },
    {
        "rule_type": "category_group",
        "target_attribute": "product_category=electronics",
        "priority": 1,
        "hard_or_soft": "soft",
        "thresholds": {},
        "canonical": "电子产品箱应尽量集中码放。",
        "paraphrases": ["请把电子类货箱放得相对集中。", "尽量不要把电子产品分散在托盘各处。"],
    },
    {
        "rule_type": "category_separate",
        "target_attribute": "product_category=electronics",
        "priority": 1,
        "hard_or_soft": "hard",
        "thresholds": {"separate_from": "weight_class=heavy", "contact_tolerance_mm": 0},
        "canonical": "电子产品箱不得与重物箱直接接触或形成上下支撑关系。",
        "paraphrases": ["必须将电子货箱和重箱隔开，不能相互贴靠或叠放。", "电子产品不可直接邻接重物，也不能与重物上下承托。"],
    },
]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any, length: int = 16) -> str:
    raw = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def stable_unit(seed: int, *parts: Any) -> float:
    raw = "|".join(str(x) for x in (seed, *parts))
    return int(hashlib.sha256(raw.encode()).hexdigest()[:16], 16) / float(16**16)


def rng_for(seed: int, *parts: Any) -> random.Random:
    raw = "|".join(str(x) for x in (seed, *parts))
    return random.Random(int(hashlib.sha256(raw.encode()).hexdigest()[:16], 16))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def portable_path(path: Path) -> str:
    """优先记录工作区相对路径，避免数据集换目录后清单内容变化。"""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(WORKSPACE.resolve()))
    except ValueError:
        return str(resolved)


def weighted_choice(u: float, values: list[str], weights: list[float]) -> str:
    total = 0.0
    for value, weight in zip(values, weights):
        total += weight
        if u < total:
            return value
    return values[-1]


def source_attributes(article_id: str, dims: tuple[int, int, int], seed: int) -> dict[str, Any]:
    material = weighted_choice(stable_unit(seed, article_id, "material"), MATERIALS, MATERIAL_WEIGHTS)
    thicknesses = THICKNESS_OPTIONS[material]
    thickness = thicknesses[int(stable_unit(seed, article_id, "thickness") * len(thicknesses)) % len(thicknesses)]
    volume_l = dims[0] * dims[1] * dims[2] / 1_000_000.0
    capacity = min(volume_l * thickness * LOAD_MULTIPLIERS[material], 500.0)
    fragile = stable_unit(seed, article_id, "fragile") < FRAGILE_PROBS[material]
    stackable = stable_unit(seed, article_id, "stackable") < STACKABLE_PROBS[material]
    electronics = stable_unit(seed, article_id, "electronics") < 0.25
    return {
        "material": material,
        "fragile": fragile,
        "stackable": stackable,
        "top_load_limit_kg_synthetic": round(capacity, 2),
        "product_category": "electronics" if electronics else "general",
    }


def geometry_id(dims: tuple[int, int, int]) -> str:
    horizontal = sorted(dims[:2], reverse=True)
    return f"G_{horizontal[0]}x{horizontal[1]}x{dims[2]}"


def normalize_source_item(raw: dict[str, Any], seed: int, tall_threshold: int) -> dict[str, Any]:
    dims = (int(raw["length/mm"]), int(raw["width/mm"]), int(raw["height/mm"]))
    attrs = source_attributes(str(raw["id"]), dims, seed)
    return {
        "source_article_id": str(raw["id"]),
        "source_sequence": int(raw["sequence"]),
        "source_product_group": str(raw.get("product_group", "unknown")),
        "dimensions": dims,
        "mass_kg": float(raw["weight/kg"]),
        "geometry_id": geometry_id(dims),
        "geometry_cluster_id": "tall" if dims[2] >= tall_threshold else "regular",
        **attrs,
    }


def semantic_combo(item: dict[str, Any]) -> bool:
    return bool(item["fragile"] and item["product_category"] == "electronics")


def choose_order_window(
    raw_items: list[dict[str, Any]],
    split: str,
    config: dict[str, Any],
    seed: int,
    order_key: str,
) -> list[dict[str, Any]] | None:
    c = config["container"]
    min_n = config["items_per_scenario"]["min"]
    max_n = config["items_per_scenario"]["max"]
    min_ratio = config["target_volume_ratio"]["min"]
    max_ratio = config["target_volume_ratio"]["max"]
    min_ood = config["geometry_ood"]["minimum_ood_items"]
    min_sem = config["semantic_ood"]["minimum_ood_items"]
    container_volume = c["length_mm"] * c["width_mm"] * c["max_height_mm"]

    physically_fit = [
        item
        for item in raw_items
        if item["dimensions"][2] <= c["max_height_mm"]
        and (
            (item["dimensions"][0] <= c["length_mm"] and item["dimensions"][1] <= c["width_mm"])
            or (item["dimensions"][1] <= c["length_mm"] and item["dimensions"][0] <= c["width_mm"])
        )
    ]
    if split == "test_geometry_ood":
        eligible = [item for item in physically_fit if not semantic_combo(item)]
    elif split == "test_semantic_ood":
        eligible = [item for item in physically_fit if item["geometry_cluster_id"] == "regular"]
    else:
        eligible = [
            item
            for item in physically_fit
            if item["geometry_cluster_id"] == "regular" and not semantic_combo(item)
        ]

    windows: list[list[dict[str, Any]]] = []
    for n in range(min_n, min(max_n, len(eligible)) + 1):
        for start in range(0, len(eligible) - n + 1):
            window = eligible[start : start + n]
            ratio = sum(math.prod(item["dimensions"]) for item in window) / container_volume
            if not (min_ratio <= ratio <= max_ratio):
                continue
            if len({item["geometry_id"] for item in window}) < 3:
                continue
            if len({item["dimensions"][2] for item in window}) < 3:
                continue
            if split == "test_geometry_ood" and sum(item["geometry_cluster_id"] == "tall" for item in window) < min_ood:
                continue
            if split == "test_semantic_ood" and sum(semantic_combo(item) for item in window) < min_sem:
                continue
            windows.append(window)
    if not windows:
        return None
    chooser = rng_for(seed, "window", split, order_key)
    return copy.deepcopy(windows[chooser.randrange(len(windows))])


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
) -> tuple[dict[str, Any] | None, str | None]:
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
    if record["x0"] < xmin or record["x1"] > xmax or record["y0"] < ymin or record["y1"] > ymax or record["z1"] > c["max_height_mm"]:
        return None, "out_of_bounds"
    if sum(p["item"]["mass_kg"] for p in placed) + item["mass_kg"] > c["max_payload_kg"]:
        return None, "over_payload"
    if any(boxes_overlap_3d(record, p) for p in placed):
        return None, "overlap"

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
            return None, "insufficient_support"
        cx, cy = x0 + box_l / 2, y0 + box_w / 2
        containing = [rect for _, _, rect in support_data if rect[0] <= cx <= rect[1] and rect[2] <= cy <= rect[3]]
        if not containing:
            return None, "com_outside_support"
        com_margin = max(min(cx - r[0], r[1] - cx, cy - r[2], r[3] - cy) for r in containing)
        if any(not p["item"]["stackable"] for p, _, _ in support_data):
            return None, "non_stackable_support"
        total_overlap = sum(area for _, area, _ in support_data)
        support_fractions = [(p["item_id"], area / total_overlap) for p, area, _ in support_data]
        support_ids = [x[0] for x in support_fractions]
        placed_by_id = {p["item_id"]: p for p in placed}
        propagate_load(support_fractions, item["mass_kg"], placed_by_id, increments)
        for support_id, extra in increments.items():
            support = placed_by_id[support_id]
            if support["supported_load_kg"] + extra > support["item"]["top_load_limit_kg_synthetic"] + 1e-9:
                return None, "overload"

    record["supports"] = support_fractions
    after = [copy.deepcopy(p) for p in placed]
    after_by_id = {p["item_id"]: p for p in after}
    for support_id, extra in increments.items():
        after_by_id[support_id]["supported_load_kg"] += extra
    after.append(copy.deepcopy(record))

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


def generate_candidates(
    item: dict[str, Any], placed: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    rejections: Counter[str] = Counter()
    attempted: set[tuple[float, float, float, int]] = set()
    dims = item["dimensions"]
    for yaw in config["candidate_generator"]["yaw_degrees"]:
        box_l, box_w = (dims[0], dims[1]) if yaw == 0 else (dims[1], dims[0])
        for x0, y0, z0 in candidate_points(placed, box_l, box_w, config["container"]):
            key = (x0, y0, z0, yaw)
            if key in attempted:
                continue
            attempted.add(key)
            candidate, reason = evaluate_pose(item, placed, x0, y0, z0, box_l, box_w, yaw, config)
            if candidate is None:
                rejections[reason or "unknown"] += 1
            else:
                candidates.append(candidate)
    if not candidates:
        return [], {"rejection_histogram": dict(rejections)}, {}
    front = pareto_front(candidates)
    top = select_diverse_topk(candidates, config["candidate_generator"]["top_k"])
    best = max(candidates, key=lambda x: (x["geometry_score"], x["visible"]["candidate_id"]))
    top_ids = {x["visible"]["candidate_fingerprint"] for x in top}
    front_ids = {x["visible"]["candidate_fingerprint"] for x in front}
    audit = {
        "rejection_histogram": dict(sorted(rejections.items())),
        "pareto_candidate_fingerprints": sorted(front_ids),
        "pareto_recall_at_k": round(len(top_ids & front_ids) / len(front_ids), 6),
        "geometry_oracle_fingerprint": best["visible"]["candidate_fingerprint"],
        "geometry_oracle_score": best["geometry_score"],
        "epsilon_optimal_recall_at_k": any(
            best["geometry_score"] - x["geometry_score"] <= config["candidate_generator"]["epsilon"] for x in top
        ),
    }
    counts = {
        "raw_candidate_count": len(attempted),
        "physical_valid_count": len(candidates),
    }
    return top, audit, {"best": best, **counts}


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


def rollout(items: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    placed: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    plan: list[dict[str, Any]] = []
    for step_index, item in enumerate(items):
        before = copy.deepcopy(placed)
        top, audit, meta = generate_candidates(item, placed, config)
        if not top:
            return None
        best = meta["best"]
        steps.append(
            {
                "step_index": step_index,
                "placed_before": before,
                "item": item,
                "returned": top,
                "audit": audit,
                "raw_candidate_count": meta["raw_candidate_count"],
                "physical_valid_count": meta["physical_valid_count"],
            }
        )
        plan.append({"step_index": step_index, "item_id": item["item_id"], "candidate": copy.deepcopy(best["visible"])})
        commit_candidate(best, placed)
    if not any(entry["candidate"]["pose"]["z_base_mm"] > 0 for entry in plan):
        return None
    return steps, plan


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


def touching(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ox = overlap_1d(a["x0"], a["x1"], b["x0"], b["x1"])
    oy = overlap_1d(a["y0"], a["y1"], b["y0"], b["y1"])
    oz = overlap_1d(a["z0"], a["z1"], b["z0"], b["z1"])
    face_x = (a["x1"] == b["x0"] or b["x1"] == a["x0"]) and oy > 0 and oz > 0
    face_y = (a["y1"] == b["y0"] or b["y1"] == a["y0"]) and ox > 0 and oz > 0
    face_z = (a["z1"] == b["z0"] or b["z1"] == a["z0"]) and ox > 0 and oy > 0
    return face_x or face_y or face_z


def semantic_evaluation(state: list[dict[str, Any]], rule: dict[str, Any], config: dict[str, Any]) -> tuple[dict[str, float], list[str]]:
    c = config["container"]
    rule_type = rule["rule_type"]
    scores: dict[str, float] = {}
    violations: list[str] = []
    if rule_type == "heavy_low":
        targets = [p for p in state if p["item"]["weight_class"] == "heavy"]
        score = statistics.fmean(max(0.0, 1 - p["z0"] / max(1, c["max_height_mm"] - (p["z1"] - p["z0"]))) for p in targets) if targets else 1.0
        scores[rule_type] = score
    elif rule_type == "heavy_center":
        targets = [p for p in state if p["item"]["weight_class"] == "heavy"]
        max_dist = math.hypot(c["length_mm"] / 2, c["width_mm"] / 2)
        score = statistics.fmean(max(0.0, 1 - math.hypot((p["x0"] + p["x1"]) / 2, (p["y0"] + p["y1"]) / 2) / max_dist) for p in targets) if targets else 1.0
        scores[rule_type] = score
    elif rule_type == "fragile_protect":
        targets = [p for p in state if p["item"]["fragile"]]
        values = []
        for p in targets:
            cap = max(p["item"]["top_load_limit_kg_synthetic"], 1e-6)
            unloaded = max(0.0, 1 - p["supported_load_kg"] / cap)
            high = min(1.0, p["z0"] / c["max_height_mm"])
            values.append(0.6 * unloaded + 0.4 * high)
        scores[rule_type] = statistics.fmean(values) if values else 1.0
    elif rule_type == "category_group":
        targets = [p for p in state if p["item"]["product_category"] == "electronics"]
        if len(targets) < 2:
            scores[rule_type] = 1.0
        else:
            max_dist = math.sqrt(c["length_mm"] ** 2 + c["width_mm"] ** 2 + c["max_height_mm"] ** 2)
            distances = []
            for i, a in enumerate(targets):
                for b in targets[i + 1 :]:
                    ac = ((a["x0"] + a["x1"]) / 2, (a["y0"] + a["y1"]) / 2, (a["z0"] + a["z1"]) / 2)
                    bc = ((b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2, (b["z0"] + b["z1"]) / 2)
                    distances.append(math.dist(ac, bc))
            scores[rule_type] = max(0.0, 1 - statistics.fmean(distances) / max_dist)
    elif rule_type == "category_separate":
        bad_pairs = 0
        checked = 0
        for i, a in enumerate(state):
            for b in state[i + 1 :]:
                a_e = a["item"]["product_category"] == "electronics"
                b_e = b["item"]["product_category"] == "electronics"
                a_h = a["item"]["weight_class"] == "heavy"
                b_h = b["item"]["weight_class"] == "heavy"
                if (a_e and b_h) or (b_e and a_h):
                    checked += 1
                    if touching(a, b):
                        bad_pairs += 1
        scores[rule_type] = 1.0 if checked == 0 else max(0.0, 1 - bad_pairs / checked)
        if bad_pairs:
            violations.append(f"electronics_heavy_contact:{bad_pairs}")
    return {k: round(v, 6) for k, v in scores.items()}, violations


def rule_effect_on_step(step: dict[str, Any], rule: dict[str, Any], config: dict[str, Any]) -> tuple[bool, float]:
    evaluated = []
    for candidate in step["returned"]:
        components, violations = semantic_evaluation(candidate["result_state"], rule, config)
        utility = next(iter(components.values()), 1.0)
        hard = violations if rule["hard_or_soft"] == "hard" else []
        evaluated.append((candidate, utility, hard))
    oracle = max(evaluated, key=lambda x: (-len(x[2]), x[1], x[0]["geometry_score"]))
    geometry_best = max(evaluated, key=lambda x: x[0]["geometry_score"])
    utility_range = max(x[1] for x in evaluated) - min(x[1] for x in evaluated)
    conflict = oracle[0]["visible"]["candidate_id"] != geometry_best[0]["visible"]["candidate_id"]
    return utility_range >= 0.05 and conflict, utility_range


def assign_balanced_rules(scenarios: list[dict[str, Any]], config: dict[str, Any]) -> None:
    """保持规则族数量平衡，同时优先选择确实具有区分度的场景—规则配对。

    候选生成器始终不读取指令；本函数只决定为物理场景附加哪一种语言规则视图。
    """
    by_split: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for scenario in scenarios:
        by_split[scenario["split"]].append(scenario)
    for split, group in by_split.items():
        base_quota, extra = divmod(len(group), len(RULES))
        quota = {r["rule_type"]: base_quota + (i < extra) for i, r in enumerate(RULES)}
        pairs = []
        for scenario in group:
            for rule_index, rule in enumerate(RULES):
                effects = [rule_effect_on_step(step, rule, config) for step in scenario["steps"]]
                count = sum(flag for flag, _ in effects)
                max_range = max((value for _, value in effects), default=0.0)
                pairs.append((count, max_range, -rule_index, scenario["scenario_id"], scenario, rule))
        pairs.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))
        assigned: set[str] = set()
        for _, _, _, sid, scenario, rule in pairs:
            rule_type = rule["rule_type"]
            if sid in assigned or quota[rule_type] <= 0:
                continue
            scenario["rule"] = copy.deepcopy(rule)
            quota[rule_type] -= 1
            assigned.add(sid)
        if len(assigned) != len(group) or any(quota.values()):
            raise RuntimeError(f"无法为划分{split}均衡分配规则：{quota}")


def assign_weight_classes(scenarios: list[dict[str, Any]], q1: float, q2: float) -> None:
    for scenario in scenarios:
        for item in scenario["items"]:
            mass = item["mass_kg"]
            item["weight_class"] = "light" if mass <= q1 else "medium" if mass <= q2 else "heavy"


def synchronize_rollout_weight_classes(scenarios: list[dict[str, Any]]) -> None:
    """将划分后确定的重量等级同步到几何rollout阶段生成的状态快照。"""
    for scenario in scenarios:
        class_by_id = {item["item_id"]: item["weight_class"] for item in scenario["items"]}
        for step in scenario["steps"]:
            step["item"]["weight_class"] = class_by_id[step["item"]["item_id"]]
            for placed in step["placed_before"]:
                placed["item"]["weight_class"] = class_by_id[placed["item_id"]]
            for candidate in step["returned"]:
                for placed in candidate["result_state"]:
                    placed["item"]["weight_class"] = class_by_id[placed["item_id"]]


def scenario_rule(index: int) -> dict[str, Any]:
    return copy.deepcopy(RULES[index % len(RULES)])


def prepare_output(force: bool) -> None:
    marker = ROOT / ".semantic_pallet_dataset"
    if not marker.exists():
        raise RuntimeError(f"缺少安全标记文件：{marker}")
    existing = [ROOT / name for name in GENERATED_DIRS if (ROOT / name).exists()]
    if existing and not force:
        raise RuntimeError("自动生成目录已经存在；如需替换，请使用--force重新运行。")
    if force:
        for path in existing:
            shutil.rmtree(path)
    for name in GENERATED_DIRS:
        (ROOT / name).mkdir(parents=True, exist_ok=True)


def build(args: argparse.Namespace) -> None:
    config = json.loads(args.config.read_text(encoding="utf-8"))
    seed = int(config["dataset_seed"])
    prepare_output(args.force)
    with args.bed.open("r", encoding="utf-8") as handle:
        bed = json.load(handle)

    order_keys = sorted(bed)
    rng_for(seed, "order_shuffle").shuffle(order_keys)
    normalized_orders: dict[str, list[dict[str, Any]]] = {}
    for key in order_keys:
        raw_sequence = sorted(bed[key]["item_sequence"].values(), key=lambda x: int(x["sequence"]))
        normalized_orders[key] = [
            normalize_source_item(x, seed, config["geometry_ood"]["height_threshold_mm"])
            for x in raw_sequence
        ]

    selected: list[dict[str, Any]] = []
    used_orders: set[str] = set()
    rejected = Counter()
    split_order = ["train", "validation", "test_id", "test_geometry_ood", "test_semantic_ood"]
    next_number = 1
    for split in split_order:
        target = config["scenario_counts"][split]
        count = 0
        for order_key in order_keys:
            if count >= target:
                break
            if order_key in used_orders:
                continue
            window = choose_order_window(normalized_orders[order_key], split, config, seed, order_key)
            if window is None:
                rejected[f"{split}:no_window"] += 1
                continue
            scenario_id = f"SCN_{next_number:04d}"
            for item_index, item in enumerate(window):
                item["item_id"] = f"item_{item_index + 1:02d}"
                item["weight_class"] = "unassigned"
            packed = rollout(window, config)
            if packed is None:
                rejected[f"{split}:packing_failed_or_flat"] += 1
                continue
            steps, plan = packed
            rule = scenario_rule(next_number - 1)
            selected.append(
                {
                    "scenario_id": scenario_id,
                    "base_physical_id": f"PHY_{next_number:04d}",
                    "scenario_family_id": f"FAM_{(next_number - 1) // 5 + 1:03d}",
                    "pair_group_id": f"PAIR_{next_number:04d}",
                    "split_group_id": "TEST_ID_LANGUAGE" if split == "test_id" else split.upper(),
                    "split": split,
                    "source_order_key": order_key,
                    "source_order_id": str(bed[order_key]["properties"].get("order_nr", order_key)),
                    "items": window,
                    "rule": rule,
                    "steps": steps,
                    "plan": plan,
                }
            )
            used_orders.add(order_key)
            count += 1
            next_number += 1
        if count != target:
            raise RuntimeError(f"划分{split}只能生成{count}/{target}个场景")

    train_masses = [item["mass_kg"] for s in selected if s["split"] == "train" for item in s["items"]]
    tertiles = statistics.quantiles(train_masses, n=3, method="inclusive")
    q1, q2 = tertiles[0], tertiles[1]
    assign_weight_classes(selected, q1, q2)
    synchronize_rollout_weight_classes(selected)
    assign_balanced_rules(selected, config)

    config_hash = digest(config, 64)
    split_scenarios: defaultdict[str, list[str]] = defaultdict(list)
    split_cases: defaultdict[str, list[str]] = defaultdict(list)
    all_case_count = 0
    semantic_case_count = Counter()
    total_rejections = Counter()
    visible_scenarios: dict[str, dict[str, Any]] = {}

    for scenario in selected:
        sid = scenario["scenario_id"]
        rule = scenario["rule"]
        instruction_id = f"INS_{digest((seed, sid, 'canonical'), 12)}"
        public_scenario = {
            "schema_version": "1.0",
            "scenario_id": sid,
            "container": config["container"],
            "items": [public_item(x) for x in scenario["items"]],
            "arrival_order": [x["item_id"] for x in scenario["items"]],
            "buffer_size": 1,
            "instruction": {"instruction_id": instruction_id, "text": rule["canonical"]},
        }
        visible_scenarios[sid] = public_scenario
        write_json(ROOT / "tasks" / "scenarios" / f"{sid}.json", public_scenario)
        split_scenarios[scenario["split"]].append(sid)
        write_json(
            ROOT / "annotations" / "ground_truth_rules" / f"{sid}.json",
            {
                "schema_version": "1.0",
                "scenario_id": sid,
                "ground_truth_rules": [rule],
                "source_order_id": scenario["source_order_id"],
                "source_order_key": scenario["source_order_key"],
                "source_article_ids": [x["source_article_id"] for x in scenario["items"]],
                "source_sequence_positions": [x["source_sequence"] for x in scenario["items"]],
                "split": scenario["split"],
                "split_group_id": scenario["split_group_id"],
                "reference_feasible_plan_id": f"PLAN_{sid[4:]}",
            },
        )
        write_json(
            ROOT / "annotations" / "reference_feasible_plans" / f"PLAN_{sid[4:]}.json",
            {
                "schema_version": "1.0",
                "plan_id": f"PLAN_{sid[4:]}",
                "scenario_id": sid,
                "planner": "extreme_point_ems_style_geometry_oracle_v0.1",
                "is_globally_optimal": False,
                "placements": [entry["candidate"] for entry in scenario["plan"]],
            },
        )

        ranked_steps = []
        for step in scenario["steps"]:
            evaluated = []
            for candidate in step["returned"]:
                component_scores, violations = semantic_evaluation(candidate["result_state"], rule, config)
                soft_utility = next(iter(component_scores.values()), 1.0)
                evaluated.append(
                    {
                        "candidate": candidate,
                        "semantic_score_components": component_scores,
                        "soft_utility": soft_utility,
                        "hard_violations": violations if rule["hard_or_soft"] == "hard" else [],
                    }
                )
            oracle = max(
                evaluated,
                key=lambda x: (-len(x["hard_violations"]), x["soft_utility"], x["candidate"]["geometry_score"]),
            )
            geometry_best = max(evaluated, key=lambda x: x["candidate"]["geometry_score"])
            semantic_range = max(x["soft_utility"] for x in evaluated) - min(x["soft_utility"] for x in evaluated)
            conflict = oracle["candidate"]["visible"]["candidate_id"] != geometry_best["candidate"]["visible"]["candidate_id"]
            semantic_required = semantic_range >= 0.05 and conflict
            ranked_steps.append((semantic_required, semantic_range, step, evaluated, oracle))
        ranked_steps.sort(key=lambda x: (not x[0], -x[1], x[2]["step_index"]))
        chosen_steps = sorted(ranked_steps[: config["decision_cases_per_scenario"]], key=lambda x: x[2]["step_index"])

        for _, semantic_range, step, evaluated, oracle in chosen_steps:
            dc_number = all_case_count + 1
            decision_id = f"DC_{dc_number:05d}"
            cset_id = f"CSET_{dc_number:05d}"
            order_seed = int(digest((seed, cset_id), 8), 16)
            display_candidates = [copy.deepcopy(x["candidate"]["visible"]) for x in evaluated]
            rng_for(seed, "candidate_order", cset_id).shuffle(display_candidates)
            physical_state = {
                "container": config["container"],
                "placed_items": visible_placed(step["placed_before"]),
                "available_items": [public_item(step["item"])],
                "buffer_size": 1,
            }
            context = {
                "physical_state_hash": digest(physical_state, 64),
                "instruction_text": rule["canonical"],
            }
            candidate_set = {
                "schema_version": "1.0",
                "candidate_set_id": cset_id,
                "scenario_id": sid,
                "step_index": step["step_index"],
                "physical_state_hash": digest(physical_state, 64),
                "decision_context_hash": digest(context, 64),
                "generator": {
                    "name": config["candidate_generator"]["name"],
                    "version": config["candidate_generator"]["version"],
                    "config_hash": config_hash,
                    "top_k": config["candidate_generator"]["top_k"],
                },
                "coordinate_frame": "container_bottom_center",
                "length_unit": "mm",
                "raw_candidate_count": step["raw_candidate_count"],
                "physical_valid_count": step["physical_valid_count"],
                "returned_count": len(display_candidates),
                "candidate_order_seed": order_seed,
                "candidates": display_candidates,
            }
            decision = {
                "schema_version": "1.0",
                "decision_case_id": decision_id,
                "base_scenario_id": sid,
                "step_index": step["step_index"],
                "placed_items": visible_placed(step["placed_before"]),
                "available_items": [public_item(step["item"])],
                "instruction_text": rule["canonical"],
                "candidate_set_id": cset_id,
            }
            annotation = {
                "schema_version": "1.0",
                "decision_case_id": decision_id,
                "candidate_set_id": cset_id,
                "ground_truth_rule": rule,
                "geometry_reference": step["audit"],
                "candidate_evaluations": [
                    {
                        "candidate_id": x["candidate"]["visible"]["candidate_id"],
                        "geometry_score": x["candidate"]["geometry_score"],
                        "semantic_score_components": x["semantic_score_components"],
                        "soft_utility": round(x["soft_utility"], 6),
                        "hard_violations": x["hard_violations"],
                    }
                    for x in evaluated
                ],
                "oracle_candidate_id": oracle["candidate"]["visible"]["candidate_id"],
                "semantic_utility_range": round(semantic_range, 6),
                "semantic_decision_required": bool(
                    semantic_range >= 0.05
                    and oracle["candidate"]["visible"]["candidate_id"]
                    != max(evaluated, key=lambda x: x["candidate"]["geometry_score"])["candidate"]["visible"]["candidate_id"]
                ),
            }
            write_json(ROOT / "candidates" / "candidate_sets" / f"{cset_id}.json", candidate_set)
            write_json(ROOT / "candidates" / "candidate_audits" / f"{cset_id}.json", step["audit"])
            write_json(ROOT / "tasks" / "decision_cases" / f"{decision_id}.json", decision)
            write_json(ROOT / "annotations" / "oracle_candidate_scores" / f"{decision_id}.json", annotation)
            split_cases[scenario["split"]].append(decision_id)
            semantic_case_count[scenario["split"]] += int(annotation["semantic_decision_required"])
            total_rejections.update(step["audit"]["rejection_histogram"])
            all_case_count += 1

    # Language-OOD视图复用完全相同的物理状态和候选坐标，但使用独立的不透明ID
    # 和决策上下文哈希。
    test_id_scenarios = [s for s in selected if s["split"] == "test_id"]
    group_manifest = [
        {
            "scenario_id": scenario["scenario_id"],
            "base_physical_id": scenario["base_physical_id"],
            "scenario_family_id": scenario["scenario_family_id"],
            "pair_group_id": scenario["pair_group_id"],
            "variant_id": "canonical_instruction",
            "split_group_id": scenario["split_group_id"],
        }
        for scenario in selected
    ]
    canonical_case_files = sorted((ROOT / "tasks" / "decision_cases").glob("*.json"))
    cases_by_sid: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in canonical_case_files:
        case = json.loads(path.read_text(encoding="utf-8"))
        cases_by_sid[case["base_scenario_id"]].append(case)
    for language_index, scenario in enumerate(test_id_scenarios, start=101):
        sid = scenario["scenario_id"]
        lang_sid = f"SCN_{language_index:04d}"
        lang_scenario = copy.deepcopy(visible_scenarios[sid])
        lang_scenario["scenario_id"] = lang_sid
        lang_scenario["instruction"] = {
            "instruction_id": f"INS_{digest((seed, sid, 'language_variant'), 12)}",
            "text": scenario["rule"]["paraphrases"][1],
        }
        write_json(ROOT / "tasks" / "scenarios" / f"{lang_sid}.json", lang_scenario)
        split_scenarios["test_language_ood"].append(lang_sid)
        write_json(
            ROOT / "annotations" / "ground_truth_rules" / f"{lang_sid}.json",
            {
                "schema_version": "1.0",
                "scenario_id": lang_sid,
                "ground_truth_rules": [scenario["rule"]],
                "paired_canonical_scenario_id": sid,
                "split": "test_language_ood",
                "split_group_id": "TEST_ID_LANGUAGE",
            },
        )
        group_manifest.append(
            {
                "scenario_id": lang_sid,
                "base_physical_id": scenario["base_physical_id"],
                "scenario_family_id": scenario["scenario_family_id"],
                "pair_group_id": scenario["pair_group_id"],
                "variant_id": "language_ood",
                "split_group_id": "TEST_ID_LANGUAGE",
            }
        )
        for source_case in sorted(cases_by_sid[sid], key=lambda x: x["step_index"]):
            source_cset = json.loads((ROOT / "candidates" / "candidate_sets" / f"{source_case['candidate_set_id']}.json").read_text(encoding="utf-8"))
            source_ann = json.loads((ROOT / "annotations" / "oracle_candidate_scores" / f"{source_case['decision_case_id']}.json").read_text(encoding="utf-8"))
            all_case_count += 1
            decision_id = f"DC_{all_case_count:05d}"
            cset_id = f"CSET_{all_case_count:05d}"
            source_cset["candidate_set_id"] = cset_id
            source_cset["scenario_id"] = lang_sid
            source_cset["decision_context_hash"] = digest(
                {
                    "physical_state_hash": source_cset["physical_state_hash"],
                    "instruction_id": lang_scenario["instruction"]["instruction_id"],
                    "buffer_size": 1,
                },
                64,
            )
            source_case["decision_case_id"] = decision_id
            source_case["base_scenario_id"] = lang_sid
            source_case["instruction_text"] = lang_scenario["instruction"]["text"]
            source_case["candidate_set_id"] = cset_id
            source_ann["decision_case_id"] = decision_id
            source_ann["candidate_set_id"] = cset_id
            source_ann["paired_canonical_scenario_id"] = sid
            write_json(ROOT / "candidates" / "candidate_sets" / f"{cset_id}.json", source_cset)
            write_json(ROOT / "candidates" / "candidate_audits" / f"{cset_id}.json", source_ann["geometry_reference"])
            write_json(ROOT / "tasks" / "decision_cases" / f"{decision_id}.json", source_case)
            write_json(ROOT / "annotations" / "oracle_candidate_scores" / f"{decision_id}.json", source_ann)
            split_cases["test_language_ood"].append(decision_id)
            semantic_case_count["test_language_ood"] += int(source_ann["semantic_decision_required"])

    # 生成20个轻量级buffer_size=3配对场景。由于动作还需要选择箱体，候选集合
    # 由后续规划器在线生成。
    buffer_quota = {
        "train": 10,
        "validation": 2,
        "test_id": 4,
        "test_geometry_ood": 2,
        "test_semantic_ood": 2,
    }
    assert sum(buffer_quota.values()) == config["buffer3_pair_count"]
    buffer_sources = [
        scenario
        for split, quota in buffer_quota.items()
        for scenario in [x for x in selected if x["split"] == split][:quota]
    ]
    for buffer_index, scenario in enumerate(buffer_sources, start=121):
        sid = scenario["scenario_id"]
        buffer_sid = f"SCN_{buffer_index:04d}"
        variant = copy.deepcopy(visible_scenarios[sid])
        variant["scenario_id"] = buffer_sid
        variant["buffer_size"] = 3
        write_json(ROOT / "tasks" / "scenarios" / f"{buffer_sid}.json", variant)
        split_scenarios[f"{scenario['split']}_buffer3"].append(buffer_sid)
        write_json(
            ROOT / "annotations" / "ground_truth_rules" / f"{buffer_sid}.json",
            {
                "schema_version": "1.0",
                "scenario_id": buffer_sid,
                "ground_truth_rules": [scenario["rule"]],
                "source_order_id": scenario["source_order_id"],
                "source_order_key": scenario["source_order_key"],
                "source_article_ids": [x["source_article_id"] for x in scenario["items"]],
                "source_sequence_positions": [x["source_sequence"] for x in scenario["items"]],
                "paired_canonical_scenario_id": sid,
                "split": f"{scenario['split']}_buffer3",
                "split_group_id": scenario["split_group_id"],
                "reference_feasible_plan_id": f"PLAN_{sid[4:]}",
            },
        )
        group_manifest.append(
            {
                "scenario_id": buffer_sid,
                "base_physical_id": scenario["base_physical_id"],
                "scenario_family_id": scenario["scenario_family_id"],
                "pair_group_id": scenario["pair_group_id"],
                "variant_id": "buffer3",
                "split_group_id": scenario["split_group_id"],
            }
        )

    # ReMe任务流使用留出的ID场景。每条流从干净的记忆快照开始；流文件包含
    # 自然语言指令，但不包含Oracle结构化规则。
    stream_pool = [s for s in selected if s["split"] == "test_id"]
    episodes_n = config["streams"]["episodes_per_stream"]
    shift_at = config["streams"]["policy_shift_episode"]
    for stream_index in range(config["streams"]["stationary_count"]):
        rule = RULES[stream_index % len(RULES)]
        episodes = []
        for episode_index in range(episodes_n):
            scenario = stream_pool[(stream_index * 3 + episode_index) % len(stream_pool)]
            episodes.append({"episode_index": episode_index, "scenario_id": scenario["scenario_id"], "policy_version": "P1", "instruction": rule["canonical"]})
        stream = {
            "schema_version": "1.0",
            "stream_id": f"STREAM_STATIONARY_{stream_index + 1:02d}",
            "stream_type": "stationary",
            "memory_reset_group": f"RESET_STATIONARY_{stream_index + 1:02d}",
            "episodes": episodes,
        }
        write_json(ROOT / "streams" / "stationary" / f"{stream['stream_id']}.json", stream)
    shift_pairs = [(0, 1), (1, 2), (2, 3), (3, 4)]
    for stream_index in range(config["streams"]["policy_shift_count"]):
        first, second = (RULES[x] for x in shift_pairs[stream_index % len(shift_pairs)])
        episodes = []
        for episode_index in range(episodes_n):
            scenario = stream_pool[(stream_index * 4 + episode_index) % len(stream_pool)]
            after_shift = episode_index >= shift_at
            entry = {
                "episode_index": episode_index,
                "scenario_id": scenario["scenario_id"],
                "policy_version": "P2" if after_shift else "P1",
                "instruction": second["canonical"] if after_shift else first["canonical"],
            }
            if episode_index == shift_at:
                entry["change_event"] = f"{first['rule_type']}_to_{second['rule_type']}"
            episodes.append(entry)
        stream = {
            "schema_version": "1.0",
            "stream_id": f"STREAM_SHIFT_{stream_index + 1:02d}",
            "stream_type": "policy_shift",
            "memory_reset_group": f"RESET_SHIFT_{stream_index + 1:02d}",
            "episodes": episodes,
        }
        write_json(ROOT / "streams" / "policy_shift" / f"{stream['stream_id']}.json", stream)

    for split, scenario_ids in sorted(split_scenarios.items()):
        write_json(
            ROOT / "splits" / f"{split}.json",
            {"schema_version": "1.0", "split": split, "scenario_ids": scenario_ids, "decision_case_ids": split_cases.get(split, [])},
        )
    write_json(
        ROOT / "splits" / "group_manifest.json",
        {"schema_version": "1.0", "groups": group_manifest},
    )

    article_catalog: dict[str, dict[str, Any]] = {}
    geometry_catalog: defaultdict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "attribute_combinations": set()})
    for scenario in selected:
        for item in scenario["items"]:
            aid = item["source_article_id"]
            article_catalog.setdefault(
                aid,
                {
                    "source_article_id": aid,
                    "geometry_id": item["geometry_id"],
                    "material": item["material"],
                    "fragile": item["fragile"],
                    "stackable": item["stackable"],
                    "top_load_limit_kg_synthetic": item["top_load_limit_kg_synthetic"],
                    "product_category": item["product_category"],
                },
            )
            cat = geometry_catalog[item["geometry_id"]]
            cat["count"] += 1
            cat["attribute_combinations"].add((item["fragile"], item["stackable"], item["product_category"], item["material"]))
    write_json(ROOT / "catalog" / "article_attributes.json", list(article_catalog.values()))
    write_json(
        ROOT / "catalog" / "geometry_catalog.json",
        [
            {"geometry_id": gid, "count": data["count"], "attribute_combination_count": len(data["attribute_combinations"])}
            for gid, data in sorted(geometry_catalog.items())
        ],
    )

    all_items = [item for s in selected for item in s["items"]]
    def phi(a: list[bool], b: list[bool]) -> float:
        n11 = sum(x and y for x, y in zip(a, b)); n10 = sum(x and not y for x, y in zip(a, b))
        n01 = sum(not x and y for x, y in zip(a, b)); n00 = len(a) - n11 - n10 - n01
        denom = math.sqrt((n11+n10)*(n01+n00)*(n11+n01)*(n10+n00))
        return 0.0 if denom == 0 else (n11*n00 - n10*n01) / denom
    median_volume = statistics.median(math.prod(x["dimensions"]) for x in all_items)
    summary = {
        "dataset_version": config["dataset_version"],
        "base_scenario_count": len(selected),
        "visible_scenario_file_count": len(list((ROOT / "tasks" / "scenarios").glob("*.json"))),
        "decision_case_count": all_case_count,
        "split_base_counts": dict(Counter(s["split"] for s in selected)),
        "split_semantic_decision_counts": dict(semantic_case_count),
        "item_count": len(all_items),
        "unique_geometry_count": len({x["geometry_id"] for x in all_items}),
        "unique_article_count": len(article_catalog),
        "weight_class_thresholds_kg": {"light_max": round(q1, 6), "medium_max": round(q2, 6)},
        "attribute_counts": {
            "fragile": sum(x["fragile"] for x in all_items),
            "stackable": sum(x["stackable"] for x in all_items),
            "electronics": sum(x["product_category"] == "electronics" for x in all_items),
            "fragile_and_electronics": sum(semantic_combo(x) for x in all_items),
        },
        "bias_audit": {
            "phi_large_volume_fragile": round(phi([math.prod(x["dimensions"]) >= median_volume for x in all_items], [x["fragile"] for x in all_items]), 6),
            "phi_heavy_electronics": round(phi([x["weight_class"] == "heavy" for x in all_items], [x["product_category"] == "electronics" for x in all_items]), 6),
            "geometries_with_multiple_attribute_combinations": sum(len(x["attribute_combinations"]) > 1 for x in geometry_catalog.values()),
        },
        "candidate_rejection_histogram": dict(sorted(total_rejections.items())),
        "selection_rejections": dict(sorted(rejected.items())),
        "notes": [
            "test_id与test_language_ood是同一TEST_ID_LANGUAGE划分组中的配对评测视图",
            "top_load_limit_kg_synthetic是合成属性，不是真实工业抗压测量值",
            "MVD-v0.1用于接口和功能实验，不承担最终统计结论",
        ],
    }
    write_json(ROOT / "statistics" / "dataset_summary.json", summary)

    mixed_revision = None
    try:
        mixed_revision = subprocess.run(
            ["git", "-C", str(args.mixed), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    provenance = {
        "dataset_release_date": config.get("dataset_release_date", "2026-09-11"),
        "generator": str(Path(__file__).relative_to(WORKSPACE)),
        "config_path": portable_path(args.config),
        "config_sha256": sha256_file(args.config),
        "sources": [
            {"name": "BED-BPP", "path": portable_path(args.bed), "sha256": sha256_file(args.bed)},
            {
                "name": "MixedPalletBoxes",
                "path": portable_path(args.mixed),
                "git_revision": mixed_revision,
                "logic_source_sha256": sha256_file(args.mixed / "box_generator.py"),
            },
        ],
    }
    write_json(ROOT / "provenance" / "manifest.json", provenance)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--bed", type=Path, default=DEFAULT_BED)
    parser.add_argument("--mixed", type=Path, default=DEFAULT_MIXED)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    build(parse_args())

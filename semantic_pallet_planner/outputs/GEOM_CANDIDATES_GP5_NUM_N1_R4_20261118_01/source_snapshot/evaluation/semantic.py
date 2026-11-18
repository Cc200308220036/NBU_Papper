"""冻结的 V0.1 业务规则定义，仅供评价器和特权基线使用。"""
from __future__ import annotations
import copy, math, statistics, hashlib, json
from collections import defaultdict, Counter
from typing import Any, Iterable
def overlap_1d(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


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

#!/usr/bin/env python3
"""不调用候选生成器，独立复核所有公开候选的关键物理约束。"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from pallet_protocol import state_hash


ROOT = Path(__file__).resolve().parents[1]
TOL = 1e-6


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def bounds(record):
    x, y, z = record["pose"]["x_mm"], record["pose"]["y_mm"], record["pose"]["z_base_mm"]
    length, width, height = record["oriented_size_mm"]
    return (x - length / 2, x + length / 2, y - width / 2, y + width / 2, z, z + height)


def overlap_3d(a, b):
    return all((min(a[i + 1], b[i + 1]) - max(a[i], b[i])) > TOL for i in (0, 2, 4))


def union_area(rectangles):
    if not rectangles:
        return 0.0
    xs = sorted({v for r in rectangles for v in r[:2]})
    total = 0.0
    for left, right in zip(xs, xs[1:]):
        if right - left <= TOL:
            continue
        intervals = sorted((r[2], r[3]) for r in rectangles if r[0] < right - TOL and r[1] > left + TOL)
        merged = 0.0
        if intervals:
            start, end = intervals[0]
            for low, high in intervals[1:]:
                if low <= end + TOL:
                    end = max(end, high)
                else:
                    merged += end - start
                    start, end = low, high
            merged += end - start
        total += (right - left) * merged
    return total


def support_rect(candidate_bounds, placed_bounds):
    x0, x1, y0, y1, _, _ = candidate_bounds
    a0, a1, b0, b1, _, _ = placed_bounds
    rect = (max(x0, a0), min(x1, a1), max(y0, b0), min(y1, b1))
    return rect if rect[1] - rect[0] > TOL and rect[3] - rect[2] > TOL else None


def propagate(item_id, load_value, placed_by_id, increments):
    item = placed_by_id[item_id]
    increments[item_id] += load_value
    for edge in item.get("support_fractions", []):
        propagate(edge["item_id"], load_value * edge["fraction"], placed_by_id, increments)


def check_candidate(case, scenario, candidate):
    errors = []
    container = scenario["container"]
    cb = bounds(candidate)
    xmin, xmax = -container["length_mm"] / 2, container["length_mm"] / 2
    ymin, ymax = -container["width_mm"] / 2, container["width_mm"] / 2
    if cb[0] < xmin - TOL or cb[1] > xmax + TOL or cb[2] < ymin - TOL or cb[3] > ymax + TOL or cb[4] < -TOL or cb[5] > container["max_height_mm"] + TOL:
        errors.append("out_of_bounds")
    placed = case["placed_items"]
    placed_by_id = {p["item_id"]: p for p in placed}
    placed_bounds = {p["item_id"]: bounds(p) for p in placed}
    if any(overlap_3d(cb, pb) for pb in placed_bounds.values()):
        errors.append("overlap")
    available = {x["item_id"]: x for x in case["available_items"]}[candidate["pick_item_id"]]
    if sum(x["mass_kg"] for x in placed) + available["mass_kg"] > container["max_payload_kg"] + TOL:
        errors.append("over_payload")
    z_base = cb[4]
    expected_ids = []
    fractions = []
    if z_base > TOL:
        rects = []
        for item_id, pb in placed_bounds.items():
            if abs(pb[5] - z_base) > TOL:
                continue
            rect = support_rect(cb, pb)
            if rect:
                area = (rect[1] - rect[0]) * (rect[3] - rect[2])
                rects.append(rect)
                expected_ids.append(item_id)
                fractions.append((item_id, area))
        ratio = union_area(rects) / ((cb[1] - cb[0]) * (cb[3] - cb[2]))
        if ratio + TOL < 0.70:
            errors.append("insufficient_support")
        cx, cy = candidate["pose"]["x_mm"], candidate["pose"]["y_mm"]
        if not any(r[0] - TOL <= cx <= r[1] + TOL and r[2] - TOL <= cy <= r[3] + TOL for r in rects):
            errors.append("com_outside_support")
        if any(not placed_by_id[x]["stackable"] for x in expected_ids):
            errors.append("non_stackable_support")
        total = sum(area for _, area in fractions)
        increments = defaultdict(float)
        for item_id, area in fractions:
            propagate(item_id, available["mass_kg"] * area / total, placed_by_id, increments)
        for item_id, extra in increments.items():
            item = placed_by_id[item_id]
            if item["supported_load_kg"] + extra > item["top_load_limit_kg_synthetic"] + TOL:
                errors.append("overload")
                break
        reported = candidate["support"]
        if set(reported["support_item_ids"]) != set(expected_ids):
            errors.append("support_ids_mismatch")
        if abs(reported["support_ratio"] - ratio) > 2e-6:
            errors.append("support_ratio_mismatch")
    elif candidate["support"]["support_item_ids"] or abs(candidate["support"]["support_ratio"] - 1.0) > TOL:
        errors.append("floor_support_mismatch")
    expected_height = max([cb[5], *(bounds(p)[5] for p in placed)])
    if abs(candidate["resulting_geometry"]["max_height_mm"] - expected_height) > TOL:
        errors.append("max_height_mismatch")
    volume = sum(math.prod(p["oriented_size_mm"]) for p in placed) + math.prod(candidate["oriented_size_mm"])
    expected_ratio = volume / (container["length_mm"] * container["width_mm"] * container["max_height_mm"])
    if abs(candidate["resulting_geometry"]["volume_utilization"] - expected_ratio) > 2e-6:
        errors.append("volume_utilization_mismatch")
    return errors


def main():
    scenarios = {p.stem: load(p) for p in (ROOT / "tasks" / "scenarios").glob("*.json")}
    failures = []
    checked = 0
    multilayer = 0
    for case_path in sorted((ROOT / "tasks" / "decision_cases").glob("*.json")):
        case = load(case_path)
        scenario = scenarios[case["base_scenario_id"]]
        cset = load(ROOT / "candidates" / "candidate_sets" / f"{case['candidate_set_id']}.json")
        if state_hash(scenario["container"], case) != cset["physical_state_hash"]:
            failures.append({"case": case["decision_case_id"], "candidate": None, "errors": ["state_hash_mismatch"]})
        for candidate in cset["candidates"]:
            checked += 1
            multilayer += int(candidate["pose"]["z_base_mm"] > 0)
            errors = check_candidate(case, scenario, candidate)
            if errors:
                failures.append({"case": case["decision_case_id"], "candidate": candidate["candidate_id"], "errors": errors})
    histogram = Counter(error for entry in failures for error in entry["errors"])
    report = {
        "status": "PASS" if not failures else "FAIL",
        "checked_candidate_count": checked,
        "multilayer_candidate_count": multilayer,
        "failure_count": len(failures),
        "failure_histogram": dict(sorted(histogram.items())),
        "failure_examples": failures[:20],
        "scope": ["边界", "不重叠", "总载荷", "支撑率", "重心投影", "不可堆叠", "传播承重", "支撑ID", "最大高度", "体积率"],
    }
    (ROOT / "statistics" / "independent_geometry_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

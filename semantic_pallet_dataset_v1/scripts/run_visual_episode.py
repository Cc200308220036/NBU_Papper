#!/usr/bin/env python3
"""使用在线候选生成器运行整场真值码垛并逐步渲染；默认采用几何最佳候选。"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from build_dataset import commit_candidate, generate_candidates, public_item, visible_placed
from pallet_protocol import build_request
from render_decision_cases import render_final_layout, render_montage, render_selected_result, render_workspace


ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def internal_item(item):
    result = copy.deepcopy(item)
    dims = item["dimensions_mm"]
    result["dimensions"] = [dims["length"], dims["width"], dims["height"]]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="SCN_0001")
    parser.add_argument("--max-steps", type=int)
    args = parser.parse_args()
    config = load(ROOT / "configs/mvd_v0.1.json")
    scenario = load(ROOT / "tasks/scenarios" / f"{args.scenario}.json")
    placed = []
    trajectory = []
    output = ROOT / "runs" / f"DEMO_{args.scenario}"
    output.mkdir(parents=True, exist_ok=True)
    items = [internal_item(x) for x in scenario["items"]]
    if args.max_steps:
        items = items[:args.max_steps]
    for step_index, item in enumerate(items):
        top, audit, counts = generate_candidates(item, placed, config)
        if not top:
            trajectory.append({"step_index": step_index, "status": "NO_CANDIDATE"})
            break
        ranked = sorted(top, key=lambda x: (-x["geometry_score"], x["visible"]["candidate_id"]))
        visible_candidates = [copy.deepcopy(x["visible"]) for x in ranked]
        case = {
            "decision_case_id": f"{args.scenario}_STEP_{step_index:03d}",
            "step_index": step_index,
            "placed_items": visible_placed(placed),
            "available_items": [public_item(item)],
            "instruction_text": scenario["instruction"]["text"],
        }
        from pallet_protocol import state_hash
        cset = {"physical_state_hash": state_hash(scenario["container"], case), "candidates": visible_candidates}
        step_dir = output / f"step_{step_index:03d}"
        step_dir.mkdir(parents=True, exist_ok=True)
        render_workspace(case, scenario, step_dir / "workspace.png")
        render_montage(case, scenario, cset, step_dir / "candidates_montage.png")
        request = build_request(scenario["container"], case, cset, "workspace.png", "candidates_montage.png")
        selected = ranked[0]
        render_selected_result(case, scenario, selected["visible"], step_dir / "selected_result.png")
        response = {"schema_version": "pallet_vlm_response_v1", "request_id": case["decision_case_id"], "state_hash": cset["physical_state_hash"], "candidate_id": selected["visible"]["candidate_id"], "selector": "geometry_best_demo"}
        (step_dir / "vlm_request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (step_dir / "selection.json").write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        trajectory.append({"step_index": step_index, "item_id": item["item_id"], "selected_candidate": selected["visible"], "candidate_counts": counts, "candidate_audit": audit})
        commit_candidate(selected, placed)
    result = {"schema_version": "visual_episode_v1", "scenario_id": args.scenario, "selector": "geometry_best_demo", "completed_steps": len(placed), "requested_steps": len(items), "final_placed_items": visible_placed(placed), "trajectory": trajectory}
    render_final_layout(scenario["container"], result["final_placed_items"], f"FINAL LAYOUT | {args.scenario} | {len(placed)} boxes", output / "final_layout.png")
    (output / "episode.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS" if len(placed) == len(items) else "INCOMPLETE", "output": str(output), "completed_steps": len(placed)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

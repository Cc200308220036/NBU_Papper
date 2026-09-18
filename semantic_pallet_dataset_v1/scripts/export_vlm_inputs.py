#!/usr/bin/env python3
"""从内部记录导出不含Oracle和划分标签的VLM白名单输入。"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from pallet_protocol import build_request


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    output = ROOT / "views" / "vlm_inputs"
    output.mkdir(parents=True, exist_ok=True)
    validator = Draft202012Validator(load(ROOT / "schemas" / "vlm_request.schema.json"))
    scenarios = {p.stem: load(p) for p in (ROOT / "tasks" / "scenarios").glob("*.json")}
    count = 0
    for case_path in sorted((ROOT / "tasks" / "decision_cases").glob("*.json")):
        case = load(case_path)
        cset = load(ROOT / "candidates" / "candidate_sets" / f"{case['candidate_set_id']}.json")
        scenario = scenarios[case["base_scenario_id"]]
        stem = case["decision_case_id"]
        request = build_request(
            scenario["container"], case, cset,
            f"../rendered/{stem}/workspace.png",
            f"../rendered/{stem}/candidates_montage.png",
        )
        validator.validate(request)
        (output / f"{stem}.json").write_text(
            json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        count += 1
    print(json.dumps({"status": "PASS", "vlm_request_count": count}, ensure_ascii=False))


if __name__ == "__main__":
    main()

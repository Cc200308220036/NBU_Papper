"""汇总阶段1C的协议、位置、成本及配对语义指标。"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import json
import statistics

from ..logging.artifacts import dump

VLM_METHODS = ("vlm_text", "vlm_visual")
REQUIRED_METHODS = ("random_valid", "geometry_greedy", "handcrafted_rule",
                    "vlm_text", "vlm_visual", "candidate_oracle")


def _mean(values):
    return statistics.mean(values) if values else None


def write_stage1c_summaries(experiment):
    root = Path(experiment.root)
    rows = experiment.decisions
    protocol = {}; cost = {}; positions = {}
    for method in VLM_METHODS:
        group = [r for r in rows if r["method"] == method]
        valid = [bool(r.get("vlm_response_valid")) for r in group]
        protocol[method] = {
            "n": len(group), "valid_count": sum(valid), "vlm_valid_rate": _mean(valid),
            "fallback_count": sum(bool(r.get("fallback")) for r in group),
            "repair_count": sum(int(r.get("repair_count", 0) or 0) for r in group),
            "error_categories": dict(Counter(r.get("error_category") for r in group if r.get("error_category"))),
        }
        cost[method] = {
            "input_tokens_total": sum(int(r.get("input_tokens", 0) or 0) for r in group),
            "output_tokens_total": sum(int(r.get("output_tokens", 0) or 0) for r in group),
            # 供应商错误不会产生ModelResult，时延字段会记为零；统计成功推理时延时排除这些零值，
            # 避免平均时延被错误地拉低。
            "api_latency_mean_s": _mean([float(r["api_latency_s"]) for r in group
                                           if r.get("api_latency_s") not in (None, "") and float(r["api_latency_s"]) > 0]),
            "estimated_cost_total": sum(float(r.get("estimated_cost", 0) or 0) for r in group),
            "cache_hit_count": sum(bool(r.get("cache_hit")) for r in group),
        }
        positions[method] = dict(sorted(Counter(r.get("selected_display_position") for r in group
                                                         if r.get("selected_display_position")).items()))
    by_case = defaultdict(dict)
    for row in rows:
        by_case[row.get("decision_case_id")][row["method"]] = row
    comparisons = {}
    for left, right in (("vlm_text", "geometry_greedy"), ("vlm_visual", "geometry_greedy"),
                        ("vlm_visual", "vlm_text")):
        diffs = [float(methods[left]["soft_utility"]) - float(methods[right]["soft_utility"])
                 for methods in by_case.values() if left in methods and right in methods]
        comparisons[f"{left}_minus_{right}"] = {
            "n": len(diffs), "mean_soft_utility_delta": _mean(diffs),
            "wins": sum(x > 1e-12 for x in diffs), "ties": sum(abs(x) <= 1e-12 for x in diffs),
            "losses": sum(x < -1e-12 for x in diffs),
        }
    reports = [json.loads(path.read_text()) for path in root.glob("selector_inputs/vlm_*/*/leakage_report.json")]
    leakage = {"reports": len(reports), "passed": bool(reports) and all(r.get("passed") for r in reports),
               "hit_count": sum(len(r.get("forbidden_key_hits", [])) + len(r.get("forbidden_value_hits", [])) +
                                len(r.get("real_candidate_id_hits", [])) for r in reports)}
    dump(root / "metrics/protocol_summary.json", protocol)
    dump(root / "metrics/cost_summary.json", cost)
    dump(root / "metrics/position_bias.json", positions)
    dump(root / "metrics/paired_comparisons.json", comparisons)
    dump(root / "leakage_report.json", leakage)
    return {"protocol": protocol, "cost": cost, "positions": positions,
            "comparisons": comparisons, "leakage": leakage}


def write_stage1c_acceptance(experiment, replay_status: str, test_status: bool):
    root = Path(experiment.root); rows = experiment.decisions
    protocol = json.loads((root / "metrics/protocol_summary.json").read_text())
    leakage = json.loads((root / "leakage_report.json").read_text())
    methods = {r["method"] for r in rows}; cases = defaultdict(set)
    for row in rows: cases[row["decision_case_id"]].add(row["candidate_set_id"])
    checks = []
    def add(name, passed, evidence): checks.append({"check": name, "passed": bool(passed), "evidence": evidence})
    add("all_tests_pass", test_status, "tests/status.json")
    full_matrix = (len(cases) == 360 and len(rows) == 2160 and set(REQUIRED_METHODS) == methods and
                   all(sum(r["method"] == method for r in rows) == 360 for method in REQUIRED_METHODS))
    add("360_cases_six_methods_2160_rows", full_matrix, "metrics/per_decision.csv")
    add("same_frozen_candidate_set", all(len(x) == 1 for x in cases.values()), "metrics/per_decision.csv")
    add("zero_model_input_leakage", leakage["passed"] and leakage["hit_count"] == 0, "leakage_report.json")
    add("zero_physical_hard_violations", all(int(r.get("hard_violations", 0)) == 0 for r in rows), "metrics/per_decision.csv")
    for method in VLM_METHODS:
        rate = protocol.get(method, {}).get("vlm_valid_rate")
        add(f"{method}_valid_rate_at_least_98_percent", rate is not None and rate >= .98,
            "metrics/protocol_summary.json")
    add("replay_pass", replay_status == "PASS", "replay_report.json")
    add("api_metrics_recorded", all("api_latency_s" in r and "prompt_sha256" in r and "mapping_sha256" in r
                                    for r in rows if r["method"] in VLM_METHODS), "metrics/per_decision.csv")
    status = "PASS" if checks and all(x["passed"] for x in checks) else "FAIL"
    report = {"stage": "1c", "status": status, "checks": checks, "fixed_rows": len(rows),
              "decision_cases": len(cases), "methods": sorted(methods),
              "research_outcomes_are_not_acceptance_gates": True}
    dump(root / "acceptance_report.json", report)
    lines = ["# 阶段1C开发与验收报告", "", f"结论：**{status}**", "",
             f"固定决策{len(rows)}条，Decision Case {len(cases)}个。", "",
             "| 检查 | 结果 | 证据 |", "|---|---|---|"]
    lines.extend(f"| {x['check']} | {'PASS' if x['passed'] else 'FAIL'} | {x['evidence']} |" for x in checks)
    lines += ["", "语义提升、视觉增益和成本属于研究结果，均完整报告，但不预设为工程PASS门槛。", ""]
    (root / "acceptance_report.md").write_text("\n".join(lines))
    return report

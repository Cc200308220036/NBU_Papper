#!/usr/bin/env python3
"""验证Schema、数据泄漏隔离、划分一致性以及MVD验收条件。"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def digest(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_files(pattern: str, schema_name: str) -> int:
    schema = load(ROOT / "schemas" / schema_name)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    paths = sorted(ROOT.glob(pattern))
    for path in paths:
        errors = sorted(validator.iter_errors(load(path)), key=lambda x: list(x.path))
        if errors:
            first = errors[0]
            where = "/".join(str(x) for x in first.path)
            raise AssertionError(f"Schema验证失败 {path}:{where}：{first.message}")
    return len(paths)


def strip_language_view(scenario: dict[str, Any]) -> dict[str, Any]:
    value = dict(scenario)
    value.pop("scenario_id")
    value.pop("instruction")
    return value


def main() -> None:
    config = load(ROOT / "configs" / "mvd_v0.1.json")
    counts = {
        "scenarios": validate_files("tasks/scenarios/*.json", "scenario.schema.json"),
        "decision_cases": validate_files("tasks/decision_cases/*.json", "decision_case.schema.json"),
        "candidate_sets": validate_files("candidates/candidate_sets/*.json", "candidate_set.schema.json"),
        "candidate_audits": validate_files("candidates/candidate_audits/*.json", "candidate_audit.schema.json"),
        "ground_truth_rules": validate_files("annotations/ground_truth_rules/*.json", "ground_truth_rule.schema.json"),
        "reference_plans": validate_files("annotations/reference_feasible_plans/*.json", "reference_plan.schema.json"),
        "oracle_annotations": validate_files("annotations/oracle_candidate_scores/*.json", "oracle_annotation.schema.json"),
        "streams": validate_files("streams/*/*.json", "stream.schema.json"),
    }
    split_paths = sorted(path for path in (ROOT / "splits").glob("*.json") if path.name != "group_manifest.json")
    split_validator = Draft202012Validator(load(ROOT / "schemas" / "split.schema.json"))
    for path in split_paths:
        split_validator.validate(load(path))
    Draft202012Validator(load(ROOT / "schemas" / "group_manifest.schema.json")).validate(load(ROOT / "splits" / "group_manifest.json"))

    expected_base = sum(config["scenario_counts"].values())
    assert counts["scenarios"] == expected_base + 20 + config["buffer3_pair_count"], counts
    assert counts["decision_cases"] == counts["candidate_sets"] == counts["candidate_audits"] == counts["oracle_annotations"]
    assert 300 <= counts["decision_cases"] <= 500
    assert counts["reference_plans"] == expected_base
    assert counts["streams"] == config["streams"]["stationary_count"] + config["streams"]["policy_shift_count"]

    scenarios = {p.stem: load(p) for p in sorted((ROOT / "tasks" / "scenarios").glob("*.json"))}
    cases = {p.stem: load(p) for p in sorted((ROOT / "tasks" / "decision_cases").glob("*.json"))}
    csets = {p.stem: load(p) for p in sorted((ROOT / "candidates" / "candidate_sets").glob("*.json"))}
    annotations = {p.stem: load(p) for p in sorted((ROOT / "annotations" / "oracle_candidate_scores").glob("*.json"))}
    split_data = {p.stem: load(p) for p in split_paths}

    # 检查可见记录是否泄漏信息：ID必须不透明，规划器可见任务中不能出现评测、
    # 分组或原始来源元数据。
    forbidden_keys = {
        "source_order_id", "source_order_key", "source_article_id", "source_article_ids",
        "ground_truth_rule", "ground_truth_rules", "oracle_candidate_id", "split",
        "split_group_id", "variant_id", "pair_group_id", "scenario_family_id", "base_physical_id",
    }
    rule_tokens = {"HEAVY_LOW", "HEAVY_CENTER", "FRAGILE_PROTECT", "CATEGORY_GROUP", "CATEGORY_SEPARATE", "LANGUAGE_OOD"}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            leaked = forbidden_keys & value.keys()
            assert not leaked, f"可见字段发生泄漏：{leaked}"
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for record in list(scenarios.values()) + list(cases.values()) + list(csets.values()):
        walk(record)
        text = json.dumps(record, ensure_ascii=False)
        assert not any(token in text for token in rule_tokens), "可见记录中存在非透明元数据"

    # 检查引用完整性，以及候选集合与隐藏标注是否一致。
    for case_id, case in cases.items():
        assert case["base_scenario_id"] in scenarios
        cset = csets[case["candidate_set_id"]]
        ann = annotations[case_id]
        assert cset["candidate_set_id"] == case["candidate_set_id"] == ann["candidate_set_id"]
        assert cset["scenario_id"] == case["base_scenario_id"]
        assert cset["step_index"] == case["step_index"]
        physical_state = {
            "container": scenarios[case["base_scenario_id"]]["container"],
            "placed_items": case["placed_items"],
            "available_items": case["available_items"],
            "buffer_size": len(case["available_items"]),
        }
        assert cset["physical_state_hash"] == digest(physical_state), f"状态哈希错误：{case_id}"
        candidate_ids = [x["candidate_id"] for x in cset["candidates"]]
        assert len(candidate_ids) == len(set(candidate_ids)) == cset["returned_count"]
        assert cset["returned_count"] <= cset["physical_valid_count"] <= cset["raw_candidate_count"]
        assert all(x["physical_valid"] and not x["physical_rejection_reasons"] for x in cset["candidates"])
        assert ann["oracle_candidate_id"] in candidate_ids
        assert {x["candidate_id"] for x in ann["candidate_evaluations"]} == set(candidate_ids)

    # 检查基础场景的数量、装载密度、SKU多样性和多层条件。
    base_ids = [sid for name in ("train", "validation", "test_id", "test_geometry_ood", "test_semantic_ood") for sid in split_data[name]["scenario_ids"]]
    assert len(base_ids) == len(set(base_ids)) == expected_base
    c = config["container"]
    container_volume = c["length_mm"] * c["width_mm"] * c["max_height_mm"]
    for sid in base_ids:
        scenario = scenarios[sid]
        assert config["items_per_scenario"]["min"] <= len(scenario["items"]) <= config["items_per_scenario"]["max"]
        assert scenario["arrival_order"] == [x["item_id"] for x in scenario["items"]]
        assert len(set(scenario["arrival_order"])) == len(scenario["items"])
        ratio = sum(x["dimensions_mm"]["length"] * x["dimensions_mm"]["width"] * x["dimensions_mm"]["height"] for x in scenario["items"]) / container_volume
        assert config["target_volume_ratio"]["min"] <= ratio <= config["target_volume_ratio"]["max"]
        assert len({x["geometry_id"] for x in scenario["items"]}) >= 3
        assert len({x["dimensions_mm"]["height"] for x in scenario["items"]}) >= 3
        plan = load(ROOT / "annotations" / "reference_feasible_plans" / f"PLAN_{sid[4:]}.json")
        assert len(plan["placements"]) == len(scenario["items"])
        assert any(x["pose"]["z_base_mm"] > 0 for x in plan["placements"])

    # 检查来源订单隔离、几何留出和语义组合留出。
    source_by_split: defaultdict[str, set[str]] = defaultdict(set)
    gt_by_sid = {p.stem: load(p) for p in (ROOT / "annotations" / "ground_truth_rules").glob("*.json")}
    for split in ("train", "validation", "test_id", "test_geometry_ood", "test_semantic_ood"):
        for sid in split_data[split]["scenario_ids"]:
            source_by_split[split].add(gt_by_sid[sid]["source_order_key"])
    split_names = list(source_by_split)
    for index, left in enumerate(split_names):
        for right in split_names[index + 1:]:
            assert source_by_split[left].isdisjoint(source_by_split[right]), f"来源订单泄漏：{left}/{right}"

    tall_threshold = config["geometry_ood"]["height_threshold_mm"]
    regular_splits = ("train", "validation", "test_id", "test_semantic_ood")
    assert all(item["dimensions_mm"]["height"] < tall_threshold for split in regular_splits for sid in split_data[split]["scenario_ids"] for item in scenarios[sid]["items"])
    assert all(sum(item["dimensions_mm"]["height"] >= tall_threshold for item in scenarios[sid]["items"]) >= config["geometry_ood"]["minimum_ood_items"] for sid in split_data["test_geometry_ood"]["scenario_ids"])

    def is_semantic_combo(item: dict[str, Any]) -> bool:
        return item["fragile"] and item["product_category"] == "electronics"
    assert not any(is_semantic_combo(item) for split in ("train", "validation", "test_id", "test_geometry_ood") for sid in split_data[split]["scenario_ids"] for item in scenarios[sid]["items"])
    assert all(sum(is_semantic_combo(item) for item in scenarios[sid]["items"]) >= config["semantic_ood"]["minimum_ood_items"] for sid in split_data["test_semantic_ood"]["scenario_ids"])

    # 检查语言配对：物理内容完全相同，只允许指令和不透明ID不同。
    group_manifest = load(ROOT / "splits" / "group_manifest.json")["groups"]
    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in group_manifest:
        groups[entry["pair_group_id"]].append(entry)
    language_pairs = 0
    for entries in groups.values():
        canonical = next((x for x in entries if x["variant_id"] == "canonical_instruction"), None)
        language = next((x for x in entries if x["variant_id"] == "language_ood"), None)
        if language:
            language_pairs += 1
            assert canonical is not None
            assert canonical["split_group_id"] == language["split_group_id"] == "TEST_ID_LANGUAGE"
            assert strip_language_view(scenarios[canonical["scenario_id"]]) == strip_language_view(scenarios[language["scenario_id"]])
    assert language_pairs == 20
    buffer_split_names = [name for name in split_data if name.endswith("_buffer3")]
    buffer_ids = [sid for name in buffer_split_names for sid in split_data[name]["scenario_ids"]]
    assert len(buffer_ids) == config["buffer3_pair_count"]
    assert all(scenarios[sid]["buffer_size"] == 3 for sid in buffer_ids)

    # 每个核心测试集至少一半决策点必须属于非平凡语义选择。
    semantic_rates = {}
    for split in ("test_id", "test_geometry_ood", "test_semantic_ood", "test_language_ood"):
        case_ids = split_data[split]["decision_case_ids"]
        rate = sum(annotations[x]["semantic_decision_required"] for x in case_ids) / len(case_ids)
        semantic_rates[split] = rate
        assert rate >= 0.5, f"划分{split}中的非平凡语义决策不足：{rate:.3f}"

    # 检查任务流时序和策略切换语义。
    streams = [load(p) for p in sorted((ROOT / "streams").glob("*/*.json"))]
    assert sum(x["stream_type"] == "stationary" for x in streams) == config["streams"]["stationary_count"]
    assert sum(x["stream_type"] == "policy_shift" for x in streams) == config["streams"]["policy_shift_count"]
    for stream in streams:
        assert [x["episode_index"] for x in stream["episodes"]] == list(range(config["streams"]["episodes_per_stream"]))
        assert all(x["scenario_id"] in split_data["test_id"]["scenario_ids"] for x in stream["episodes"])
        changes = [x for x in stream["episodes"] if "change_event" in x]
        if stream["stream_type"] == "stationary":
            assert not changes and len({x["policy_version"] for x in stream["episodes"]}) == 1
        else:
            assert len(changes) == 1 and changes[0]["episode_index"] == config["streams"]["policy_shift_episode"]

    # 其余JSON至少通过元数据Schema；同时检查所有Schema文档自身是否合法。
    # 核心基准记录使用上面定义的严格Schema。
    metadata_validator = Draft202012Validator({"type": ["object", "array"]})
    for path in sorted(ROOT.rglob("*.json")):
        metadata_validator.validate(load(path))
    for path in sorted((ROOT / "schemas").glob("*.json")):
        Draft202012Validator.check_schema(load(path))

    # 派生报告不参与内容哈希，避免首次验证和再次验证的文件集合不同。
    checksum_excluded = {
        ROOT / "statistics" / "generated_checksums.json",
        ROOT / "statistics" / "validation_report.json",
        ROOT / "statistics" / "independent_geometry_report.json",
        ROOT / "statistics" / "stage0_acceptance_report.json",
        ROOT / "statistics" / "visual_audit_manifest.json",
        ROOT / "statistics" / "reproducibility_report.json",
    }
    checksum_paths = [
        p for p in sorted(ROOT.rglob("*.json"))
        if p not in checksum_excluded and p.relative_to(ROOT).parts[0] not in {"views", "runs"}
    ]
    checksum_record = {
        "schema_version": "1.0",
        "file_count": len(checksum_paths),
        "files": {str(p.relative_to(ROOT)): sha256(p) for p in checksum_paths},
    }
    (ROOT / "statistics" / "generated_checksums.json").write_text(
        json.dumps(checksum_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report = {
        "status": "PASS",
        "validated_counts": counts,
        "split_manifest_count": len(split_paths),
        "semantic_decision_rates": {k: round(v, 6) for k, v in semantic_rates.items()},
        "checks": [
            "核心JSON记录严格Schema验证",
            "可见元数据不透明性检查",
            "文件引用完整性检查",
            "体积率、SKU多样性和多层条件验收",
            "来源订单跨划分隔离检查",
            "几何与语义留出检查",
            "语言配对物理等价性检查",
            "非平凡语义决策激活率检查",
            "记忆任务流时序检查",
        ],
    }
    (ROOT / "statistics" / "validation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

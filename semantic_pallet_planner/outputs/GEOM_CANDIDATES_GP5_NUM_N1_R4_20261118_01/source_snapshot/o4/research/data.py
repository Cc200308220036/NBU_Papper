"""Source audit and deterministic study derivation outside the V1 dataset.

Selection uses only recorded provenance and raw mechanical eligibility, never
model scores, parser success, policy feasibility or complete-order outcomes.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from ...config import WORKSPACE, generator_config, load_config
from ...domain import PalletState
from ...evaluation.geometry_oracle import check_candidate
from ...evaluation.state import apply_candidate
from ...planner.generator import ExtremePointGenerator
from ...planner.scoring import geometry_score
from ..common import CATEGORIES, O4Error, digest, read, write
from ..observation import build_observation
from ..online.planner_adapter import labeled_candidates
from ..remote_v2.experiment import file_hash, file_manifest, new_directory, source_hashes, verify_sources
from . import VERSION
from .specifications import CORE, instruction, specification, split_records
from .validation import reference_gold

DEFAULT_CONFIG = WORKSPACE / "semantic_pallet_planner/configs/o4_d_research_v1.json"
DEFAULT_BED = WORKSPACE / "raw/bed_bpp/bed-bpp_v1.json"


def validate_design(config):
    expected = read(DEFAULT_CONFIG)
    if set(config) != set(expected) or config["version"] != VERSION:
        raise ValueError("unknown study design fields/version")
    if set(config["sources"]) != {"development", "calibration", "test"}:
        raise ValueError("all three source partitions required")
    if any(type(n) is not int or n < 2 for n in config["sources"].values()):
        raise ValueError("at least two independent source groups per partition")
    if type(config["seed"]) is not int or type(config["items_per_order"]) is not int or not 3 <= config["items_per_order"] <= 24:
        raise ValueError("invalid seed/item limit")
    for key in ("fixed_repeats", "online_repeats"):
        if set(config[key]) != set(config["sources"]) or any(type(n) is not int or not 1 <= n <= 10 for n in config[key].values()):
            raise ValueError("invalid repeat design")
    for key in ("practical_gain", "progress_noninferiority_margin"):
        if type(config[key]) not in (int, float) or not 0 <= config[key] <= 1:
            raise ValueError("invalid effect criterion")
    if type(config["bootstrap_samples"]) is not int or config["bootstrap_samples"] < 100:
        raise ValueError("bootstrap_samples must be >=100")
    # Varying size/repetition is allowed only before sealing the new corpus.
    for key in ("primary_fixed_metric", "primary_online_metric", "inference", "online_families", "online_planner"):
        if config[key] != expected[key]:
            raise ValueError(f"unsupported design change: {key}")
    return config


def provenance_values(value):
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ("source_order_key", "source_order_id", "source_order_keys"):
                if isinstance(child, (str, int)):
                    found.add(str(child))
                elif isinstance(child, list):
                    found.update(str(x) for x in child if isinstance(x, (str, int)))
            found.update(provenance_values(child))
    elif isinstance(value, list):
        for child in value:
            found.update(provenance_values(child))
    return found


def source_audit(workspace=WORKSPACE):
    workspace = Path(workspace)
    paths = set((workspace / "semantic_pallet_dataset_v1/annotations/ground_truth_rules").glob("*.json"))
    outputs = workspace / "semantic_pallet_planner/outputs"
    for root in outputs.iterdir():
        if not root.is_dir():
            continue
        for name in ("manifest.json", "split_manifest.json", "plan.json"):
            if (root / name).is_file():
                paths.add(root / name)
        paths.update((root / "private").glob("*.json"))
    excluded, records = set(), []
    for path in sorted(paths):
        values = provenance_values(read(path))
        excluded.update(values)
        records.append({"path": str(path.relative_to(workspace)), "sha256": file_hash(path),
                        "source_values": sorted(values)})
    return {"excluded_source_values": sorted(excluded), "files": records,
            "claim": "absent from recorded repository source provenance; not a claim about external exposure",
            "raw_data_preexisted": True, "independently_collected_real_data": False}


def raw_profile(sequence):
    return [[x["length/mm"], x["width/mm"], x["height/mm"], x["weight/kg"]] for x in sequence]


def select_sources(raw, audit, design):
    excluded = set(audit["excluded_source_values"])
    count = design["items_per_order"]
    # Exclude geometry/mass clones of all known source orders as well as IDs.
    fingerprints = {digest(raw_profile(sorted(order["item_sequence"].values(), key=lambda x: int(x["sequence"]))[:count]))
                    for key, order in raw.items()
                    if key in excluded or str(order["properties"].get("order_nr")) in excluded}
    selected, rejected = [], {"recorded_source": 0, "mechanical_eligibility": 0, "duplicate_window": 0}
    total = sum(design["sources"].values())
    for key in sorted(raw, key=lambda key: digest([design["seed"], "source_selection", key])):
        order = raw[key]
        if key in excluded or str(order["properties"].get("order_nr")) in excluded:
            rejected["recorded_source"] += 1
            continue
        sequence = sorted(order["item_sequence"].values(), key=lambda x: int(x["sequence"]))[:count]
        if len(sequence) != count or any(
            not (0 < x["weight/kg"] <= 100 and 0 < x["height/mm"] <= 850
                 and 0 < min(x["length/mm"], x["width/mm"]) <= 1000
                 and 0 < max(x["length/mm"], x["width/mm"]) <= 1200) for x in sequence):
            rejected["mechanical_eligibility"] += 1
            continue
        fingerprint = digest(raw_profile(sequence))
        if fingerprint in fingerprints:
            rejected["duplicate_window"] += 1
            continue
        fingerprints.add(fingerprint)
        selected.append((key, sequence, fingerprint))
        if len(selected) == total:
            break
    if len(selected) != total:
        raise ValueError("not enough distinct eligible unrecorded sources; no substitutions by model outcome")
    return selected, rejected


def scenario_from_raw(key, sequence, index, seed):
    identifier = f"R{index:04d}"
    container = copy.deepcopy(generator_config(load_config())["container"])
    items, attributes = [], {}
    for i, raw in enumerate(sequence):
        item_id = f"box_{i + 1:02d}"
        token = int(digest([seed, key, i])[:16], 16)
        mass = float(raw["weight/kg"])
        item = {"item_id": item_id, "mass_kg": mass,
                "dimensions_mm": {axis: float(raw[axis + "/mm"]) for axis in ("length", "width", "height")},
                "stackable": True, "fragile": bool((token >> 5) & 1),
                "weight_class": "light" if mass < 5 else "medium" if mass < 10 else "heavy",
                "top_load_limit_kg_synthetic": 100., "product_category": "general"}
        items.append(item)
        attributes[item_id] = {"object_id": item_id, "cargo_category": CATEGORIES[token % len(CATEGORIES)],
                               "packaging": {"reinforced": bool((token >> 2) & 1)},
                               "labels": {"no_top_load": token % 7 == 0,
                                          "max_top_load_kg": float((2, 5, 8, 12)[(token >> 7) % 4])},
                               "physical_top_load_limit_kg": 100.}
    return {"scenario_id": identifier, "container": container, "items": items,
            "arrival_order": [item["item_id"] for item in items], "buffer_size": 1}, attributes


def anchors(scenario, config):
    """Three geometry-only prefixes; blocked prefixes retained without replacement."""
    placed, result = [], []
    for index in range(3):
        state = {"request_id": "anchor", "container": scenario["container"],
                 "placed_items": copy.deepcopy(placed), "available_items": [scenario["items"][index]]}
        generated = ExtremePointGenerator(config).generate(PalletState.from_dict(state))
        raw = generated.candidate_set.data["candidates"]
        if any(check_candidate(state, {"container": scenario["container"]}, candidate) for candidate in raw):
            raise O4Error("invalid_candidate", "fixed candidate independent physical audit")
        public, _ = labeled_candidates(raw)
        result.append((copy.deepcopy(state), public))
        if raw:
            chosen = min(raw, key=lambda c: (-geometry_score(c), c["candidate_id"]))
            if check_candidate(state, {"container": scenario["container"]}, chosen):
                raise O4Error("invalid_candidate", "anchor physical audit")
            placed = apply_candidate(state, chosen)
        else:
            # Later prefixes cannot pretend the blocked box was placed.
            break
    return result


def build(output, config_path=DEFAULT_CONFIG, bed_path=DEFAULT_BED):
    design = validate_design(read(config_path))
    audit = source_audit()
    raw = read(bed_path)
    selected, rejected = select_sources(raw, audit, design)
    root = new_directory(output)
    fixed, tasks, scenarios, attributes, registry = [], [], {}, {}, []
    config = generator_config(load_config())
    cursor = 0
    for split, count in design["sources"].items():
        for _ in range(count):
            key, sequence, fingerprint = selected[cursor]
            scenario, attrs = scenario_from_raw(key, sequence, cursor + 1, design["seed"])
            sid = scenario["scenario_id"]
            scenarios[sid], attributes[sid] = scenario, attrs
            states = anchors(scenario, config)
            registry.append({"scenario_id": sid, "source_order_key": key, "split": split,
                             "geometry_mass_fingerprint": fingerprint,
                             "source_sequence_positions": [int(x["sequence"]) for x in sequence]})
            for family, style, track in split_records(split):
                state, candidates = states[CORE.index(family) % len(states) if family in CORE else 0]
                identifier = f"Q{len(fixed) + 1:06d}"
                state = copy.deepcopy(state)
                state["request_id"] = identifier
                text = instruction(family, style)
                req = build_observation(state, attrs, text)
                case = {"case_id": identifier, "source_order_key": key, "scenario_id": sid,
                        "split": split, "track": track, "family": family,
                        "template_family": style, "pair_id": f"{sid}_{family}",
                        "request": req, "reference_policy": specification(family), "candidates": candidates}
                fixed.append(case)
                write(root / "public" / f"{identifier}.json", req)
            for family in design["online_families"]:
                for style in ("canonical", "natural_" + {"development": "development", "calibration": "calibration", "test": "heldout"}[split]):
                    tasks.append({"task_id": f"T{len(tasks) + 1:06d}", "scenario_id": sid,
                                  "source_order_key": key, "split": split, "family": family,
                                  "track": "control" if style == "canonical" else "expression",
                                  "template_family": style, "configuration": family,
                                  "instruction_text": instruction(family, style), "reference_policy": specification(family),
                                  "planned_items": len(sequence)})
            cursor += 1
    inputs = {"fixed": fixed, "tasks": tasks, "scenarios": scenarios, "attributes": attributes, "generator_config": config}
    write(root / "design.json", design)
    write(root / "private/input_snapshot.json", inputs)
    write(root / "private/source_registry.json", registry)
    write(root / "audit/source_audit.json", audit)
    gold = reference_gold()
    if gold["status"] != "PASS":
        raise O4Error("reference_gold_failure")
    write(root / "audit/reference_gold.json", gold)
    write(root / "audit/selection.json", {"raw_orders": len(raw), "selected": len(selected), "rejections": rejected,
          "selection_basis": "seeded source IDs, first N arrivals, mechanical eligibility and duplicate exclusion only",
          "model_outcome_filter": False, "policy_feasibility_filter": False})
    sources = source_hashes()
    for name in sources:
        target = root / "code_snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((WORKSPACE / name).read_bytes())
    write(root / "manifest.json", {"version": VERSION, "design_digest": digest(design), "input_digest": digest(inputs),
          "bed_sha256": file_hash(Path(bed_path)), "source_sha256": sources,
          "data_origin": "new BED-BPP source windows + synthetic physical/semantic attributes",
          "template_origin": "programmatic controlled holdout; not external blind human language",
          "human_review": "NOT_PERFORMED; no fabricated signatures", "role": "reserved_before_real_API"})
    write(root / "delivery_manifest.json", {"files": file_manifest(root)})
    return verify(root)


def verify(root):
    root = Path(root)
    if file_manifest(root) != read(root / "delivery_manifest.json")["files"]:
        raise O4Error("delivery_drift")
    design, inputs, manifest = read(root / "design.json"), read(root / "private/input_snapshot.json"), read(root / "manifest.json")
    validate_design(design)
    if manifest["version"] != VERSION or manifest["design_digest"] != digest(design) or manifest["input_digest"] != digest(inputs):
        raise O4Error("manifest_mismatch")
    verify_sources(manifest["source_sha256"])
    registry = read(root / "private/source_registry.json")
    excluded = set(read(root / "audit/source_audit.json")["excluded_source_values"])
    keys = [row["source_order_key"] for row in registry]
    profiles = [row["geometry_mass_fingerprint"] for row in registry]
    if len(set(keys)) != len(keys) or len(set(profiles)) != len(profiles) or set(keys) & excluded:
        raise O4Error("source_overlap")
    by_id = {row["scenario_id"]: row for row in registry}
    for split, count in design["sources"].items():
        if sum(row["split"] == split for row in registry) != count:
            raise O4Error("manifest_mismatch", "split counts")
    from ..compiler import response_for
    from ..remote_v2.protocol import validate_response
    for case in inputs["fixed"]:
        if read(root / "public" / f"{case['case_id']}.json") != case["request"]:
            raise O4Error("public_input_drift")
        row = by_id[case["scenario_id"]]
        if row["source_order_key"] != case["source_order_key"] or row["split"] != case["split"]:
            raise O4Error("source_overlap", "case provenance")
        validate_response(response_for(case["request"], case["reference_policy"]), case["request"])
    if read(root / "audit/reference_gold.json") != reference_gold():
        raise O4Error("reference_gold_failure")
    return {"status": "PASS", "read_only": True, "real_api_calls": 0, "sources": len(registry),
            "fixed_cases": len(inputs["fixed"]), "online_tasks": len(inputs["tasks"]),
            "splits": {split: sum(row["split"] == split for row in registry) for split in design["sources"]},
            "human_review": "NOT_PERFORMED", "power_certified": False}

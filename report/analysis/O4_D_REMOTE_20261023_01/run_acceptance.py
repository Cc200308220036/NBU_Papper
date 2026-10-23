"""Reproduce this delivery's offline matrices; never contacts a model provider."""
from pathlib import Path
import json
import os
import sys

WORKSPACE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKSPACE / "semantic_pallet_planner/src"))

from semantic_pallet_planner.o4.common import read, write
from semantic_pallet_planner.o4.remote.experiment import execute, file_manifest, prepare
from semantic_pallet_planner.o4.remote.testing import ProtocolServiceDouble
from semantic_pallet_planner.o4.remote.transport import ChatTransport
from semantic_pallet_planner.runners.o4_remote import load_model_config


def main(output):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    config = load_model_config(WORKSPACE / "semantic_pallet_planner/configs/o4_d_deepseek_flash.yaml")
    os.environ[config.api_key_env] = "OFFLINE_ACCEPTANCE_ONLY"
    reports = []
    for name, profile in (("compile", "compile-smoke"), ("fixed", "fixed"), ("orders", "orders-smoke")):
        plan_root = root / (name + "_plan")
        plan = prepare(plan_root, config, profile=profile, task_limit=6)
        print(json.dumps({"starting": name, "jobs": len(plan["jobs"])}, ensure_ascii=False), flush=True)
        service = ProtocolServiceDouble()
        report = execute(plan_root, root / (name + "_run"), budget=plan["maximum_api_attempts"],
                         transport=ChatTransport(config, opener=service, test_double=True))
        reports.append({"matrix": name, "service_requests": len(service.requests),
                        "actual_png_transfers": len(service.image_bytes), **report})
        write(root / "progress.json", reports)
        print(json.dumps(reports[-1], ensure_ascii=False), flush=True)
    summary = read(root / "orders_run/metrics/summary.json")
    controls = []
    for planner in {row["planner"] for row in summary["episodes"]}:
        rows = [row for row in summary["episodes"] if row["planner"] == planner]
        controls.append({"planner": planner,
                         "four_backends_agree": len({(row["completed"], row["mean_item_ratio"], row["mean_volume_ratio"])
                                                     for row in rows}) == 1})
    report = {"status": "PASS" if all(row["status"] == "PASS" for row in reports)
              and all(row["four_backends_agree"] for row in controls) else "FAIL",
              "scope": "O4_D_ENGINEERING_OFFLINE", "real_api_calls": 0,
              "real_model_status": "NOT_RUN_USER_EXECUTES_API",
              "human_review": "NOT_REQUIRED_BY_USER", "matrices": reports,
              "controls": controls, "full_o4_status": "INCOMPLETE"}
    write(root / "offline_acceptance.json", report)
    write(root / "delivery_manifest.json", {"files": file_manifest(root)})
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])

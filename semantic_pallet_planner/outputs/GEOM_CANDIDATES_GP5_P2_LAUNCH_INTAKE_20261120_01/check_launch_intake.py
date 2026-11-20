"""Reproducible read-only intake check for GP5_P2_LAUNCH_MATERIAL_INTAKE_AND_READONLY_PREFLIGHT_ONLY."""
import json
import sys
from pathlib import Path

sys.path.insert(0, "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_PHASE_SNAPSHOT_R3_R1_20261119_01")
import driver as r3_driver

from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.contracts import JevSelectError, digest
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.geometry_native_protocol import policy_digest
from semantic_pallet_planner.jev_select.geometry_order_execution import load_order_config, validate_monitor_snapshot
from semantic_pallet_planner.jev_select.packaging_versions import (
    DEFAULT_GEOMETRY_BACKEND,
    GEOMETRY_OPERATIONAL_PLAN,
)

BASE = Path("semantic_pallet_planner/outputs")
RUNTIME = BASE / "GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01"
PLAN_DIGEST = "248e746c4d3b8063a0f56e2be9f8441b5c34c7c5947147d8da6d67a3396b70e5"
MONITOR_DIGEST = "83b807f6aa8f60a45c1873aebd20fc2aeb04ec5cc924cf2568137bff254f88d6"


def main():
    plan = json.loads((RUNTIME / "acceptance_plan_FROZEN.json").read_bytes())
    snap = json.loads((RUNTIME / "monitor_snapshot.json").read_bytes())
    assert digest(plan) == PLAN_DIGEST
    assert digest(snap) == MONITOR_DIGEST
    p.validate_order_plan(plan)
    validate_monitor_snapshot(snap)
    assert DEFAULT_GEOMETRY_BACKEND == "ems_surface_hybrid_v1"
    assert GEOMETRY_OPERATIONAL_PLAN == "geometry_operational_order_plan_v1"

    found = {"geometry_scope_authorization_v2": [], "geometry_scope_review_v2": [], "geometry_kernel_launch_v2": []}
    for folder in sorted(BASE.glob("*20261120*")):
        for jf in sorted(folder.glob("*.json")):
            try:
                doc = json.loads(jf.read_bytes())
            except Exception:
                continue
            if not isinstance(doc, dict):
                continue
            v = doc.get("version")
            if v in found and doc.get("plan_digest") == PLAN_DIGEST:
                found[v].append(str(jf))

    assert all(not v for v in found.values()), f"Unexpected materials found: {found}"

    # Verify exact stop point at driver.prepare / load_order_config gate without modifying runtime or ledger.
    try:
        r3_driver.prepare(
            RUNTIME,
            RUNTIME / "MISSING_SCOPE_REVIEW.json",
            RUNTIME / "MISSING_KERNEL_LAUNCH.json",
            authorization_reference=None,
        )
    except (FileNotFoundError, JevSelectError, OSError) as exc:
        driver_stop = f"{type(exc).__name__}: {exc}"
    else:
        raise AssertionError("driver.prepare unexpectedly succeeded without launch materials")

    try:
        load_order_config(plan, "J00", monitor_snapshot=snap, admission={})
    except JevSelectError as exc:
        gate_stop = exc.code
    else:
        raise AssertionError("load_order_config unexpectedly succeeded without launch record")

    ledger = json.loads((RUNTIME / "shared_call_ledger.json").read_bytes())
    assert ledger["calls"] == []
    assert ledger["counts"] == {"assessment_entries": 0, "solver_calls": 0, "test_double_assessments": 0}

    print(
        json.dumps(
            {
                "source_identity": digest(source_manifest()),
                "publication_policy_digest": policy_digest(),
                "plan_digest": PLAN_DIGEST,
                "monitor_digest": MONITOR_DIGEST,
                "found_v2_materials": found,
                "driver_prepare_stop": driver_stop,
                "load_order_config_gate_stop": gate_stop,
                "ledger_calls": len(ledger["calls"]),
                "four_job_joint_preflight": "NOT_RUN_BLOCKED_MISSING_LAUNCH_MATERIALS",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

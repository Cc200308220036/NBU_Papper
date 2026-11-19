"""Prepare final Linux host freeze and pending launch request without dispatching."""
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path

from scipy.optimize._highspy import _core

from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.geometry_kernel_completion import required_coverage
from semantic_pallet_planner.jev_select.geometry_native_protocol import identity_fields, policy_digest, wire
from semantic_pallet_planner.jev_select.geometry_order_execution import validate_monitor_snapshot
from semantic_pallet_planner.jev_select.geometry_order_meter import CallBudget
from semantic_pallet_planner.jev_select.ledger import write
from semantic_pallet_planner.jev_select.packaging_versions import (
    DEFAULT_GEOMETRY_BACKEND,
    GEOMETRY_BACKENDS,
    GEOMETRY_OPERATIONAL_PLAN,
)
from semantic_pallet_planner.jev_select.stability.monitor import exact_freeze

BASE = Path("semantic_pallet_planner/outputs")
DEV_RECEIPT = BASE / "GEOM_CANDIDATES_GP5_P2_CONTRACT_ISOLATION_20261119_01" / "source_identity_receipt.json"
HIST = BASE / "GEOM_CANDIDATES_GP5_P2_BOUNDED_REAL_MONITOR_RUNTIME_20261119_01"
RUNTIME = BASE / "GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01"
EXPECTED_HEAD = "2c97f59444f07e40b98da529e5256efc441207d4"


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    assert subprocess.check_output(["git", "branch", "--show-current"], text=True).strip() == "dev/jev-select"
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    assert head == EXPECTED_HEAD, f"Expected {EXPECTED_HEAD}, got {head}"
    assert not (RUNTIME / "acceptance_plan_FROZEN.json").exists(), f"NO_OVERWRITE_RUNTIME_ROOT: {RUNTIME}"

    files = source_manifest()
    dev_receipt = read(DEV_RECEIPT)
    assert len(files) == 594 and files == dev_receipt["files"]
    assert digest(files) == dev_receipt["new_source_identity"]
    assert policy_digest() == dev_receipt["new_publication_policy_digest"]
    assert DEFAULT_GEOMETRY_BACKEND == "ems_surface_hybrid_v1"
    assert GEOMETRY_OPERATIONAL_PLAN == "geometry_operational_order_plan_v1"

    tasks = []
    for case in ("K01", "K02"):
        raw_path = HIST / f"{case}_task.json"
        raw = raw_path.read_bytes()
        task = p.adapt_task(raw, origin="SYNTHETIC_FIXED", expected_sha256=sha(raw_path))
        hist_id = read(HIST / f"{case}_identity.json")
        for key in ("origin", "raw_sha256", "normalized_digest", "runtime_digest", "task_id", "source_group_id"):
            assert task["identity"][key] == hist_id[key], (case, key)
        assert task["identity"]["adapter_digest"] == p.adapter_digest()
        tasks.append(task)

    hist_plan = read(HIST / "acceptance_plan_FROZEN.json")
    plan = p.prepare_order_plan(tasks, data_identity=hist_plan["data_identity"], scope=p.ACCEPTANCE, native=True)
    plan.update(
        status="FROZEN",
        assessment_limit=8,
        solver_limit=128,
        call_ledger_path=str(RUNTIME / "shared_call_ledger.json"),
    )
    p.validate_order_plan(plan)

    snap = exact_freeze()
    validate_monitor_snapshot(snap)

    RUNTIME.mkdir(parents=True, exist_ok=True)
    write(RUNTIME / "monitor_snapshot.json", snap)
    write(RUNTIME / "acceptance_plan_FROZEN.json", plan)
    write(
        RUNTIME / "source_manifest.json",
        {
            "source_files": len(files),
            "source_identity": digest(files),
            "publication_policy_digest": policy_digest(),
            "default_geometry_backend": DEFAULT_GEOMETRY_BACKEND,
            "geometry_backends": list(GEOMETRY_BACKENDS),
            "operational_plan_version": GEOMETRY_OPERATIONAL_PLAN,
            "files": files,
        },
    )
    for case, task in zip(("K01", "K02"), tasks, strict=True):
        (RUNTIME / f"{case}_task.json").write_bytes(task["raw"])
        write(RUNTIME / f"{case}_identity.json", task["identity"])

    budget = CallBudget(RUNTIME / "shared_call_ledger.json", plan, evidence="REAL_KERNEL", job_id="PRESTART_NO_CALL")
    assert budget.value["calls"] == []
    assert budget.value["counts"] == {"assessment_entries": 0, "solver_calls": 0, "test_double_assessments": 0}

    cov = required_coverage(plan)
    run_denom = p.draft_run(plan)
    assert all(row["status"] == "NOT_RUN" for row in run_denom["rows"])
    write(RUNTIME / "required_coverage.json", cov)
    write(RUNTIME / "run_denominator_NOT_RUN.json", run_denom)

    hist_rec = read(HIST / "recovery_NOT_RUN.json")
    recovery = dict(hist_rec, plan_digest=digest(plan), source_identity=digest(files), status="FROZEN_SCOPE_NOT_RUN")
    assert len(recovery["rows"]) == 6 and all(row["status"] == "NOT_RUN" for row in recovery["rows"])
    write(RUNTIME / "recovery_NOT_RUN.json", recovery)

    host_env = {
        "platform": platform.platform(),
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "numpy": importlib.metadata.version("numpy"),
        "scipy": importlib.metadata.version("scipy"),
        "jsonschema": importlib.metadata.version("jsonschema"),
        "highs_version": ".".join(str(getattr(_core, "HIGHS_VERSION_" + k)) for k in ("MAJOR", "MINOR", "PATCH")),
    }

    write(
        RUNTIME / "startup_review_request.json",
        {
            "unit": "GP5_P2_BOUNDED_REAL_MONITOR_USABILITY",
            "status": "PENDING_INDEPENDENT_LAUNCH_REVIEW",
            "plan_digest": digest(plan),
            "source_identity": digest(files),
            "environment_digest": plan["environment_digest"],
            "monitor_digest": digest(snap),
            **identity_fields(plan),
            "default_geometry_backend": DEFAULT_GEOMETRY_BACKEND,
            "operational_plan_version": GEOMETRY_OPERATIONAL_PLAN,
            "plan_reference": {
                "path": str(RUNTIME / "acceptance_plan_FROZEN.json"),
                "sha256": sha(RUNTIME / "acceptance_plan_FROZEN.json"),
            },
            "monitor_reference": {
                "path": str(RUNTIME / "monitor_snapshot.json"),
                "sha256": sha(RUNTIME / "monitor_snapshot.json"),
            },
            "shared_ledger_path": plan["call_ledger_path"],
            "launch_record": "NOT_ISSUED",
            "independent_review": "MISSING",
            "historical_authorization_reused": False,
            "dispatch": "NOT_READY",
            "self_signed_review": False,
            "limits": {"assessment_entries": 8, "solver_calls": 128, "model_calls": 0},
            "primary": 4,
            "recovery": 6,
            "host_environment": host_env,
        },
    )

    write(
        RUNTIME / "freeze_receipt.json",
        {
            "head": head,
            "source_files": len(files),
            "source_identity": digest(files),
            "publication_policy_digest": policy_digest(),
            "default_geometry_backend": DEFAULT_GEOMETRY_BACKEND,
            "operational_plan_version": GEOMETRY_OPERATIONAL_PLAN,
            "plan_digest": digest(plan),
            "monitor_digest": digest(snap),
            "read_only_monitor_validation": "PASS",
            "new_actual_host_freeze": True,
            "historical_freeze_reused": False,
            "historical_authorization_reused": False,
            "raw_inputs_preserved": True,
            "shared_ledger_counts": budget.value["counts"],
            "real_assessments": 0,
            "actual_LP": 0,
            "model_calls": 0,
            "dispatches": 0,
            "recovery_dispatches": 0,
            "host_environment": host_env,
            "stop": "INDEPENDENT_LAUNCH_REVIEW_AND_MATCHING_LAUNCH_RECORD_REQUIRED",
        },
    )

    print(
        json.dumps(
            {
                "runtime_root": str(RUNTIME),
                "plan_digest": digest(plan),
                "monitor_digest": digest(snap),
                "source_identity": digest(files),
                "counts": budget.value["counts"],
                "status": "FROZEN_PENDING_INDEPENDENT_LAUNCH_REVIEW",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

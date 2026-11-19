"""Read-only verification of the new freeze package and unchanged historical runtime."""
import hashlib
import json
import subprocess
from pathlib import Path

from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.geometry_kernel_completion import required_coverage
from semantic_pallet_planner.jev_select.geometry_native_protocol import policy_digest
from semantic_pallet_planner.jev_select.geometry_order_execution import validate_monitor_snapshot

BASE = Path("semantic_pallet_planner/outputs")
HIST = BASE / "GEOM_CANDIDATES_GP5_P2_BOUNDED_REAL_MONITOR_RUNTIME_20261119_01"
RUNTIME = BASE / "GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01"
HEAD = "2c97f59444f07e40b98da529e5256efc441207d4"


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    # 1. Historical runtime untouched vs HEAD
    hist_files = [x for x in HIST.iterdir() if x.is_file()]
    assert len(hist_files) == 19
    for path in hist_files:
        assert path.read_bytes() == subprocess.check_output(["git", "show", f"{HEAD}:{path}"])
    assert read(HIST / "shared_call_ledger.json")["calls"] == []

    # 2. Source & policy match
    files = source_manifest()
    src_doc = read(RUNTIME / "source_manifest.json")
    assert len(files) == 594 and files == src_doc["files"]
    assert digest(files) == src_doc["source_identity"]
    assert policy_digest() == src_doc["publication_policy_digest"]

    # 3. Raw K01/K02 bytes preserved
    for case in ("K01", "K02"):
        assert (RUNTIME / f"{case}_task.json").read_bytes() == (HIST / f"{case}_task.json").read_bytes()
        tid = read(RUNTIME / f"{case}_identity.json")
        adapted = p.adapt_task((RUNTIME / f"{case}_task.json").read_bytes(), origin="SYNTHETIC_FIXED", expected_sha256=tid["raw_sha256"])
        assert adapted["identity"] == tid

    # 4. Frozen plan & monitor snapshot
    plan = read(RUNTIME / "acceptance_plan_FROZEN.json")
    p.validate_order_plan(plan)
    assert plan["status"] == "FROZEN"
    assert plan["scope"] == p.ACCEPTANCE
    assert plan["assessment_limit"] == 8 and plan["solver_limit"] == 128 and plan["model_calls_max"] == 0
    assert [(j["task_id"], j["backend"]) for j in plan["jobs"]] == [
        ("GP5_SYNTH_K01", "e2_original_v1"),
        ("GP5_SYNTH_K01", "ems_surface_hybrid_v1"),
        ("GP5_SYNTH_K02", "e2_original_v1"),
        ("GP5_SYNTH_K02", "ems_surface_hybrid_v1"),
    ]

    snap = read(RUNTIME / "monitor_snapshot.json")
    validate_monitor_snapshot(snap)

    # 5. Zero ledger & NOT_RUN coverage/denominators
    ledger = read(RUNTIME / "shared_call_ledger.json")
    assert ledger["plan_digest"] == digest(plan)
    assert ledger["calls"] == []
    assert ledger["counts"] == {"assessment_entries": 0, "solver_calls": 0, "test_double_assessments": 0}

    cov = read(RUNTIME / "required_coverage.json")
    assert cov == required_coverage(plan)
    assert len(cov["primary"]) == 4 and len(cov["recovery"]) == 6

    run_denom = read(RUNTIME / "run_denominator_NOT_RUN.json")
    assert run_denom["plan_digest"] == digest(plan)
    assert len(run_denom["rows"]) == 4 and all(r["status"] == "NOT_RUN" for r in run_denom["rows"])

    rec = read(RUNTIME / "recovery_NOT_RUN.json")
    assert rec["plan_digest"] == digest(plan) and rec["source_identity"] == digest(files)
    assert rec["denominator"] == 6 and len(rec["rows"]) == 6
    assert all(r["status"] == "NOT_RUN" for r in rec["rows"])

    # 6. Pending startup review request (no launch record, no historical authorization reuse)
    req = read(RUNTIME / "startup_review_request.json")
    assert req["launch_record"] == "NOT_ISSUED"
    assert req["independent_review"] == "MISSING"
    assert req["historical_authorization_reused"] is False
    assert req["dispatch"] == "NOT_READY"
    assert req["self_signed_review"] is False
    assert req["plan_digest"] == digest(plan)
    assert req["monitor_digest"] == digest(snap)
    assert req["plan_reference"]["sha256"] == sha(RUNTIME / "acceptance_plan_FROZEN.json")
    assert req["monitor_reference"]["sha256"] == sha(RUNTIME / "monitor_snapshot.json")
    assert Path(req["shared_ledger_path"]) == RUNTIME / "shared_call_ledger.json"

    print("READ_ONLY_FREEZE_VERIFICATION_PASS")


if __name__ == "__main__":
    main()

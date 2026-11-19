"""Verify Git archives and startup-material coverage without importing business code."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess

REVIEWED = "705db06a79a5fe590959637c36aa62bc6116e06b"
DELIVERY = "d34aa6f6368ab6cb9c970b5a96b14cb3897d9d4f"
PARENT_QA = "2a4d20430ccd0cf01ebdb6935d71c1e4a2ae172b"
OUT = Path("semantic_pallet_planner/outputs")
DEV = OUT / "GEOM_CANDIDATES_GP5_P2_LAUNCH_REVIEW_PREFLIGHT_20261120_01"
RUNTIME = OUT / "GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01"
DRIVER = OUT / "GEOM_CANDIDATES_GP5_P2_PHASE_SNAPSHOT_R3_R1_20261119_01/driver.py"
SOURCE = "semantic_pallet_planner/src"

def git(*args):
    return subprocess.check_output(["git", *args])

def blob(revision, path):
    return git("show", f"{revision}:{path}")

def doc(revision, path):
    return json.loads(blob(revision, path))

def main():
    assert git("rev-parse", DELIVERY + "^").decode().strip() == PARENT_QA
    assert git("rev-parse", REVIEWED + "^").decode().strip() == DELIVERY
    assert not git("diff", "--name-only", PARENT_QA, REVIEWED, "--", SOURCE, str(RUNTIME), str(DRIVER))

    manifest = doc(DELIVERY, DEV / "manifest.json")
    assert manifest["synced_head"] == PARENT_QA
    assert len(manifest["files"]) == 5
    for item in manifest["files"]:
        raw = blob(DELIVERY, item["path"])
        assert (len(raw), sha256(raw).hexdigest()) == (item["bytes"], item["sha256"])

    handoff = doc(REVIEWED, DEV / "handoff.json")
    freeze = doc(REVIEWED, RUNTIME / "handoff.json")
    receipts = doc(REVIEWED, DEV / "command_receipts.json")
    gaps = doc(REVIEWED, DEV / "launch_material_gaps.json")
    request = doc(REVIEWED, RUNTIME / "startup_review_request.json")
    ledger = doc(REVIEWED, RUNTIME / "shared_call_ledger.json")
    assert handoff["synced_head"] == receipts["synced_head"] == PARENT_QA
    for key, value in handoff["identities"].items():
        assert freeze[key] == gaps[key] == value
    assert not ledger["calls"]
    assert all(value == 0 for value in handoff["actual_this_delivery"].values())
    assert handoff["actual_this_delivery"] == receipts["actual_this_delivery"]
    preflight = "NOT_RUN_BLOCKED_MISSING_LAUNCH_MATERIALS"
    assert handoff["checks"]["four_job_joint_preflight"] == receipts["four_job_joint_preflight"] == gaps["four_job_joint_preflight_status"] == preflight
    versions = {row["artifact"] for row in gaps["missing_materials"] if row["status"] == "MISSING"}
    assert versions == {"geometry_scope_authorization_v2", "geometry_scope_review_v2", "geometry_kernel_launch_v2"}
    assert "authorization_reference" not in request

    # Look for the new plan digest first, then accept only top-level v2 artifacts.
    plan = handoff["identities"]["plan_digest"]
    candidates = git("grep", "-l", "-F", plan, REVIEWED, "--", str(OUT), ":(glob)**/*.json")
    for candidate in candidates.decode().splitlines():
        revision, path = candidate.split(":", 1)
        artifact = doc(revision, path)
        if isinstance(artifact, dict):
            assert not (artifact.get("version") in versions and artifact.get("plan_digest") == plan), path
    print("PASS: developer reached parent QA; five delivery bytes match; source, driver and freeze unchanged.")
    print("PASS: handoff, freeze, receipts and gaps agree; frozen ledger empty; no matching v2 material in tracked JSON.")
    print("NOT_RUN: four-job joint preflight, four primary jobs and six recoveries.")

if __name__ == "__main__":
    main()

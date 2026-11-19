"""Verify saved GP5-P2 prelaunch evidence without importing production code."""

import hashlib
import json
import platform
from pathlib import Path
import subprocess

OUT = Path("semantic_pallet_planner/outputs")
PREFIX = "GEOM_CANDIDATES_GP5_P2_BOUNDED_REAL_MONITOR"
PRESTART = OUT / f"{PREFIX}_PRESTART_20261119_01"
RUNTIME = OUT / f"{PREFIX}_RUNTIME_20261119_01"
R1 = OUT / "GEOM_CANDIDATES_GP5_P2_R1_EXTERNAL_REVIEW_BINDING_20261119_01"
SOURCE = Path("semantic_pallet_planner/src/semantic_pallet_planner")
DEV = "39d0884c9120c03082867d50d169911877ab51e8"
ENTRY = "0e37ced18c93ec2395766b5e8ab7c17095e35673"
PREVIOUS_QA = "52766787cdac095ce2d6724adfe8373fc39598e8"


def git(*args):
    return subprocess.check_output(["git", *args])


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode())


assert not git("diff", "--name-only", PREVIOUS_QA, ENTRY, "--", str(SOURCE))
for directory, count in ((PRESTART, 9), (RUNTIME, 20)):
    manifest = load(directory / "delivery_manifest.json")
    assert git("show", f"{DEV}:{directory}/delivery_manifest.json") == (directory / "delivery_manifest.json").read_bytes()
    rows = manifest["files"]
    assert len({r["path"] for r in rows}) == len(rows) == manifest["member_count"] == count
    for row in rows:
        path = Path(row["path"])
        raw = git("show", f"{DEV}:{path}")
        assert len(raw) == row["size_bytes"] and sha(raw) == row["sha256"], path
        if path.name != "README.md":
            assert path.read_bytes() == raw, path

source_manifest = load(RUNTIME / "source_manifest.json")
files = {}
for path in SOURCE.rglob("*"):
    relative = path.relative_to(SOURCE)
    if path.is_file() and path.suffix in (".py", ".json") and not {"tests", "__pycache__"}.intersection(relative.parts):
        files[relative.as_posix()] = sha(path.read_bytes())
assert files == source_manifest["files"] == load(R1 / "source_manifest.json")["files"]
assert len(files) == source_manifest["source_files"] == 591
source_identity = digest(files)
assert source_identity == source_manifest["source_identity"]

plan = load(RUNTIME / "acceptance_plan_FROZEN.json")
draft = load(R1 / "acceptance_plan_DRAFT.json")
ledger_path = RUNTIME / "shared_call_ledger.json"
assert plan == {**draft, "status": "FROZEN", "call_ledger_path": str(ledger_path)}
assert plan["source_identity"] == source_identity
assert (plan["assessment_limit"], plan["solver_limit"], plan["model_calls_max"]) == (8, 128, 0)
assert plan["event_limit"] is None and plan["extra_seeds"] is False
for case, identity in zip(("K01", "K02"), plan["tasks"]):
    raw = (RUNTIME / f"{case}_task.json").read_bytes()
    assert raw == (R1 / f"{case}_task.json").read_bytes()
    assert sha(raw) == identity["raw_sha256"]
    assert identity == load(RUNTIME / f"{case}_identity.json") == load(R1 / f"{case}_identity.json")
plan_digest = digest(plan)
assert plan_digest == "2e97da50ad87c91b50b0259129f1dfc0b584e11c653d23a9a25830f3499d6433"

monitor = load(RUNTIME / "monitor_snapshot.json")
identity = monitor["algorithm_identity"]
assert monitor["enabled"] and monitor["algorithm"] == identity["algorithm"] == "pct_exact_pose_network_v3"
assert identity["source_digest"] == digest(identity["files_sha256"])
assert identity["dependency_digest"] == digest(identity["dependencies"])
for name, checksum in identity["files_sha256"].items():
    assert sha((SOURCE / "jev_select/stability" / name).read_bytes()) == checksum, name
monitor_digest = digest(monitor)
assert monitor_digest == "b6cda604eaf1640c48c7d6d71fb536f4ef777cac56ca2de0c01b8ed4dda3ab07"

request = load(RUNTIME / "startup_review_request.json")
authorization = load(RUNTIME / "user_authorization.json")
provenance = load(RUNTIME / "authorization_provenance.json")
handoff = load(RUNTIME / "handoff.json")
freeze = load(RUNTIME / "freeze_receipt.json")
for record in (request, provenance, handoff, freeze):
    assert record["plan_digest"] == plan_digest and record["monitor_digest"] == monitor_digest
assert request["environment_digest"] == plan["environment_digest"]
assert request["source_identity"] == freeze["source_identity"] == source_identity
for field, filename in (("plan_reference", "acceptance_plan_FROZEN.json"),
                        ("monitor_reference", "monitor_snapshot.json"),
                        ("authorization_reference", "user_authorization.json")):
    target = RUNTIME / filename
    assert request[field] == {"path": str(target), "sha256": sha(target.read_bytes())}
assert provenance["authorization_reference"] == request["authorization_reference"]
assert request["limits"] == provenance["authorized_limits"] == handoff["limits"] == {
    "assessment_entries": 8, "solver_calls": 128, "model_calls": 0,
}
assert provenance["user_message_exact"] == "我明确授权执行"
assert authorization == {
    "version": "geometry_scope_authorization_v2", "status": "APPROVED",
    "plan_digest": plan_digest, **{k: plan[k] for k in ("scope", "runtime_version", "publication_policy_digest")},
}
assert all(request[k] == plan[k] for k in ("runtime_version", "publication_policy_digest"))
assert request["shared_ledger_path"] == str(ledger_path)
assert request["self_signed_review"] is False
assert request["independent_review"] == "MISSING" and request["launch_record"] == "NOT_ISSUED"
assert request["dispatch"] == handoff["dispatch"] == "NOT_READY"

zero = {"assessment_entries": 0, "solver_calls": 0, "test_double_assessments": 0}
assert load(ledger_path) == {
    "version": "geometry_call_ledger_v1", "evidence": "REAL_KERNEL",
    "plan_digest": plan_digest, "calls": [], "counts": zero,
    "limits": {"assessment_entries": 8, "solver_calls": 128},
}
assert freeze["shared_ledger_counts"] == zero
assert all(freeze[k] == 0 for k in ("real_assessments", "actual_LP", "model_calls", "dispatches", "recovery_dispatches"))
coverage = load(RUNTIME / "required_coverage.json")
assert coverage == load(R1 / "required_coverage.json")
primary = load(RUNTIME / "run_denominator_NOT_RUN.json")
recovery = load(RUNTIME / "recovery_NOT_RUN.json")
assert primary["plan_digest"] == recovery["plan_digest"] == plan_digest
assert len(primary["rows"]) == 4
assert primary["rows"] == [{"job_id": row["job_id"], "status": "NOT_RUN", "metrics": None} for row in coverage["primary"]]
assert len(recovery["rows"]) == recovery["denominator"] == 6
assert [{k: row[k] for k in ("job_id", "phase")} for row in recovery["rows"]] == coverage["recovery"]
assert all(row["status"] == "NOT_RUN" for row in recovery["rows"])

print("Verified 9 PRESTART and 20 RUNTIME manifest members at the developer revision.")
print(f"Verified {len(files)} production files, {len(identity['files_sha256'])} monitor files and both original task identities.")
print(f"FROZEN plan {plan_digest}, monitor {monitor_digest}.")
print("Authorization transcription and references match; no independent review or launch receipt in the handoff.")
print("Limits 8/128/0; ledger empty; 4 primary and 6 recoveries NOT_RUN.")
print(f"QA host: {platform.system()}; saved monitor host: {monitor['execution_environment']['platform']}.")

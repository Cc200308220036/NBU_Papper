"""Check the committed freeze using Git blobs; never run the freezer or planner."""
from pathlib import Path
import hashlib
import json
import subprocess

BASE = "2c97f59444f07e40b98da529e5256efc441207d4"
REV = "195e1138884306a09e6329150798816ffd747919"
OUT = Path("semantic_pallet_planner/outputs")
NEW = OUT / "GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01"
OLD = OUT / "GEOM_CANDIDATES_GP5_P2_BOUNDED_REAL_MONITOR_RUNTIME_20261119_01"
SOURCE = Path("semantic_pallet_planner/src/semantic_pallet_planner")


def git(*args):
    return subprocess.check_output(["git", *args])


def blob(path, revision=REV):
    return git("show", f"{revision}:{path}")


def doc(name):
    return json.loads(blob(NEW / name))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(doc):
    return sha(json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())


assert not git("diff", "--name-only", BASE, REV, "--", str(SOURCE), str(OLD))
manifest = doc("manifest.json")["files"]
assert len(manifest) == len({row["path"] for row in manifest}) == 19
for row in manifest:
    raw = blob(row["path"])
    assert len(raw) == row["bytes"] and sha(raw) == row["sha256"], row["path"]
old_files = git("ls-tree", "-r", "--name-only", REV, "--", str(OLD)).decode().splitlines()
assert len(old_files) == 19
assert all(blob(path) == blob(path, BASE) for path in old_files)
source = doc("source_manifest.json")
receipt = json.loads(blob(OUT / "GEOM_CANDIDATES_GP5_P2_CONTRACT_ISOLATION_20261119_01" / "source_identity_receipt.json"))
assert len(source["files"]) == source["source_files"] == 594
assert source["files"] == receipt["files"]
assert digest(source["files"]) == source["source_identity"] == receipt["new_source_identity"]
assert source["publication_policy_digest"] == receipt["new_publication_policy_digest"]
assert source["default_geometry_backend"] == "ems_surface_hybrid_v1"

plan = doc("acceptance_plan_FROZEN.json")
snap = doc("monitor_snapshot.json")
request = doc("startup_review_request.json")
freeze = doc("freeze_receipt.json")
handoff = doc("handoff.json")
ledger = doc("shared_call_ledger.json")
limits = {"assessment_entries": 8, "solver_calls": 128, "model_calls": 0}
assert plan["status"] == "FROZEN" and plan["scope"] == "KERNEL_ACCEPTANCE_SYNTHETIC_ONLY"
assert plan["source_identity"] == source["source_identity"]
assert plan["publication_policy_digest"] == source["publication_policy_digest"]
assert (plan["assessment_limit"], plan["solver_limit"], plan["model_calls_max"]) == (8, 128, 0)
assert plan["event_limit"] is None and not plan["extra_seeds"]
assert plan["call_ledger_path"] == request["shared_ledger_path"] == str(NEW / "shared_call_ledger.json")
for record in (request, freeze, handoff):
    assert record["plan_digest"] == digest(plan)
    assert record["monitor_digest"] == digest(snap)
    assert record["source_identity"] == source["source_identity"]
assert handoff["default_route_identity"] == receipt["default_route_identity"]
assert request["environment_digest"] == plan["environment_digest"]
assert request["limits"] == handoff["limits"] == limits
assert request["status"] == "PENDING_INDEPENDENT_LAUNCH_REVIEW"
assert request["dispatch"] == "NOT_READY" and request["launch_record"] == "NOT_ISSUED"
assert request["independent_review"] == "MISSING" and request["self_signed_review"] is False
assert "authorization_reference" not in request and request["historical_authorization_reused"] is False
assert freeze["historical_freeze_reused"] is False and freeze["new_actual_host_freeze"] is True
for key, name in (("plan_reference", "acceptance_plan_FROZEN.json"), ("monitor_reference", "monitor_snapshot.json")):
    assert request[key] == {"path": str(NEW / name), "sha256": sha(blob(NEW / name))}, key
host = request["host_environment"]
env = snap["execution_environment"]
assert freeze["host_environment"] == host and host["python_executable"] == env["executable"]
assert host["platform"] == env["platform"] and env["python"].split()[0] == host["python_version"]
algorithm = snap["algorithm_identity"]
assert digest(algorithm["files_sha256"]) == algorithm["source_digest"]
assert digest(algorithm["dependencies"]) == algorithm["dependency_digest"]
for name, checksum in algorithm["files_sha256"].items():
    assert sha(blob(SOURCE / "jev_select/stability" / name)) == checksum, name
assert host["numpy"] == env["numpy"] == algorithm["dependencies"]["numpy"]
assert all(host[name] == algorithm["dependencies"][name] for name in ("scipy", "highs_version"))
for case, task in zip(("K01", "K02"), plan["tasks"], strict=True):
    name = f"{case}_task.json"
    assert blob(NEW / name) == blob(OLD / name)
    assert sha(blob(NEW / name)) == task["raw_sha256"]
    assert doc(f"{case}_identity.json") == task and task["task_id"] == f"GP5_SYNTH_{case}"
matrix = [(f"J{i:02}", f"GP5_SYNTH_K{1+i//2:02}", ("e2_original_v1", "ems_surface_hybrid_v1")[i%2]) for i in range(4)]
assert [(job["job_id"], job["task_id"], job["backend"]) for job in plan["jobs"]] == matrix
coverage = doc("required_coverage.json")
assert [(row["job_id"], row["task_id"], row["backend"]) for row in coverage["primary"]] == matrix
main = doc("run_denominator_NOT_RUN.json")
recovery = doc("recovery_NOT_RUN.json")
assert main["plan_digest"] == recovery["plan_digest"] == ledger["plan_digest"] == digest(plan)
assert main["rows"] == [{"job_id": jid, "status": "NOT_RUN", "metrics": None} for jid, *_ in matrix]
assert len(recovery["rows"]) == recovery["denominator"] == 6
assert all(r["status"] == "NOT_RUN" for r in recovery["rows"])
assert [{k: r[k] for k in ("job_id", "phase")} for r in recovery["rows"]] == coverage["recovery"]
assert coverage["recovery"] == [{"job_id": j, "phase": phase} for j in ("J00", "J01") for phase in ("SELECTED", "MONITORED", "COMMITTED")]
assert ledger["evidence"] == "REAL_KERNEL" and ledger["calls"] == []
assert ledger["limits"] == {"assessment_entries": 8, "solver_calls": 128}
assert ledger["counts"] == {"assessment_entries": 0, "solver_calls": 0, "test_double_assessments": 0}
print("Verified 19 manifest members, 594-source identity, 19 historical runtime files, two unchanged task inputs, and archived environment and monitor bytes.")
print(f"Plan {digest(plan)}; monitor {digest(snap)}.")
print("Four primary and six recovery rows NOT_RUN; zero ledger; no authorization reference, independent review or launch in the startup request.")

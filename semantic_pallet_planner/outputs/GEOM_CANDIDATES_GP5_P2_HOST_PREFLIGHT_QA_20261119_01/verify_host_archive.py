"""Check archived host observations without running the producer or planner."""
import hashlib
import json
from pathlib import Path
import subprocess

out = Path("semantic_pallet_planner/outputs")
host = out / "GEOM_CANDIDATES_GP5_P2_HOST_PREFLIGHT_20261119_01"
runtime = out / "GEOM_CANDIDATES_GP5_P2_BOUNDED_REAL_MONITOR_RUNTIME_20261119_01"
rev = "52919d84fe065d3edd7f97486e3058428ecebe32"
previous = "30d9cd194be224817d4b6a87e9eff15d7fdc92ac"


def git(*args):
    return subprocess.check_output(["git", *args])


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode())


manifest_path = host / "delivery_manifest.json"
assert git("show", f"{rev}:{manifest_path}") == manifest_path.read_bytes()
manifest = load(manifest_path)
rows = manifest["files"]
assert len({row["path"] for row in rows}) == len(rows) == manifest["member_count"] == 6
for row in rows:
    path = Path(row["path"])
    raw = git("show", f"{rev}:{path}")
    assert len(raw) == row["size_bytes"] and sha(raw) == row["sha256"], path
    if path.name != "README.md":
        assert path.read_bytes() == raw, path
assert not git("diff", "--name-only", previous, rev, "--", "semantic_pallet_planner/src", str(runtime))
result = load(host / "host_preflight.json")
handoff = load(host / "handoff.json")
for key in ("host_preflight", "synced_head", "source_identity", "plan_digest", "monitor_digest",
            "independent_review", "launch_record", "dispatch", "primary", "recovery"):
    assert result[key] == handoff[key], key
assert result["synced_head"] == "e34f80f2991552b3079d3f3de630a213513d47fd"
assert result["host_preflight"] == "PASS_READONLY"
files = {str(p): sha(p.read_bytes()) for p in runtime.rglob("*") if p.is_file()}
assert len(files) == 19 and files == result["runtime_file_hashes"]
plan = load(runtime / "acceptance_plan_FROZEN.json")
monitor = load(runtime / "monitor_snapshot.json")
assert result["plan_digest"] == digest(plan)
assert result["monitor_digest"] == digest(monitor)
assert plan["source_identity"] == result["source_identity"]
assert digest(result["actual_order_environment"]) == plan["environment_digest"]
assert result["actual_monitor_environment"] == monitor["execution_environment"]
assert result["dependency_identity"] == monitor["algorithm_identity"]["dependencies"]
assert result["ledger"] == load(runtime / "shared_call_ledger.json")
assert result["ledger"]["calls"] == [] and set(result["ledger"]["counts"].values()) == {0}
assert all(result[k] == 0 for k in ("real_assessments_this_turn", "actual_LP_this_turn",
                                   "model_calls_this_turn", "freeze_this_turn"))
assert result["independent_review"] == "MISSING" and result["launch_record"] == "NOT_ISSUED"
assert result["four_job_joint_admission_preflight"] == "NOT_RUN_MISSING_REVIEW_AND_LAUNCH"
assert result["dispatch"] == "NOT_READY"
assert result["primary"] == "4/4 NOT_RUN" and result["recovery"] == "6/6 NOT_RUN"
assert load(host / "command_receipts.json")["real_dispatch"] == 0
print("Verified six delivery members, 19 unchanged runtime files and the archived Linux environment, dependencies, fingerprints and empty ledger.")
print("Four-job joint admission preflight, main execution and recoveries are still NOT_RUN.")

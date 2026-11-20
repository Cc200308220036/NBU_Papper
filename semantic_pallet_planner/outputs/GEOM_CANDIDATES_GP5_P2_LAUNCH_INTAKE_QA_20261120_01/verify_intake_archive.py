"""Check frozen Git evidence without importing or running the planner."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess


HEAD = "712401c7ee74396f906340fa1030dc973c16056d"
PARENT = "5d5904173250d607be5b395cec894f9fc3edeb20"
FREEZE = "195e1138884306a09e6329150798816ffd747919"
BASE = Path("semantic_pallet_planner/outputs")
PACKAGE = "GEOM_CANDIDATES_GP5_P2_"
ROOT = BASE / (PACKAGE + "FINAL_RUNTIME_20261120_01")
DEV = BASE / (PACKAGE + "LAUNCH_INTAKE_20261120_01")
DRIVER = BASE / (PACKAGE + "PHASE_SNAPSHOT_R3_R1_20261119_01") / "driver.py"
SOURCE = Path("semantic_pallet_planner/src/semantic_pallet_planner")
VERSIONS = {"geometry_scope_authorization_v2", "geometry_scope_review_v2", "geometry_kernel_launch_v2"}


def git(*args):
    return subprocess.check_output(["git", *args])


def blob(path, revision=HEAD):
    return git("show", f"{revision}:{path}")


def doc(path, revision=HEAD):
    return json.loads(blob(path, revision))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())


def constants(path):
    return {node.targets[0].id: node.value.value for node in ast.parse(path.read_bytes()).body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)}


def main():
    assert git("rev-parse", HEAD + "^").decode().strip() == PARENT
    assert not git("diff", "--name-only", FREEZE, HEAD, "--", str(ROOT), str(SOURCE), str(DRIVER))
    counts = []
    for suffix, filename, revision in (
        ("FINAL_RUNTIME", "manifest.json", FREEZE),
        ("LAUNCH_REVIEW_PREFLIGHT", "manifest.json", "d34aa6f6368ab6cb9c970b5a96b14cb3897d9d4f"),
        ("LAUNCH_REVIEW_PREFLIGHT_QA", "delivery_manifest.json", PARENT),
        ("LAUNCH_INTAKE", "manifest.json", HEAD),
    ):
        directory = BASE / (PACKAGE + suffix + "_20261120_01")
        entries = doc(directory / filename, revision)["files"]
        counts.append(len(entries))
        for entry in entries:
            raw = blob(entry["path"], revision)
            assert (len(raw), sha(raw)) == (entry["bytes"], entry["sha256"]), entry["path"]
    assert counts == [19, 5, 7, 6], counts

    handoff = doc(DEV / "handoff.json")
    receipts = doc(DEV / "command_receipts.json")
    gaps = doc(DEV / "launch_material_gaps.json")
    frozen = doc(ROOT / "handoff.json")
    plan = doc(ROOT / "acceptance_plan_FROZEN.json")
    monitor = doc(ROOT / "monitor_snapshot.json")
    request = doc(ROOT / "startup_review_request.json")
    ledger = doc(ROOT / "shared_call_ledger.json")
    sources = doc(ROOT / "source_manifest.json")
    assert handoff["synced_head"] == receipts["synced_head"] == gaps["synced_head"] == PARENT
    for key, value in handoff["identities"].items():
        assert frozen[key] == gaps[key] == value, key
    for key in ("source_identity", "publication_policy_digest", "environment_digest", "runtime_version"):
        assert request[key] == plan[key], key
    assert digest(plan) == request["plan_digest"] == frozen["plan_digest"] == ledger["plan_digest"]
    assert digest(monitor) == request["monitor_digest"] == frozen["monitor_digest"]
    for name, filename in (("plan_reference", "acceptance_plan_FROZEN.json"), ("monitor_reference", "monitor_snapshot.json")):
        assert request[name] == {"path": str(ROOT / filename), "sha256": sha(blob(ROOT / filename))}
    assert plan["call_ledger_path"] == request["shared_ledger_path"] == str(ROOT / "shared_call_ledger.json")
    assert "authorization_reference" not in request and request["launch_record"] == "NOT_ISSUED"
    assert len(sources["files"]) == 594 and digest(sources["files"]) == sources["source_identity"] == plan["source_identity"]
    tracked = git("ls-tree", "-rz", "--name-only", HEAD, "--", str(SOURCE)).decode().strip("\0").split("\0")
    actual = {Path(path).relative_to(SOURCE).as_posix() for path in tracked
              if Path(path).suffix in {".py", ".json"} and not {"tests", "__pycache__"}.intersection(Path(path).relative_to(SOURCE).parts)}
    assert actual == set(sources["files"])
    for name, expected in sources["files"].items():
        assert sha((SOURCE / name).read_bytes()) == expected, name
    module = SOURCE / "jev_select"
    versions = constants(module / "packaging_versions.py")
    policy_files = ("geometry_native_protocol.py", "geometry_native_shape_bridge.py")
    policy = digest({"policy": versions["GEOMETRY_NATIVE_POLICY"], "bridge": versions["GEOMETRY_NATIVE_BRIDGE"],
                     "key_equivalence": constants(module / policy_files[1])["KEY_EQUIVALENCE"],
                     "source_sha256": digest({name: sha((module / name).read_bytes()) for name in policy_files})})
    assert policy == sources["publication_policy_digest"] == plan["publication_policy_digest"]
    assert versions["DEFAULT_GEOMETRY_BACKEND"] == sources["default_geometry_backend"] == request["default_geometry_backend"] == "ems_surface_hybrid_v1"
    assert versions["GEOMETRY_OPERATIONAL_PLAN"] == sources["operational_plan_version"] == request["operational_plan_version"]
    for name, expected in monitor["algorithm_identity"]["files_sha256"].items():
        assert sha((SOURCE / "jev_select/stability" / name).read_bytes()) == expected, name
    assert digest(monitor["algorithm_identity"]["dependencies"]) == monitor["algorithm_identity"]["dependency_digest"]
    assert digest(monitor["algorithm_identity"]["files_sha256"]) == monitor["algorithm_identity"]["source_digest"]
    host = receipts["host_environment"]
    assert host == doc(ROOT / "command_receipts.json")["host_environment"]
    assert all(host[key] == monitor["algorithm_identity"]["dependencies"][key] for key in ("numpy", "scipy", "highs_version"))
    assert host["platform"] == monitor["execution_environment"]["platform"]
    assert host["python_executable"] == monitor["execution_environment"]["executable"]
    assert (plan["assessment_limit"], plan["solver_limit"], plan["model_calls_max"]) == (8, 128, 0)
    jobs = [(f"J{index:02}", f"GP5_SYNTH_K{1 + index // 2:02}", ("e2_original_v1", "ems_surface_hybrid_v1")[index % 2]) for index in range(4)]
    assert [(job["job_id"], job["task_id"], job["backend"]) for job in plan["jobs"]] == jobs
    primary = doc(ROOT / "run_denominator_NOT_RUN.json")
    recovery = doc(ROOT / "recovery_NOT_RUN.json")
    assert primary["plan_digest"] == recovery["plan_digest"] == digest(plan)
    assert [(row["job_id"], row["status"], row["metrics"]) for row in primary["rows"]] == [(job[0], "NOT_RUN", None) for job in jobs]
    assert recovery["denominator"] == 6 and [(row["job_id"], row["phase"], row["status"]) for row in recovery["rows"]] == [
        (job, phase, "NOT_RUN") for job in ("J00", "J01") for phase in ("SELECTED", "MONITORED", "COMMITTED")]
    assert ledger["calls"] == [] and ledger["counts"] == {"assessment_entries": 0, "solver_calls": 0, "test_double_assessments": 0}
    assert handoff["actual_this_delivery"] == receipts["actual_this_delivery"] and not any(receipts["actual_this_delivery"].values())
    assert {row["artifact"] for row in gaps["missing_materials"] if row["status"] == "MISSING"} == VERSIONS
    matches = git("grep", "-lz", "-F", digest(plan), HEAD, "--", "*.json").decode().strip("\0").split("\0")
    for match in matches:
        path = match.split(":", 1)[1]
        candidate = doc(path)
        assert not (isinstance(candidate, dict) and candidate.get("version") in VERSIONS and candidate.get("plan_digest") == digest(plan)), path
    print(f"PASS manifests={counts}; source_files=594; matching_plan_json={len(matches)}; matching_v2_records=0; ledger_calls=0")
    print("NOT_RUN joint preflight J00–J03, primary 4, recovery 6; no planner imports or dispatch")


if __name__ == "__main__":
    main()

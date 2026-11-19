"""Verify the sealed archive and exercise plan and pre-dispatch contracts only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import traceback
from unittest.mock import patch

out = Path("semantic_pallet_planner/outputs")
dev = out / "GEOM_CANDIDATES_GP5_P2_CONTRACT_ISOLATION_20261119_01"
runtime = out / "GEOM_CANDIDATES_GP5_P2_BOUNDED_REAL_MONITOR_RUNTIME_20261119_01"
source = Path("semantic_pallet_planner/src/semantic_pallet_planner")
head = "2c97f59444f07e40b98da529e5256efc441207d4"
base = "ca5c39c7c21a909b0ee46a411174420e6451001f"


def load(path):
    return json.loads(path.read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args])


manifest = load(dev / "manifest.json")["files"]
assert len(manifest) == len({row["path"] for row in manifest}) == 9
for row in manifest:
    path = Path(row["path"])
    raw = git("show", f"{head}:{path}")
    assert len(raw) == row["bytes"] and sha(raw) == row["sha256"], path
    if path.name != "README.md":
        assert raw == path.read_bytes(), path
source_receipt = load(dev / "source_identity_receipt.json")
source_files = {}
for path in source.rglob("*"):
    rel = path.relative_to(source)
    if path.is_file() and path.suffix in (".py", ".json") and not {"tests", "__pycache__"}.intersection(rel.parts):
        source_files[rel.as_posix()] = sha(path.read_bytes())
assert len(source_files) == 594 and source_files == source_receipt["files"]
historical = [path for path in runtime.iterdir() if path.is_file()]
assert len(historical) == 19
assert all(path.read_bytes() == git("show", f"{base}:{path}") for path in historical)
assert load(runtime / "shared_call_ledger.json")["calls"] == []
print("Verified 9 manifest entries, 594 production files and 19 unchanged historical runtime files.")

from semantic_pallet_planner.jev_select import packaging_geometry_protocol as protocol
from semantic_pallet_planner.jev_select.contracts import JevSelectError, digest
from semantic_pallet_planner.jev_select.geometry_kernel_completion import required_coverage
from semantic_pallet_planner.jev_select.geometry_native_protocol import policy_digest

assert digest(source_files) == source_receipt["new_source_identity"]
assert policy_digest() == source_receipt["new_publication_policy_digest"]
tasks = []
for case in ("K01", "K02"):
    raw = (runtime / f"{case}_task.json").read_bytes()
    tasks.append(protocol.adapt_task(raw, origin="SYNTHETIC_FIXED", expected_sha256=sha(raw)))
identity = digest("QA_CONTRACT_ONLY")
for backend in (None, "e2_original_v1"):
    plan = protocol.prepare_operational_order_plan(tasks, data_identity=identity, backend=backend)
    assert plan["version"] == "geometry_operational_order_plan_v1"
    assert all(job["backend"] == (backend or "ems_surface_hybrid_v1") for job in plan["jobs"])
    assert plan["assessment_limit"] == plan["solver_limit"] == 0
    try:
        protocol.validate_operational_order_plan({**plan, "scope": protocol.ACCEPTANCE})
    except JevSelectError:
        pass
    else:
        raise AssertionError("Operational schema must reject real acceptance scope")

for native in (False, True):
    fixed = protocol.prepare_order_plan(tasks, data_identity=identity, scope=protocol.ACCEPTANCE, native=native)
    assert len(required_coverage(fixed)["primary"]) == 4
    for job_list in (fixed["jobs"][:-1], fixed["jobs"][1::2]):
        try:
            protocol.validate_order_plan({**fixed, "jobs": job_list})
        except JevSelectError as exc:
            assert exc.code == "geometry_order_matrix", exc
        else:
            raise AssertionError("Fixed scope must reject missing jobs and single backend")
print("Operational EMS/E2 routing is synthetic-only; both existing versions preserve the paired matrix.")

# The shared validator historically permits a one-task paired plan. The dedicated
# 4+6 runtime driver must reject it before admission and configuration loading.
sys.path.insert(0, str(out / "GEOM_CANDIDATES_GP5_P2_PHASE_SNAPSHOT_R3_R1_20261119_01"))
import driver

narrow = protocol.prepare_order_plan(tasks[:1], data_identity=identity, scope=protocol.ACCEPTANCE, native=True)
assert len(narrow["jobs"]) == 2
with TemporaryDirectory() as temp:
    root = Path(temp)
    narrow.update(status="FROZEN", assessment_limit=8, solver_limit=128,
                  call_ledger_path=str(root / "shared_call_ledger.json"))
    for name in ("K01_task.json", "K02_task.json", "monitor_snapshot.json"):
        (root / name).write_bytes((runtime / name).read_bytes())
    snap_path = root / "monitor_snapshot.json"
    snapshot = load(snap_path)
    plan_path = root / "acceptance_plan_FROZEN.json"
    driver.write(plan_path, narrow)
    request = {
        "plan_digest": digest(narrow), "source_identity": narrow["source_identity"],
        "environment_digest": narrow["environment_digest"], "publication_policy_digest": narrow["publication_policy_digest"],
        "shared_ledger_path": narrow["call_ledger_path"], "monitor_digest": digest(snapshot),
        "plan_reference": {"path": str(plan_path), "sha256": sha(plan_path.read_bytes())},
        "monitor_reference": {"path": str(snap_path), "sha256": sha(snap_path.read_bytes())},
    }
    driver.write(root / "startup_review_request.json", request)
    driver.write(root / "shared_call_ledger.json", {})
    mock_launch = root / "fixture.json"
    driver.write(mock_launch, {"authorization": None, "review": None, "monitor_digest": digest(snapshot)})
    with (
        patch.object(driver.p, "validate_admission") as admission,
        patch.object(driver.order, "load_order_config") as config,
        patch.object(driver.order, "run_order_job", side_effect=AssertionError("NO_DISPATCH")) as dispatch,
    ):
        try:
            driver.prepare(root, None, mock_launch)
        except AssertionError as exc:
            last = traceback.extract_tb(exc.__traceback__)[-1]
            assert last.name == "prepare" and "plan['jobs']" in last.line, last
        else:
            raise AssertionError("4+6 driver must reject a one-task paired plan")
        admission.assert_not_called()
        config.assert_not_called()
        dispatch.assert_not_called()
print("Dedicated 4+6 driver rejects a one-task paired plan before admission, configuration or dispatch.")

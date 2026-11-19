"""Verify the development archive and check plan contracts without dispatch."""
import hashlib
import json
from pathlib import Path
import subprocess

out = Path("semantic_pallet_planner/outputs")
dev = out / "GEOM_CANDIDATES_GP5_P2_EMS_OPERATIONAL_ENTRY_20261119_01"
runtime = out / "GEOM_CANDIDATES_GP5_P2_BOUNDED_REAL_MONITOR_RUNTIME_20261119_01"
source = Path("semantic_pallet_planner/src/semantic_pallet_planner")
head = "ff4c1c56c213c1470a88773c54cb233008ebf2ce"
baseline = "e9a2f424610b4072ce84dad2e7c973cd49cc888f"


def load(path):
    return json.loads(path.read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args])


rows = load(dev / "manifest.json")["files"]
assert len(rows) == len({row["path"] for row in rows}) == 8
for row in rows:
    path = Path(row["path"])
    blob = git("show", f"{head}:{path}")
    assert len(blob) == row["bytes"] and sha(blob) == row["sha256"], path
    if path.name != "README.md":
        assert blob == path.read_bytes()
source_receipt = load(dev / "source_identity_receipt.json")
production = {}
for path in source.rglob("*"):
    rel = path.relative_to(source)
    if path.is_file() and path.suffix in (".py", ".json") and not {"tests", "__pycache__"}.intersection(rel.parts):
        production[rel.as_posix()] = sha(path.read_bytes())
assert len(production) == 593 and production == source_receipt["files"]
protected = [path for path in runtime.iterdir() if path.is_file()]
assert len(protected) == 19
assert all(path.read_bytes() == git("show", f"{baseline}:{path}") for path in protected)
assert load(runtime / "shared_call_ledger.json")["calls"] == []
print("Verified 8 development files, 593 production files and 19 unchanged historical runtime files.")

from semantic_pallet_planner.jev_select import packaging_geometry_protocol as protocol
from semantic_pallet_planner.jev_select.contracts import JevSelectError, digest
from semantic_pallet_planner.jev_select.geometry_kernel_completion import required_coverage
from semantic_pallet_planner.jev_select.geometry_native_protocol import policy_digest

assert digest(production) == source_receipt["new_source_identity"]
assert policy_digest() == source_receipt["new_publication_policy_digest"]
adapted = []
for case in ("K01", "K02"):
    raw = (runtime / f"{case}_task.json").read_bytes()
    adapted.append(protocol.adapt_task(raw, origin="SYNTHETIC_FIXED", expected_sha256=sha(raw)))
identity = digest("GP5_P2_QA_PURE_PLAN_ONLY")
for backend in (None, "e2_original_v1"):
    plan = protocol.prepare_operational_order_plan(adapted, data_identity=identity, backend=backend)
    expected = backend or "ems_surface_hybrid_v1"
    assert {job["backend"] for job in plan["jobs"]} == {expected}
    assert plan["scope"] == protocol.DEVELOPMENT
    assert plan["assessment_limit"] == plan["solver_limit"] == 0
print("Operational constructor selects EMS by default and explicit E2 correctly.")

code = git("show", f"{baseline}:{source}/jev_select/packaging_geometry_protocol.py")
old = {"__name__": "qa_base_plan", "__package__": protocol.__package__}
exec(compile(code, "<prior plan implementation>", "exec"), old)
for native in (False, True):
    matrix = protocol.prepare_order_plan(adapted, data_identity=identity, scope=protocol.ACCEPTANCE, native=native)
    assert len(required_coverage(matrix)["primary"]) == 4
    old["validate_order_plan"](matrix)
    plan = protocol.prepare_operational_order_plan(
        adapted, data_identity=identity, scope=protocol.ACCEPTANCE, native=native,
    )
    assert matrix["version"] == plan["version"] and len(plan["jobs"]) == 2
    protocol.validate_order_plan(plan)
    for check, error in ((old["validate_order_plan"], "geometry_order_matrix"),
                         (required_coverage, "geometry_completion_matrix")):
        try:
            check(plan)
        except JevSelectError as exc:
            assert exc.code == error, exc
        else:
            raise AssertionError(f"Expected pure structural rejection: {error}")
print("Both existing plan versions now accept a two-job real-acceptance draft that the old plan validator and current completion coverage reject. No launch generated.")

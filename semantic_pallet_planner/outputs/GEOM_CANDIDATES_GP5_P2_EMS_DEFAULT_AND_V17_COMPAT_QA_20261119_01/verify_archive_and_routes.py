"""Verify the delivery and compare configuration entry points without dispatching."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

OUT = Path("semantic_pallet_planner/outputs")
DEV = OUT / "GEOM_CANDIDATES_GP5_P2_EMS_DEFAULT_AND_V17_COMPAT_20261119_01"
RUNTIME = OUT / "GEOM_CANDIDATES_GP5_P2_BOUNDED_REAL_MONITOR_RUNTIME_20261119_01"
SOURCE = Path("semantic_pallet_planner/src/semantic_pallet_planner")
HEAD = "3c5ccc2ddf89e648dabd1838cb50996f8438f12a"
BASE = "0a34f9b835250e7a0dad366432144ec8213ae088"


def git(*args):
    return subprocess.check_output(["git", *args])


def load(path):
    return json.loads(path.read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


rows = load(DEV / "manifest.json")["files"]
assert len(rows) == len({r["path"] for r in rows}) == 12
for row in rows:
    path = Path(row["path"])
    raw = git("show", f"{HEAD}:{path}")
    assert len(raw) == row["bytes"] and sha(raw) == row["sha256"], path
    if path.name != "README.md":
        assert raw == path.read_bytes(), path
expected = load(DEV / "source_identity_receipt.json")
files = {}
for path in SOURCE.rglob("*"):
    rel = path.relative_to(SOURCE)
    if path.is_file() and path.suffix in (".py", ".json") and not {"tests", "__pycache__"}.intersection(rel.parts):
        files[rel.as_posix()] = sha(path.read_bytes())
assert len(files) == 593 and files == expected["files"]
runtime_files = [path for path in RUNTIME.iterdir() if path.is_file()]
assert len(runtime_files) == 19
for path in runtime_files:
    assert path.read_bytes() == git("show", f"{BASE}:{path}")
assert load(RUNTIME / "shared_call_ledger.json")["calls"] == []
print("Verified 12 delivery items, 593 production files and 19 unchanged historical runtime files.")

from semantic_pallet_planner.jev_select.candidate_backends import load_geometry_config
from semantic_pallet_planner.jev_select.config import generator_config, generator_config_for
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.packaging_runtime import load_runtime_config
from semantic_pallet_planner.jev_select.geometry_native_protocol import policy_digest
from semantic_pallet_planner.jev_select import geometry_kernel_completion as completion

assert digest(files) == expected["new_source_identity"]
assert policy_digest() == expected["new_publication_policy_digest"]
identities = {key: digest("QA_" + key) for key in ("data_identity", "task_identity", "monitor_identity")}
assert load_geometry_config(**identities)["candidate_backend"] == "ems_surface_hybrid_v1"
assert load_geometry_config(backend="e2_original_v1", **identities)["candidate_backend"] == "e2_original_v1"
assert generator_config_for()["generator"]["backend"] == "ems_surface_hybrid_v1"
fresh_local = load_runtime_config(data_identity=identities["data_identity"], task_digest=identities["task_identity"])
assert fresh_local["candidate_backend"] == "e2_original_v1"
assert generator_config_for(fresh_local) == generator_config()
assert [row["backend"] for row in load(RUNTIME / "acceptance_plan_FROZEN.json")["jobs"]] == [
    "e2_original_v1", "ems_surface_hybrid_v1",
] * 2
print("Geometry loader defaults to EMS and explicit E2 passes. New call to existing packaging runtime loader still chooses E2; frozen matrix unchanged.")

sys.path.insert(0, "semantic_pallet_planner/tests/unit")
import test_geometry_external_review_identity_r1 as fixtures


class OrdinaryRecoveryProbe(fixtures.ReviewIdentity):
    def test_both_ordinary_versions_with_durable_root(self):
        for native in (False, True):
            with self.subTest(native=native):
                plan = self.plan(native=native)
                receipt, log, review = self.completion(plan)
                for row in receipt["recovery"]:
                    record = load(Path(row["after"]["path"]))
                    record["durable_root"] = str(Path(row["after"]["path"]).parent)
                    row["after"] = self.ref(record)
                review["recovery_digest"] = digest(receipt["recovery"])
                receipt["review"] = self.ref(review)
                completion.validate_completion(receipt, plan, log, lambda _: None)


suite = unittest.defaultTestLoader.loadTestsFromModule(fixtures)
suite.addTest(OrdinaryRecoveryProbe("test_both_ordinary_versions_with_durable_root"))
assert unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful()
print("Ordinary v16 and v17 completion with durable_root pass at coverage layer; durable validation callback stubbed.")

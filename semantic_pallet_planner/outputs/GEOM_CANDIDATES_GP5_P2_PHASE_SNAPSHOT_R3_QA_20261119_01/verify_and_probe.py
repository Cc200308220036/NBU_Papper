"""Verify the R3 archive and exercise metadata-only readiness checks."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

OUT = Path("semantic_pallet_planner/outputs")
DEV = OUT / "GEOM_CANDIDATES_GP5_P2_PHASE_SNAPSHOT_R3_20261119_01"
RUNTIME = OUT / "GEOM_CANDIDATES_GP5_P2_BOUNDED_REAL_MONITOR_RUNTIME_20261119_01"
SOURCE = Path("semantic_pallet_planner/src/semantic_pallet_planner")
BASE = "b5de450cc51aedff536b478aee30ffe92d07e58b"
HEAD = "27e22d68fcb729d68dcd2bd0e058dd2cd28f7a5c"


def load(path):
    return json.loads(path.read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args])


rows = load(DEV / "manifest.json")["files"]
assert len(rows) == len({row["path"] for row in rows})
for row in rows:
    path = Path(row["path"])
    raw = git("show", f"{HEAD}:{path}")
    assert len(raw) == row["bytes"] and sha(raw) == row["sha256"], path
    if path.name != "README.md":
        assert raw == path.read_bytes()
source_doc = load(DEV / "source_identity_receipt.json")
source_files = {}
for path in SOURCE.rglob("*"):
    rel = path.relative_to(SOURCE)
    if path.is_file() and path.suffix in (".py", ".json") and not {"tests", "__pycache__"}.intersection(rel.parts):
        source_files[rel.as_posix()] = sha(path.read_bytes())
assert len(source_files) == 593 and source_files == source_doc["files"]
runtime_files = [path for path in RUNTIME.iterdir() if path.is_file()]
assert len(runtime_files) == 19
for path in runtime_files:
    assert path.read_bytes() == git("show", f"{BASE}:{path}")
assert not load(RUNTIME / "shared_call_ledger.json")["calls"]
print(f"Verified {len(rows)} delivery entries, 593 production files, 19 unchanged historical runtime files.")

sys.path.insert(0, str(DEV))
sys.path.insert(0, "semantic_pallet_planner/tests/unit")
import driver
import test_driver
import test_geometry_external_review_identity_r1 as old_test
from semantic_pallet_planner.jev_select import geometry_kernel_completion as completion
from semantic_pallet_planner.jev_select.contracts import JevSelectError, digest
from semantic_pallet_planner.jev_select.geometry_native_protocol import policy_digest

assert digest(source_files) == source_doc["new_source_identity"]
assert policy_digest() == source_doc["new_publication_policy_digest"]


class LegacyCompletionProbe(old_test.ReviewIdentity):
    def test_durable_legacy_branch(self):
        plan = self.plan(native=False)
        receipt, log, review = self.completion(plan)
        completion.validate_completion(receipt, plan, log, lambda record: None)
        for row in receipt["recovery"]:
            rec = load(Path(row["after"]["path"]))
            rec["durable_root"] = str(Path(row["after"]["path"]).parent)
            row["after"] = self.ref(rec)
        review["recovery_digest"] = digest(receipt["recovery"])
        receipt["review"] = self.ref(review)
        old_source = git("show", f"{BASE}:{SOURCE}/jev_select/geometry_kernel_completion.py")
        old = {"__name__": "qa_baseline_completion", "__package__": completion.__package__}
        exec(compile(old_source, "<retained completion implementation>", "exec"), old)
        old["validate_completion"](receipt, plan, log, lambda record: None)
        with self.assertRaises(JevSelectError) as rejected:
            completion.validate_completion(receipt, plan, log, lambda record: None)
        self.assertEqual(rejected.exception.code, "geometry_completion_recovery_credential_missing")
        print("Legacy v16 coverage fixture with durable_root passes baseline and is rejected by R3 solely for a missing phase credential.")


class MonitorBindingProbe(test_driver.PhaseSnapshotParentEvidenceTests):
    def test_stale_fixed_digest_blocks_new_monitor(self):
        runtime, plan, snap, request, _, auth_ref, review_path, launch_path, _ = self.make_runtime_and_records()
        new_snapshot = copy.deepcopy(snap)
        new_snapshot["execution_environment"]["platform"] += " QA fixture"
        new_digest = digest(new_snapshot)
        self.assertNotEqual(new_digest, driver.EXPECTED_MONITOR_DIGEST)
        snap_path = runtime / "monitor_snapshot.json"
        driver.write(snap_path, new_snapshot)
        act_request = driver.read(runtime / "startup_review_request.json")
        act_request["monitor_digest"] = new_digest
        act_request["monitor_reference"]["sha256"] = sha(snap_path.read_bytes())
        driver.write(runtime / "startup_review_request.json", act_request)
        launch = driver.read(launch_path)
        launch["monitor_digest"] = new_digest
        driver.write(launch_path, launch)
        with (
            patch.object(driver.p, "validate_admission") as admission,
            patch.object(driver.order, "load_order_config") as cfg,
            self.forbid_dispatch() as run,
            self.assertRaises(AssertionError),
        ):
            driver.prepare(runtime, review_path, launch_path, authorization_reference=auth_ref)
        admission.assert_not_called()
        cfg.assert_not_called()
        run.assert_not_called()
        print("Changed monitor digest, matched in request, raw file and launch, is rejected before admission/config because of the historical constant.")


suite = unittest.TestSuite([
    LegacyCompletionProbe("test_durable_legacy_branch"),
    MonitorBindingProbe("test_stale_fixed_digest_blocks_new_monitor"),
])
assert unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful()

"""Check the sealed delivery and compare legacy coverage using pure fixtures."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

out = Path("semantic_pallet_planner/outputs")
dev = out / "GEOM_CANDIDATES_GP5_P2_PHASE_SNAPSHOT_R3_R1_20261119_01"
source = Path("semantic_pallet_planner/src/semantic_pallet_planner")
package = source / "jev_select"
head = "afa128ff835513593b19e6017d376bc8222ac9c7"


def git(*args):
    return subprocess.check_output(["git", *args])


def load(path):
    return json.loads(path.read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


rows = load(dev / "manifest.json")["files"]
assert len(rows) == len({row["path"] for row in rows}) == 16
for row in rows:
    path = Path(row["path"])
    raw = git("show", f"{head}:{path}")
    assert len(raw) == row["bytes"] and sha(raw) == row["sha256"], path
    if path.name != "README.md":
        assert raw == path.read_bytes(), path
source_map = {}
for path in source.rglob("*"):
    relative = path.relative_to(source)
    if path.is_file() and path.suffix in (".py", ".json") and not {"tests", "__pycache__"}.intersection(relative.parts):
        source_map[relative.as_posix()] = sha(path.read_bytes())
receipt = load(dev / "source_identity_receipt.json")
assert len(source_map) == 593 and source_map == receipt["files"]
hashes = load(dev / "command_receipts.json")["runtime_file_hashes"]
assert len(hashes) == 19 and all(sha(Path(file).read_bytes()) == expected for file, expected in hashes.items())
protected_routes = [str(package / name) for name in ("config.py", "candidate_backends.py", "candidates.py", "packaging_runtime.py")]
assert not git("diff", "--name-only", "cfcbf662", head, "--", *protected_routes)
assert '"candidate_backend": "e2_original_v1"' in (package / "candidates.py").read_text()
print("16 delivery files, 593 production files, 19 historical runtime files verified. Default E2 route unchanged.")

sys.path.insert(0, "semantic_pallet_planner/tests/unit")
import test_geometry_external_review_identity_r1 as fixtures
from semantic_pallet_planner.jev_select import geometry_kernel_completion as completion
from semantic_pallet_planner.jev_select.contracts import JevSelectError, digest
from semantic_pallet_planner.jev_select.geometry_native_protocol import policy_digest

assert digest(source_map) == receipt["new_source_identity"]
assert policy_digest() == receipt["new_publication_policy_digest"]


class OrdinaryCompletionProbe(fixtures.ReviewIdentity):
    def test_completion_dispatch_by_protocol(self):
        legacy_code = git("show", f"b5de450c:{package}/geometry_kernel_completion.py")
        baseline = {"__name__": "qa_prior_completion", "__package__": completion.__package__}
        exec(compile(legacy_code, "<prior completion implementation>", "exec"), baseline)
        for native in (False, True):
            with self.subTest(native=native):
                plan = self.plan(native=native)
                value, log, review = self.completion(plan)
                for row in value["recovery"]:
                    record = load(Path(row["after"]["path"]))
                    record["durable_root"] = str(Path(row["after"]["path"]).parent)
                    row["after"] = self.ref(record)
                review["recovery_digest"] = digest(value["recovery"])
                value["review"] = self.ref(review)
                baseline["validate_completion"](value, plan, log, lambda _: None)
                if native:
                    with self.assertRaises(JevSelectError) as rejected:
                        completion.validate_completion(value, plan, log, lambda _: None)
                    self.assertEqual(rejected.exception.code, "geometry_completion_recovery_credential_missing")
                else:
                    completion.validate_completion(value, plan, log, lambda _: None)
        print("Coverage fixtures with durable_root: ordinary v16 passes; ordinary v17 still requires a phase credential unlike the baseline. Durable callback stubbed.")


suite = unittest.TestSuite([OrdinaryCompletionProbe("test_completion_dispatch_by_protocol")])
assert unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful()

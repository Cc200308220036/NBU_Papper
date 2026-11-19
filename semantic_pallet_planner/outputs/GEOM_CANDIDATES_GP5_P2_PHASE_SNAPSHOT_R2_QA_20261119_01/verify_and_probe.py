"""Verify the archive and probe saved parent evidence with temporary metadata."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

out = Path("semantic_pallet_planner/outputs")
dev = out / "GEOM_CANDIDATES_GP5_P2_PHASE_SNAPSHOT_R2_20261119_01"
runtime = out / "GEOM_CANDIDATES_GP5_P2_BOUNDED_REAL_MONITOR_RUNTIME_20261119_01"
source = Path("semantic_pallet_planner/src/semantic_pallet_planner")
head = "dce1979fa2a0fe1f3e35ab3062f1e604f1bf740c"
baseline = "f761942f243c86b6128988f9ddc6e8f632aa70ff"


def load(path):
    return json.loads(path.read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args])


rows = load(dev / "manifest.json")["files"]
assert len(rows) == len({r["path"] for r in rows}) == 14
for row in rows:
    path = Path(row["path"])
    raw = git("show", f"{head}:{path}")
    assert len(raw) == row["bytes"] and sha(raw) == row["sha256"], path
    if path.name != "README.md":
        assert raw == path.read_bytes(), path
receipt = load(dev / "source_identity_receipt.json")
all_files = {}
for path in source.rglob("*"):
    rel = path.relative_to(source)
    if path.is_file() and path.suffix in (".py", ".json") and not {"tests", "__pycache__"}.intersection(rel.parts):
        all_files[rel.as_posix()] = sha(path.read_bytes())
assert len(all_files) == 593 and all_files == receipt["files"]
archive = load(dev / "command_receipts.json")["runtime_file_hashes"]
assert len(archive) == 19 and all(sha(Path(p).read_bytes()) == h for p, h in archive.items())
assert not git("diff", "--name-only", baseline, head, "--", str(runtime))
assert load(runtime / "shared_call_ledger.json")["calls"] == []
print("14 delivery manifest members, 593 production files and 19 historical runtime files verified.")

sys.path.insert(0, str(dev))
import driver
import test_driver
from semantic_pallet_planner.jev_select import geometry_order_accounting as accounting
from semantic_pallet_planner.jev_select.geometry_native_protocol import policy_digest

assert driver.digest(all_files) == receipt["new_source_identity"]
assert policy_digest() == receipt["new_publication_policy_digest"]


class ParentEvidenceProbe(test_driver.PhaseSnapshotAccountingTests):
    def test_consumer_checks_snapshot_but_not_parent(self):
        _, plan, snap, _, _, _, _, launch_path, adapted = self.make_runtime_and_records()
        with (
            patch.object(driver.order, "validate_monitor_snapshot"),
            patch.object(driver.order, "run_order_job", side_effect=AssertionError("NO_ORDER_DISPATCH")),
        ):
            cfg = driver.order.load_order_config(plan, "J00", monitor_snapshot=snap, admission=driver.read(launch_path))
        parent = self.root / "parent"
        snapshot = self.root / "snapshot"
        (parent / "blobs").mkdir(parents=True)
        raw_task = adapted[0]["raw"]
        geometry = b"{}"
        geometry_hash = sha(geometry)
        for raw in (raw_task, geometry):
            (parent / "blobs" / sha(raw)).write_bytes(raw)
        driver.write(parent / "config.json", cfg)
        driver.write(parent / "task_identity.json", cfg["order_task_identity"])
        cp = {"phase": "SELECTED", "job_id": "J00", "pending_event": {
            "geometry_ref": {"version": "geometry_blob_ref_v1", "sha256": geometry_hash},
        }}
        terminal = {"phase": "TERMINATED", "job_id": "J00", "reason": "ALL_ITEMS_PLACED"}
        import shutil
        with accounting.invocation(parent / "accounting.json", cfg, "J00", resume=None):
            accounting.tick(cfg, "selector_calls")
            driver.write(parent / "checkpoint.json", cp)
            shutil.copytree(parent, snapshot)
            accounting.completed(cfg, terminal)
        credential = accounting.seal_phase_snapshot_credential(
            parent, snapshot, cfg, "J00", "SELECTED", cp,
            parent_result={"summary": {"completed": True}, "checkpoint": terminal},
        )
        driver.write(parent / "accounting.json", {
            **driver.read(parent / "accounting.json"), "invocations": [],
        })
        assert driver.digest(driver.read(parent / "accounting.json")) != credential["parent_invocation"]["final_accounting_digest"]
        accounting.validate_phase_snapshot_credential(credential, snapshot, cfg, "J00", cp)
        print("A genuinely sealed fixture still validates after its original parent accounting changes. No order or recovery invoked.")


result = ParentEvidenceProbe("test_consumer_checks_snapshot_but_not_parent").run()
assert result.wasSuccessful(), (result.errors, result.failures)

"""Check frozen evidence and run narrow probes in temporary storage."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

out = Path("semantic_pallet_planner/outputs")
dev = out / "GEOM_CANDIDATES_GP5_P2_OFFLINE_DRIVER_R1_20261119_01"
head = "02655773a561fb68a458d2c815cab420dada0e77"
baseline = "0a2275611109b988f3fb9623344a2bce1d6eba6c"


def load(path):
    return json.loads(path.read_bytes())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args])


manifest = load(dev / "manifest.json")
assert len(manifest["files"]) == len({r["path"] for r in manifest["files"]}) == 9
for row in manifest["files"]:
    path = Path(row["path"])
    data = git("show", f"{head}:{path}")
    assert len(data) == row["bytes"] and sha(data) == row["sha256"]
    if path.name != "README.md":
        assert data == path.read_bytes()
receipts = load(dev / "command_receipts.json")
hashes = receipts["runtime_file_hashes"]
assert len(hashes) == 19 and all(sha(Path(path).read_bytes()) == expected for path, expected in hashes.items())
assert not git("diff", "--name-only", baseline, head, "--", "semantic_pallet_planner/src")
ledger = load(Path(load(dev / "handoff.json")["runtime_root"]) / "shared_call_ledger.json")
assert not ledger["calls"] and not any(ledger["counts"].values())
print("9 R1 manifest entries and 19 protected runtime files verified. Production code unchanged.")

sys.path.insert(0, str(dev))
import driver
import probe_dispatch_01
import test_driver

host = load(out / "GEOM_CANDIDATES_GP5_P2_HOST_PREFLIGHT_20261119_01" / "host_preflight.json")
environment = host["actual_order_environment"]
plan = load(driver.R / "acceptance_plan_FROZEN.json")
assert driver.digest(environment) == plan["environment_digest"]
with (
    patch.object(driver.p, "environment", return_value=environment),
    patch.object(driver.order, "run_order_job", side_effect=AssertionError("NO_DISPATCH")),
):
    result = probe_dispatch_01.run_probe()
assert result == load(dev / "probe_dispatch_01_results.json")
attempts = result["unmutated_in_run_resume_attempts"]
assert len(attempts) == 3
assert all(r["bytes_unchanged"] and r["error_code"] == "geometry_accounting_unknown_dispatch" for r in attempts)
print("Three phases rejected by the real accounting context using synthetic checkpoints; original probe JSON left untouched.")


class ExplicitAuthorizationProbe(test_driver.DriverCorrectionTests):
    def test_explicit_path_has_no_independent_digest(self):
        runtime, auth, review, launch, _ = self.make_runtime_and_records()
        original = auth.read_bytes()
        auth.write_bytes(original + b"\n")
        assert driver.read(auth) == json.loads(original)
        data = driver.read(launch)
        data["authorization"]["sha256"] = sha(auth.read_bytes())
        driver.write(launch, data)
        with (
            patch.object(driver.p, "validate_order_plan"),
            patch.object(driver.order, "load_order_config", return_value={}) as cfg,
            patch.object(driver.order, "run_order_job", side_effect=AssertionError("NO_DISPATCH")) as dispatch,
        ):
            driver.prepare(runtime, review, launch, authorization_path=auth)
            assert cfg.call_count == 4
            dispatch.assert_not_called()
        print("Explicit --authorization path accepted byte drift plus matching replacement launch hash; schemas and reference validation ran, host/config stubbed.")


probe = ExplicitAuthorizationProbe("test_explicit_path_has_no_independent_digest").run()
assert probe.wasSuccessful(), (probe.errors, probe.failures)

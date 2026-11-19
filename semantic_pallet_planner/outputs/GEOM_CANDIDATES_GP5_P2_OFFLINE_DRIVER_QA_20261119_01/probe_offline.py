"""Probe the delivered driver with temporary fixtures. No real order entry."""
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys

development = Path("semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_OFFLINE_DRIVER_20261119_01")
sys.path.insert(0, str(development))
import driver
import test_driver
from semantic_pallet_planner.jev_select.geometry_native_protocol import identity_fields, wire

plan = driver.read(driver.R / "acceptance_plan_FROZEN.json")
monitor = driver.read(driver.R / "monitor_snapshot.json")
request = driver.read(driver.R / "startup_review_request.json")

with TemporaryDirectory() as directory:
    root = Path(directory)
    common = {**identity_fields(plan), "scope": plan["scope"], "plan_digest": driver.digest(plan), "status": "APPROVED"}

    def fixture(name, value):
        path = root / name
        driver.write(path, value)
        return {"path": str(path), "sha256": driver.p.sha(path.read_bytes())}

    authorization = fixture("authorization.json", {**common, "version": wire(plan, "geometry_scope_authorization_v1")})
    review = fixture("review.json", {**common, "version": wire(plan, "geometry_scope_review_v1")})
    launch = fixture("launch.json", {**common,
        "version": wire(plan, "geometry_kernel_launch_v1"),
        "monitor_digest": driver.digest(monitor),
        "source_identity": plan["source_identity"], "environment_digest": plan["environment_digest"],
        "authorization": authorization, "review": review,
    })
    assert authorization["path"] != request["authorization_reference"]["path"]
    with ExitStack() as mocks:
        mocks.enter_context(patch.object(driver.p, "validate_order_plan"))
        configs = mocks.enter_context(patch.object(driver.order, "load_order_config", return_value={}))
        mocks.enter_context(patch.object(driver.order, "run_order_job", side_effect=AssertionError("DISPATCH_FORBIDDEN")))
        driver.prepare(driver.R, review["path"], launch["path"])
        assert configs.call_count == 4
    print("Alternate authorization reference accepted by prepare; environment/config checks stubbed, actual admission reference/schema checks used.")

    probe_plan = {**plan, "call_ledger_path": str(root / "ledger.json")}
    counts = {"assessment_entries": 1, "solver_calls": 0, "test_double_assessments": 0}
    driver.write(probe_plan["call_ledger_path"], {
        "version": "geometry_call_ledger_v1", "plan_digest": driver.digest(probe_plan), "evidence": "REAL_KERNEL",
        "limits": {"assessment_entries": 8, "solver_calls": 128}, "counts": counts,
        "calls": [{"kind": "assessment_entries", "state": "DONE", "job_id": "J00", "index": 0}],
    })
    assert driver.check_counts(probe_plan) == counts
    print("Nonempty within-cap prior ledger accepted by the same check used in initial preflight.")

class DispatchProbe(test_driver.DriverTests):
    def test_full_4_plus_6_and_phases(self):
        super().test_full_4_plus_6_and_phases()
        calls = Counter("recovery" if "/recovery/" in root else "primary" for _, _, root in self.calls)
        resumed = sum(phase != "FRESH" and "/recovery/" not in root for _, phase, root in self.calls)
        assert calls == {"primary": 10, "recovery": 6} and resumed == 6
        print("Mock order entry invocations: primary 10 (6 resumes), separate recovery 6, total 16.")


case = DispatchProbe("test_full_4_plus_6_and_phases")
result = case.run()
assert result.wasSuccessful(), (result.errors, result.failures)

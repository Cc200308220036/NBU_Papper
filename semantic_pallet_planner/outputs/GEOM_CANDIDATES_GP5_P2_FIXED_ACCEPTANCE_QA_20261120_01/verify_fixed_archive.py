"""Audit saved acceptance evidence without importing or executing planner code."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess

OUT = Path("semantic_pallet_planner/outputs")
RUN = OUT / "GEOM_CANDIDATES_GP5_P2_FIXED_ACCEPTANCE_20261120_01"
ROOT = OUT / "GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01"
QA = OUT / "GEOM_CANDIDATES_GP5_P2_APPROVED_LAUNCH_QA_20261120_01"
REVIEWED = "7eecc5519e8594577f9b255554b53a100f0b4940"
LAUNCH = "a287357b2ea5618198cb25c4eec720ad32f32ca9"
PHASES = ("SELECTED", "MONITORED", "COMMITTED")


def git(*args):
    return subprocess.check_output(["git", *args])


def read(path):
    return json.loads(path.read_bytes())


def raw(path):
    return sha256(path.read_bytes()).hexdigest()


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def reference(ref, path):
    assert ref == {"path": str(path), "sha256": raw(path)}, path


def check_checkpoint(cp):
    assert cp["record_digest"] == digest({key: val for key, val in cp.items() if key != "record_digest"})


def main():
    assert git("rev-parse", REVIEWED + "^").decode().strip() == LAUNCH
    tracked = set(git("diff", "--name-only", LAUNCH, REVIEWED).decode().splitlines())
    paths = {str(path) for path in RUN.rglob("*") if path.is_file()}
    assert tracked == paths
    assert not git("diff", REVIEWED, "--", str(RUN), str(ROOT), str(QA), "semantic_pallet_planner/src")
    blobs = [Path(path) for path in paths if Path(path).parent.name == "blobs"]
    for path in blobs:
        assert raw(path) == path.name, path

    plan, snap = (read(ROOT / name) for name in ("acceptance_plan_FROZEN.json", "monitor_snapshot.json"))
    plan_id = digest(plan)
    launch, receipt, ledger, empty = (read(path) for path in (QA / "launch.json", RUN / "driver_receipt.json", RUN / "shared_call_ledger_FINAL.json", ROOT / "shared_call_ledger.json"))
    assert launch["plan_digest"] == receipt["plan_digest"] == empty["plan_digest"] == ledger["plan_digest"] == plan_id
    assert launch["monitor_digest"] == receipt["monitor_digest"] == digest(snap)
    assert launch["source_identity"] == receipt["source_identity"] == plan["source_identity"]
    assert launch["environment_digest"] == plan["environment_digest"]
    assert launch["authorization"] == read(QA / "authorization_reference.json")
    for name in ("authorization", "review"):
        reference(launch[name], QA / (name + ".json"))
    assert receipt["status"] == "COMPLETE" and receipt["stop"] is None and receipt["joint_preflight"] == "4/4 PASS"
    assert (receipt["primary_dispatches"], receipt["recovery_dispatches"], receipt["model_calls"]) == (4, 6, 0)
    assert empty["calls"] == [] and not any(empty["counts"].values())
    assert receipt["initial_ledger_counts"] == empty["counts"]
    assert ledger["evidence"] == "REAL_KERNEL" and ledger["limits"] == empty["limits"] == {"assessment_entries": 8, "solver_calls": 128}
    assert ledger["counts"] == receipt["final_counts"] == {"assessment_entries": 8, "solver_calls": 68, "test_double_assessments": 0}
    coverage = read(ROOT / "required_coverage.json")
    assert len(coverage["primary"]) == 4 and len(coverage["recovery"]) == 6 and len(receipt["rows"]) == 10
    counts = empty["counts"].copy()
    cursor = 0
    for row in receipt["rows"]:
        assert row["status"] == "COMPLETE"
        delta = row["ledger_delta"]
        assert set(delta) == set(counts) and delta["test_double_assessments"] == 0
        if row["kind"] == "recovery":
            assert row["before"] == counts
        entries = ledger["calls"][cursor:cursor + sum(delta.values())]
        assert Counter(call["kind"] for call in entries) == Counter({key: val for key, val in delta.items() if val})
        for index, call in enumerate(entries, cursor):
            assert call["index"] == index and call["state"] == "DONE" and call["job_id"] == row["job_id"]
        cursor += len(entries)
        counts = {key: value + delta[key] for key, value in counts.items()}
        assert row.get("counts", row.get("after")) == counts
    assert counts == ledger["counts"] and cursor == len(ledger["calls"])

    def success(root, expected):
        job = expected["job_id"]
        record = read(root / "record.json")
        cp, cfg = record["checkpoint"], record["config"]
        check_checkpoint(cp)
        assert record["durable_root"] == str(root)
        assert cp == read(root / "checkpoint.json") and cfg == read(root / "config.json")
        assert cp["job_id"] == job and cp["phase"] == "TERMINATED" and cp["reason"] == "ALL_ITEMS_PLACED"
        assert cfg["candidate_backend"] == expected["backend"] and cfg["order_task_identity"]["task_id"] == expected["task_id"]
        assert cfg["plan_digest"] == plan_id and cfg["admission_digest"] == digest(launch)
        assert cfg["monitor_evidence"] == "REAL_KERNEL" and cfg["stability_monitor"] == snap
        assert cp["method"] == cfg["selector"] == "local_first_test_double"
        events = [event for event in cp["events"] if event.get("selection")]
        assert len(events) == len(expected["poses"]) == len(cp["state"]["placed_items"])
        assert cp["state"]["end_of_stream"] and not cp["state"]["pending_items"]
        for event, pose in zip(events, expected["poses"]):
            chosen = next(candidate for candidate in event["bundle"]["physical_candidates"]
                          if candidate["candidate_id"] == event["selection"]["selected_candidate_id"])
            assert chosen["pose"] == pose
            assert chosen["oriented_size_mm"] == ([100, 80, 60] if pose["yaw_deg"] == 0 else [80, 100, 60])
            assert event["event"] == "PLACE" and event["action"] == event["proposed_action"]
            monitor = event["monitor"]
            assert monitor["status"] == monitor["result"]["status"] == "STABLE"
            assert len(event["after"]["placed_items"]) == len(event["before"]["placed_items"]) + 1
        return record, events[-1]

    for index, expected in enumerate(coverage["primary"]):
        job = expected["job_id"]
        row = receipt["rows"][index]
        assert (row["kind"], row["job_id"]) == ("primary", job)
        assert row["ledger_delta"]["assessment_entries"] == len(expected["poses"])
        success(RUN / "primary/jobs" / job, expected)

    for row, expected in zip(receipt["rows"][4:], coverage["recovery"]):
        job, phase = expected["job_id"], expected["phase"]
        assert (row["kind"], row["job_id"], row["phase"]) == ("recovery", job, phase)
        assert phase in PHASES
        parent = RUN / "primary/jobs" / job
        saved = RUN / "saved" / job / phase
        root = RUN / "recovery" / job / phase / "jobs" / job
        file_hashes = read(RUN / f"{job}_{phase}_files.json")
        assert set(file_hashes) == {str(path.relative_to(saved)) for path in saved.rglob("*") if path.is_file()}
        for name, expected_hash in file_hashes.items():
            assert raw(saved / name) == expected_hash, name
        before = read(saved / "saved_checkpoint.json")
        check_checkpoint(before)
        cred = read(saved / "phase_snapshot_credential.json")
        assert cred == read(saved / "jobs" / job / "phase_snapshot_credential.json") == read(root / "phase_snapshot_credential.json")
        assert cred["credential_digest"] == row["credential_digest"] == digest({key: value for key, value in cred.items() if key != "credential_digest"})
        assert cred["checkpoint_digest"] == digest(before) and before["phase"] == cred["phase"] == phase
        assert before["job_id"] == cred["job_id"] == job and cred["plan_digest"] == plan_id
        assert cred["source_identity"] == plan["source_identity"]
        assert cred["config_digest"] == before["config_digest"]
        for blob, expected_hash in cred["durable_references"]["blob_hashes"].items():
            assert blob == expected_hash == raw(saved / "jobs" / job / "blobs" / blob)
        pinv = cred["parent_invocation"]
        for name in ("record", "accounting"):
            ref = pinv[f"final_{name}_ref"]
            reference(ref, parent / (name + ".json"))
            assert ref == row[f"parent_{name}_ref"]
        parent_record = read(parent / "record.json")
        assert pinv["final_checkpoint_digest"] == digest(parent_record["checkpoint"])
        assert pinv["final_accounting_digest"] == digest(read(parent / "accounting.json"))
        assert pinv["parent_durable_root"] == str(parent)
        after, event = success(root, next(item for item in coverage["primary"] if item["job_id"] == job))
        assert after["config"] == parent_record["config"]
        acct = read(root / "accounting.json")
        inv = acct["invocations"][-1]
        expected_delta = {"selector_calls": 0, "singleton_executions": 0, "monitor_entries": int(phase == "SELECTED"),
                          "monitor_reuses": int(phase == "MONITORED"), "commit_attempts": int(phase != "COMMITTED"),
                          "commit_successes": int(phase != "COMMITTED")}
        assert inv["delta"] == row["accounting"] == expected_delta
        assert inv["status"] == "RETURNED" and inv["resume_phase"] == phase
        assert inv["resume_checkpoint_digest"] == digest(before) and inv["result_checkpoint_digest"] == digest(after["checkpoint"])
        assert all(acct["cumulative"][key] == sum(item["delta"][key] for item in acct["invocations"]) for key in expected_delta)
        pending = before["pending_event"]
        assert event["selection"] == pending["selection"] and event["proposed_action"] == pending["proposed_action"]
        if phase != "SELECTED":
            assert event["monitor"]["result_digest"] == pending["monitor"]["result_digest"]
        assert row["ledger_delta"]["assessment_entries"] == int(phase == "SELECTED")
        assert (row["ledger_delta"]["solver_calls"] > 0) == (phase == "SELECTED")
    print(f"PASS: {len(paths)} archived paths; {len(blobs)} content-addressed blobs; 4 primary, 6 recovery; 8 assessments, 68 LP, 0 model calls.")


if __name__ == "__main__":
    main()

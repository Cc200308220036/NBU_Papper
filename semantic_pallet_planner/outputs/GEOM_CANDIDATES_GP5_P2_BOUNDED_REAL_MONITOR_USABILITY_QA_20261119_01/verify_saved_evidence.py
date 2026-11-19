"""Verify the reviewed snapshot using Git and the Python standard library only."""

import hashlib
import json
from pathlib import Path
import subprocess


OUTPUT = Path("semantic_pallet_planner/outputs")
PREFIX = "GEOM_CANDIDATES_GP5_P2_"
BASELINE = "1ff6d93c20a747ab348071e01ef682266b571f0c"
DEVELOPER = "2c4f8e87dca43452ea7f5d643f81d6d6b56ee372"
DEVELOPMENT = OUTPUT / f"{PREFIX}R1_EXTERNAL_REVIEW_BINDING_20261119_01"
PREPARATION = OUTPUT / f"{PREFIX}REAL_MONITOR_PREPARATION_20261119_01"
PARENT_QA = OUTPUT / f"{PREFIX}R1_EXTERNAL_REVIEW_BINDING_QA_20261119_01"


def git(*args):
    return subprocess.check_output(["git", *args])


def load(path):
    return json.loads(path.read_bytes())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode())


def verify_manifest(directory, revision):
    manifest = json.loads(git("show", f"{revision}:{directory}/delivery_manifest.json"))
    rows = manifest["files"]
    assert len({row["path"] for row in rows}) == len(rows)
    for row in rows:
        blob = git("show", f"{revision}:{row['path']}")
        assert sha(blob) == row["sha256"], row["path"]
        assert len(blob) == row.get("size_bytes", row.get("bytes")), row["path"]
    return len(rows)


assert git("merge-base", "--is-ancestor", BASELINE, "HEAD") == b""
assert git("diff", "--name-only", BASELINE, "HEAD", "--", "semantic_pallet_planner/src") == b""
parent_handoff = load(PARENT_QA / "handoff.json")
handoff = load(Path(parent_handoff["developer_handoff"]))
assert Path(parent_handoff["developer_handoff"]).parent == DEVELOPMENT
assert parent_handoff["reviewed_head"] == DEVELOPER
assert handoff["actual_runtime"] == "NOT_RUN"
assert handoff["effective_receipts_issued"] == 0

qa_members = verify_manifest(PARENT_QA, BASELINE)
developer_members = verify_manifest(DEVELOPMENT, DEVELOPER)
assert (qa_members, developer_members) == (7, 30)
root = Path("semantic_pallet_planner/src/semantic_pallet_planner")
files = {}
for path in root.rglob("*"):
    relative = path.relative_to(root)
    if path.is_file() and path.suffix in (".py", ".json") and not {"tests", "__pycache__"}.intersection(relative.parts):
        files[relative.as_posix()] = sha(path.read_bytes())
source = load(DEVELOPMENT / "source_manifest.json")
assert len(files) == 591 and files == source["files"]
source_identity = digest(files)
assert source_identity == source["source_identity"] == parent_handoff["source_identity"]

draft = load(DEVELOPMENT / "acceptance_plan_DRAFT.json")
draft_digest = digest(draft)
assert draft_digest == parent_handoff["draft_digest"]
assert draft["source_identity"] == source_identity
assert draft["status"] == "DRAFT" and draft["call_ledger_path"] is None
assert draft["scope"] == "KERNEL_ACCEPTANCE_SYNTHETIC_ONLY"
for case, task in zip(("K01", "K02"), draft["tasks"]):
    filename = f"{case}_task.json"
    raw = (DEVELOPMENT / filename).read_bytes()
    assert raw == (PREPARATION / filename).read_bytes()
    assert sha(raw) == task["raw_sha256"] and task["task_id"] == f"GP5_SYNTH_{case}"

coverage = load(DEVELOPMENT / "required_coverage.json")
matrix = load(DEVELOPMENT / "matrix_DRAFT.json")["rows"]
primary = load(DEVELOPMENT / "run_denominator_NOT_RUN.json")
recovery = load(DEVELOPMENT / "recovery_DRAFT.json")
assert primary["plan_digest"] == recovery["plan_digest"] == draft_digest
assert [row["job_id"] for row in draft["jobs"]] == ["J00", "J01", "J02", "J03"]
for plan_job, expected, row in zip(draft["jobs"], coverage["primary"], matrix):
    assert all(plan_job[k] == expected[k] for k in ("job_id", "task_id", "backend"))
    assert all(row[k] == v for k, v in expected.items())
    assert row["actual"] == "NOT_RUN" and row["monitor_evidence_required"] == "REAL_KERNEL"
assert len(matrix) == len(coverage["primary"]) == len(primary["rows"]) == 4
assert primary["rows"] == [{"job_id": job["job_id"], "status": "NOT_RUN", "metrics": None} for job in draft["jobs"]]
assert coverage["recovery"] == [
    {"job_id": job, "phase": phase}
    for job in ("J00", "J01")
    for phase in ("SELECTED", "MONITORED", "COMMITTED")
]
assert len(recovery["rows"]) == recovery["denominator"] == 6
for row, expected in zip(recovery["rows"], coverage["recovery"]):
    assert all(row[k] == v for k, v in expected.items()) and row["status"] == "NOT_RUN"
    assert row["generation_publication_selection"] == [0, 0, 0]
    phase = row["phase"]
    assert row["new_assessment"] == (phase == "SELECTED")
    assert row["new_commit"] == (phase != "COMMITTED")
    assert row["monitor_reuse"] == (phase == "MONITORED")

budget = load(DEVELOPMENT / "budget_PROPOSAL.json")
assert budget["status"] == "PROPOSAL_NOT_AUTHORIZATION"
assert budget["proposed_limits"] == {"assessment_entries": 8, "solver_calls": 128}
assert (draft["assessment_limit"], draft["solver_limit"], draft["model_calls_max"]) == (8, 128, 0)
accounting = load(DEVELOPMENT / "call_accounting.json")
assert set(accounting["actual"].values()) == {0}
assert all(accounting[key] == 0 for key in (
    "effective_authorizations_issued", "effective_launches_issued", "real_completion_receipts_issued",
))

print(f"Verified manifests at fixed Git revisions: QA {qa_members}, developer {developer_members}.")
print(f"Verified {len(files)} production files, source identity {source_identity}.")
print(f"Verified DRAFT {draft_digest} and byte-identical K01/K02 inputs.")
print("Primary 4/4 NOT_RUN, recovery 6/6 NOT_RUN. 8 assessments / 128 LP is a proposal.")
print("Saved P2 actual counters and effective authorization/launch/completion receipt counts are zero.")

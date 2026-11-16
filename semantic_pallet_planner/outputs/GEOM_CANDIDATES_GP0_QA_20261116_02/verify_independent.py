"""Independent read-only GP0 byte/provenance audit; no project imports or geometry."""
from __future__ import annotations

import ast
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
QA = Path(__file__).resolve().parent
DELIVERY = ROOT / "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP0_20261116_01"
PACKAGE = ROOT / "semantic_pallet_planner/src/semantic_pallet_planner"
ENTRY = "26b279fba19a406d714373979326e0e1aadfea02"
FIXED = ["P01_ffcfcc6e4af4", "P02_f17e03ef6116", "P03_81c78da5f3a7",
         "P04_53bacc63aa29", "P05_392be366b95d"]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def load(p):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            assert k not in result, (str(p), "duplicate key", k)
            result[k] = v
        return result

    def reject_constant(token):
        raise ValueError("nonfinite JSON number: " + token)

    return json.loads(p.read_text(encoding="utf-8"), parse_float=Decimal,
                      object_pairs_hook=unique, parse_constant=reject_constant)


def ptr(value, path):
    if not path:
        return value
    assert path.startswith("/")
    for raw in path[1:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def exact_signature(value):
    # Keep booleans distinct from 0/1; compare JSON numbers by exact decimal value.
    if type(value) is bool:
        return ("bool", value)
    if type(value) in (int, Decimal):
        return ("number", Decimal(value))
    if value is None:
        return ("null",)
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, list):
        return ("array", tuple(exact_signature(v) for v in value))
    if isinstance(value, dict):
        return ("object", tuple((k, exact_signature(v)) for k, v in sorted(value.items())))
    raise TypeError(type(value))


def leaf_paths(value, prefix=""):
    if isinstance(value, dict) and value:
        for k, v in value.items():
            yield from leaf_paths(v, prefix + "/" + k.replace("~", "~0").replace("/", "~1"))
    elif isinstance(value, list) and value:
        for i, v in enumerate(value):
            yield from leaf_paths(v, prefix + "/" + str(i))
    else:
        yield prefix


def ref(r):
    path = (ROOT / r["path"]).resolve()
    assert path.is_relative_to(ROOT) and path.is_file(), r["path"]
    assert sha(path) == r["sha256"], r["path"]
    return path


def main():
    assert len(sys.argv) == 3 and sys.argv[1] == "--output"
    output = (ROOT / sys.argv[2]).resolve()
    assert output.is_relative_to(QA) and not output.exists()
    checks = []
    seal = load(DELIVERY / "delivery_manifest.json")
    actual_files = {p.relative_to(DELIVERY).as_posix(): sha(p)
                    for p in DELIVERY.rglob("*") if p.is_file() and p.name != "delivery_manifest.json"}
    assert actual_files == seal["package_files"]
    checks.append({"check": "developer_package_exact_membership_and_sha256", "status": "PASS", "count": len(actual_files)})
    external = []
    head = git("rev-parse", "HEAD").decode().strip()
    for name, expected in seal["external_delivery_files"].items():
        current = sha(ROOT / name)
        blob = git("show", head + ":" + name)
        assert current == expected == hashlib.sha256(blob).hexdigest()
        external.append({"path": name, "expected_sha256": expected, "current_sha256": current,
                         "git_snapshot_commit": head, "git_snapshot_sha256": hashlib.sha256(blob).hexdigest()})
    checks.append({"check": "external_documents_before_qa_navigation_update", "status": "PASS", "count": len(external)})
    source = load(DELIVERY / "source_manifest.json")
    current = {p.relative_to(PACKAGE).as_posix(): sha(p) for p in sorted(PACKAGE.rglob("*"))
               if p.is_file() and p.suffix in (".py", ".json")
               and not {"tests", "__pycache__"}.intersection(p.relative_to(PACKAGE).parts)}
    assert current == source["files"]
    base = {}
    for row in git("ls-tree", "-rz", ENTRY, "--", PACKAGE.relative_to(ROOT).as_posix()).split(b"\0"):
        if not row:
            continue
        meta, path = row.split(b"\t", 1)
        path = Path(path.decode()).relative_to(PACKAGE.relative_to(ROOT))
        if path.suffix in (".py", ".json") and not {"tests", "__pycache__"}.intersection(path.parts):
            base[path.as_posix()] = meta.split()[2].decode()
    assert set(base) == set(current)
    assert git("rev-parse", "--show-object-format").strip() == b"sha1"
    for name, oid in base.items():
        data = (PACKAGE / name).read_bytes()
        assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == oid, name
    checks.append({"check": "production_universe_vs_delivered_sha256_and_entry_git_blobs", "status": "PASS", "count": len(current)})
    tree = ast.parse((PACKAGE / "jev_select/candidates.py").read_text())
    constants = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
                 if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                 and n.targets[0].id in {"STATE_KEYS", "ITEM_KEYS"}}
    manifest = load(DELIVERY / "input_manifest.json")
    assert manifest["fixed_point_ids"] == FIXED == [p["point_id"] for p in manifest["points"]]
    ref(manifest["navigation"])
    points = []
    fields = 0
    for p in manifest["points"]:
        episode = load(ref(p["primary_source"]))
        event = ptr(episode, p["primary_source"]["pointer"])
        snap = load(ref(p["snapshot"]))
        assert set(snap) == {"version", "point_id", "decision_id", "current_public_state", "public_observation", "input_scope"}
        assert snap["point_id"] == p["point_id"] and snap["decision_id"] == event["decision_id"]
        assert snap["input_scope"] == "CURRENT_PUBLIC_ONLY_NOT_EXECUTABLE_CHECKPOINT"
        for field, original in (("current_public_state", "before"), ("public_observation", "observation")):
            assert exact_signature(snap[field]) == exact_signature(event[original])
        b = snap["current_public_state"]
        assert set(b) == set(constants["STATE_KEYS"])
        for item in b["placed_items"] + [x["item"] for x in b["pending_items"]]:
            assert set(item) <= set(constants["ITEM_KEYS"])
        scope = {"current_public_state": b, "public_observation": snap["public_observation"]}
        paths = list(leaf_paths(scope))
        supplied = [r["snapshot_pointer"] for r in p["field_provenance"]]
        assert len(set(supplied)) == len(supplied) == len(paths) and set(supplied) == set(paths)
        for r in p["field_provenance"]:
            pointer = r["snapshot_pointer"]
            if pointer.startswith("/current_public_state/"):
                expected = p["primary_source"]["pointer"] + "/before" + pointer[len("/current_public_state"):]
            else:
                assert pointer.startswith("/public_observation/")
                expected = p["primary_source"]["pointer"] + "/observation" + pointer[len("/public_observation"):]
            assert r["source_pointer"] == expected
            assert exact_signature(ptr(snap, pointer)) == exact_signature(ptr(episode, expected))
        fields += len(supplied)
        for r in p["historical_refs"].values():
            ref(r)
        pool = load(ROOT / p["historical_refs"]["pool"]["path"])
        assert exact_signature(pool) == exact_signature(event["bundle"]["selectable_candidates"])
        points.append({"point_id": p["point_id"], "status": "PASS", "field_records": len(supplied),
                       "placed": len(b["placed_items"]), "buffer": len(b["pending_items"]),
                       "saved_pool_count": len(pool), "snapshot_sha256": p["snapshot"]["sha256"],
                       "source_sha256": p["primary_source"]["sha256"], "source_pointer": p["primary_source"]["pointer"]})
    assert fields == 1409
    checks.append({"check": "exact_typed_values_complete_unique_provenance_current_event_only", "status": "PASS", "states": len(points), "field_records": fields})
    old = ROOT / "semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP0_QA_20261116_01/delivery_manifest.json"
    previous = {"manifest_present": old.is_file(), "missing": [], "changed": [], "unchanged": []}
    if old.is_file():
        for r in load(old)["files"]:
            p = ROOT / r["path"]
            state = "missing" if not p.is_file() else "unchanged" if sha(p) == r["sha256"] else "changed"
            previous[state].append(r["path"])
    result = {"version": "geometry_gp0_independent_audit_v2", "date": "2026-11-16", "timezone": "Asia/Shanghai",
              "python": platform.python_version(), "head": head, "source_entry": ENTRY,
              "status": "PASS_STATIC_SAVED_FACTS_ONLY", "checks": checks, "point_checks": points,
              "external_document_snapshots": external,
              "delivery_manifest_sha256": sha(DELIVERY / "delivery_manifest.json"),
              "input_manifest_sha256": sha(DELIVERY / "input_manifest.json"),
              "previous_qa_archive_availability": previous,
              "boundary": "No project imports, candidate generation, geometry/physics/support recomputation, orders, model calls or stability solves. No historical files changed.",
              "limits": "Typed exact values and pointer scope, not physical validity or full-history authenticity; design semantics reviewed separately. External docs checked before QA navigation edits."}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "package_files": len(actual_files),
                      "production_files": len(current), "states": len(points), "field_records": fields,
                      "previous_qa_missing": len(previous["missing"]), "previous_qa_changed": len(previous["changed"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()

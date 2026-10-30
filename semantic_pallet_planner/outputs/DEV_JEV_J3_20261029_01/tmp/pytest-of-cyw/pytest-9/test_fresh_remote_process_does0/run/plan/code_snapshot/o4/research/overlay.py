"""Import independently authored expressions without changing reference rules.

Import does not certify that the new text means the reference policy. Annotation
status remains provided/unverified; no human identity/signature is fabricated.
"""
from pathlib import Path
import shutil

from ...config import WORKSPACE
from ..common import O4Error, digest, read, write
from ..observation import rebind
from ..remote_v2.experiment import file_hash, file_manifest, new_directory
from .data import verify


def import_expressions(corpus, overlay_path, output):
    corpus, overlay_path = Path(corpus).resolve(), Path(overlay_path).resolve()
    verify(corpus)
    overlay = read(overlay_path)
    if (set(overlay) != {"schema_version", "provenance", "split", "rows"}
            or overlay["schema_version"] != "o4_research_expression_overlay_v1"
            or overlay["split"] not in ("development", "calibration", "test")
            or not isinstance(overlay["provenance"], str) or not overlay["provenance"].strip()):
        raise ValueError("invalid expression overlay metadata")
    inputs = read(corpus / "private/input_snapshot.json")
    expected = {c["case_id"]: c for c in inputs["fixed"] if c["split"] == overlay["split"] and c["track"] == "expression"}
    rows = overlay["rows"]
    if not isinstance(rows, list) or any(not isinstance(r, dict) or set(r) != {"case_id", "text", "template_family"}
                                       or not isinstance(r["case_id"], str) for r in rows):
        raise ValueError("overlay rows require case_id, text and template_family only")
    if (len(rows) != len(expected) or {r["case_id"] for r in rows} != set(expected)
            or len({r["case_id"] for r in rows}) != len(rows)):
        raise ValueError("overlay must cover every expression case in the chosen split exactly once")
    other_families = {c["template_family"] for c in inputs["fixed"] if c["split"] != overlay["split"]}
    other_texts = {c["request"]["instruction_text"] for c in inputs["fixed"] if c["split"] != overlay["split"]}
    for row in rows:
        if (not isinstance(row["text"], str) or not row["text"].strip() or len(row["text"]) > 10000
                or not isinstance(row["template_family"], str) or not row["template_family"].strip()
                or row["template_family"] in other_families or row["text"] in other_texts):
            raise ValueError("invalid text or cross-split template/text overlap")
    root = new_directory(output)
    for child in corpus.iterdir():
        target = root / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copyfile(child, target)
    for row in rows:
        case = expected[row["case_id"]]
        case["request"]["instruction_text"] = row["text"]
        case["request"] = rebind(case["request"])
        case["template_family"] = row["template_family"]
        write(root / "public" / (case["case_id"] + ".json"), case["request"])
        for task in inputs["tasks"]:
            if task["split"] == overlay["split"] and task["track"] == "expression" and task["scenario_id"] == case["scenario_id"] and task["family"] == case["family"]:
                task["instruction_text"], task["template_family"] = row["text"], row["template_family"]
    write(root / "private/input_snapshot.json", inputs)
    write(root / "audit/expression_overlay.json", {"provided_overlay": overlay, "sha256": file_hash(overlay_path),
          "annotation_status": "PROVIDED_NOT_INDEPENDENTLY_VERIFIED", "human_signature": None,
          "reference_ast_changed": False, "new_independent_order_sources": 0})
    manifest = read(root / "manifest.json")
    manifest.update(input_digest=digest(inputs), template_origin="provided overlay; correctness and independence not certified by import",
                    human_review="NOT_CERTIFIED_BY_IMPORT", parent_corpus_manifest=digest(read(corpus / "manifest.json")))
    write(root / "manifest.json", manifest)
    write(root / "delivery_manifest.json", {"files": file_manifest(root)})
    return verify(root)

"""Re-score the existing 312 real responses without provider calls or rewrites."""
from pathlib import Path

import pytest

from semantic_pallet_planner.config import WORKSPACE
from semantic_pallet_planner.o4.common import read
from semantic_pallet_planner.o4.evaluation_v2_rescore import files, rescore


def test_actual_real_runs_rescore_only_six_equivalent_representations(tmp_path, monkeypatch):
    from urllib import request
    monkeypatch.setattr(request, "urlopen", lambda *a, **kw: pytest.fail("network during offline evaluation"))
    monkeypatch.setattr(request.OpenerDirector, "open", lambda *a, **kw: pytest.fail("network during offline evaluation"))
    roots = [WORKSPACE / "semantic_pallet_planner/outputs" / name for name in
             ("EXP_O4_D_V2_SMOKE_REAL_20261025_01", "EXP_O4_D_V2_FIXED_REAL_20261025_01")]
    before = [files(p) for p in roots]
    output = tmp_path / "comparison"
    report = rescore(roots, output)
    assert report["status"] == "PASS" and report["existing_response_records"] == report["existing_api_attempts"] == 312
    assert report["job_records"] == 624 and report["semantic_metric_changes"] == 6
    assert report["candidate_verdicts_unchanged"] and report["new_api_calls"] == 0
    rows = read(output / "rows.json")
    changed = [r for r in rows if r["semantic_metric_changed"]]
    assert {r["case_id"] for r in changed} == {"O4_ANCHOR_04_2", "O4_ANCHOR_05_2", "O4_ANCHOR_07_2", "O4_ANCHOR_10_2", "O4_ANCHOR_19_2", "O4_ANCHOR_20_2"}
    assert all(r["backend"] == "remote_text" and not r["legacy_metrics"]["semantic_equal"] and r["evaluation_v2"]["semantic_equal"] for r in changed)
    assert all(r["evaluation_v2"]["semantic_equal"] for r in rows)
    assert all(r["candidate_verdicts_unchanged"] for r in rows)
    assert before == [files(p) for p in roots]
    with pytest.raises(FileExistsError):
        rescore(roots, output)
    with pytest.raises(ValueError):
        rescore(roots, roots[0] / "new_metrics")
    with pytest.raises(ValueError):
        rescore([roots[0], roots[0]], tmp_path / "duplicate")

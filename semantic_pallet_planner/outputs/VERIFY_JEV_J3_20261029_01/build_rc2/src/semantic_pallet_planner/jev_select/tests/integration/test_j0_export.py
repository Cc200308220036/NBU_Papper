import json

import pytest

from semantic_pallet_planner.jev_select.cli import main
from semantic_pallet_planner.jev_select.contracts import JevSelectError
from semantic_pallet_planner.jev_select.experiment import export_j0, file_manifest, validate_j0


def test_constructed_export_is_offline_complete_and_read_only(tmp_path):
    root = tmp_path / "export"
    report = export_j0(root)
    assert report["status"] == "PASS" and report["model_api_calls"] == 0
    assert len(report["cases"]) == 4
    assert {r["route"] for r in report["cases"]} == {
        "CHOICE_REQUIRED", "STOP_NO_BUSINESS_CANDIDATE", "STOP_NO_PHYSICAL_CANDIDATE"}
    before = file_manifest(root)
    assert validate_j0(root)["verified_cases"] == 4
    assert file_manifest(root) == before
    request = json.loads((root / "cases/multi_choice/request.json").read_text())
    assert len(request["questions"]["next_action"]["criteria"]) == 48
    assert "policy_ast" not in json.dumps(request)
    with pytest.raises(JevSelectError, match="unsafe_output"):
        export_j0(root)


def test_resigned_wrong_request_or_report_is_rejected(tmp_path):
    root = tmp_path / "export"
    export_j0(root)
    request = root / "cases/multi_choice/request.json"
    data = json.loads(request.read_text())
    data["questions"]["next_action"]["criteria"]["C01"]["pose"]["x_mm"] += 1
    request.write_text(json.dumps(data))
    (root / "delivery_manifest.json").write_text(json.dumps(file_manifest(root)))
    with pytest.raises(JevSelectError, match="derived_request_changed"):
        validate_j0(root)


def test_cli_exposes_only_j0_commands(tmp_path, capsys):
    root = tmp_path / "cli"
    assert main(["export-j0", "--output", str(root)]) == 0
    assert main(["validate-j0", "--artifact", str(root)]) == 0
    assert '"model_api_calls": 0' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["run", "--remote"])

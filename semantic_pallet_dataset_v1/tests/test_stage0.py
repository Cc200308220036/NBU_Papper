#!/usr/bin/env python3
"""阶段0协议、Schema与物理复核的回归测试。"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pallet_protocol import build_request, resolve_response  # noqa: E402
from validate_geometry_independent import check_candidate  # noqa: E402


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class Stage0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = load(ROOT / "tasks/decision_cases/DC_00001.json")
        cls.cset = load(ROOT / "candidates/candidate_sets/CSET_00001.json")
        cls.scenario = load(ROOT / "tasks/scenarios/SCN_0001.json")
        cls.request = build_request(cls.scenario["container"], cls.case, cls.cset, "workspace.png", "candidates.png")

    def test_public_request_has_no_hidden_labels(self):
        text = json.dumps(self.request, ensure_ascii=False)
        for token in ("semantic_decision_required", "oracle_candidate_id", "ground_truth_rule", "source_order", '"split"'):
            self.assertNotIn(token, text)

    def test_valid_response_resolves_local_candidate(self):
        chosen = self.request["candidates"][0]
        response = {"schema_version": "pallet_vlm_response_v1", "request_id": self.request["request_id"], "state_hash": self.request["state_hash"], "candidate_id": chosen["candidate_id"]}
        self.assertEqual(resolve_response(self.request, response)["candidate_id"], chosen["candidate_id"])

    def test_stale_state_is_rejected(self):
        response = {"schema_version": "pallet_vlm_response_v1", "request_id": self.request["request_id"], "state_hash": "0" * 64, "candidate_id": self.request["candidates"][0]["candidate_id"]}
        with self.assertRaisesRegex(ValueError, "state_hash"):
            resolve_response(self.request, response)

    def test_unknown_candidate_is_rejected(self):
        response = {"schema_version": "pallet_vlm_response_v1", "request_id": self.request["request_id"], "state_hash": self.request["state_hash"], "candidate_id": "not_exists"}
        with self.assertRaisesRegex(ValueError, "未知"):
            resolve_response(self.request, response)

    def test_coordinate_override_is_rejected(self):
        response = {"schema_version": "pallet_vlm_response_v1", "request_id": self.request["request_id"], "state_hash": self.request["state_hash"], "candidate_id": self.request["candidates"][0]["candidate_id"], "x_mm": 0}
        with self.assertRaisesRegex(ValueError, "禁止字段"):
            resolve_response(self.request, response)

    def test_strict_candidate_schema_rejects_bad_yaw(self):
        broken = copy.deepcopy(self.cset)
        broken["candidates"][0]["pose"]["yaw_deg"] = 45
        validator = Draft202012Validator(load(ROOT / "schemas/candidate_set.schema.json"))
        self.assertTrue(list(validator.iter_errors(broken)))

    def test_independent_checker_rejects_out_of_bounds(self):
        broken = copy.deepcopy(self.cset["candidates"][0])
        broken["pose"]["x_mm"] = 5000
        self.assertIn("out_of_bounds", check_candidate(self.case, self.scenario, broken))


if __name__ == "__main__":
    unittest.main()

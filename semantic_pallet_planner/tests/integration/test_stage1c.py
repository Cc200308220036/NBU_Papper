import json

from semantic_pallet_planner.logging.artifacts import Experiment
from semantic_pallet_planner.runners.core import FixedCaseRunner
from semantic_pallet_planner.selectors.vlm import VLMSelector
from semantic_pallet_planner.vlm.cache import ResponseCache
from semantic_pallet_planner.vlm.client import FakeClient


def test_stage1c_fixed_runner_records_trace_and_replays(cfg, repo, monkeypatch):
    from semantic_pallet_planner.selectors.baselines import REGISTRY
    exp = Experiment(cfg, "stage1c_fake")
    def factory():
        return VLMSelector(mode="text", client=FakeClient("C01"), model="fake", seed=cfg["seed"],
                           artifact_root=exp.root / "selector_inputs",
                           cache=ResponseCache(exp.root / "cache"))
    monkeypatch.setitem(REGISTRY, "vlm_text", factory)
    FixedCaseRunner(repo, exp).run(["DC_00151"], ["geometry_greedy", "vlm_text"])
    exp.finish()
    assert len(exp.decisions) == 2
    row = next(r for r in exp.decisions if r["method"] == "vlm_text")
    assert row["vlm_response_valid"] and not row["fallback"] and row["leakage_hit_count"] == 0
    events = [json.loads(line) for line in (exp.root / "steps.jsonl").read_text().splitlines()]
    vlm = next(e for e in events if e["method"] == "vlm_text")
    assert vlm["model_trace"]["prompt_version"] == "stage1c_prompt_v1"


def test_stage1c_invalid_choice_is_preserved_and_falls_back(cfg, repo, monkeypatch):
    from semantic_pallet_planner.selectors.baselines import REGISTRY
    exp = Experiment(cfg, "stage1c_fallback")
    def factory():
        return VLMSelector(mode="text", client=FakeClient("C99"), model="fake", seed=cfg["seed"],
                           artifact_root=exp.root / "selector_inputs",
                           cache=ResponseCache(exp.root / "cache"))
    monkeypatch.setitem(REGISTRY, "vlm_text", factory)
    FixedCaseRunner(repo, exp).run(["DC_00151"], ["vlm_text"])
    exp.finish()
    row = exp.decisions[0]
    assert row["fallback"] and not row["vlm_response_valid"]
    event = json.loads((exp.root / "steps.jsonl").read_text())
    assert event["model_trace"]["error_category"] == "unknown_display_candidate"

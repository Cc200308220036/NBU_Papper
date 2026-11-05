import copy
import json
from pathlib import Path

import pytest

from semantic_pallet_planner.protocol import build_request, resolve_response
from semantic_pallet_planner.selectors.vlm import VLMSelector
from semantic_pallet_planner.vlm.cache import ResponseCache, cache_key
from semantic_pallet_planner.vlm.candidate_mapping import build_candidate_mapping
from semantic_pallet_planner.vlm.client import FakeClient, ModelRequest, ModelResult
from semantic_pallet_planner.vlm.leakage import scan_model_input
from semantic_pallet_planner.vlm.prompt_builder import OUTPUT_SCHEMA, build_prompt
from semantic_pallet_planner.vlm.response_parser import VLMResponseError, parse_choice


def fixed_request(repo, case_id="DC_00151"):
    case = repo.get_decision_case(case_id)
    scenario = repo.get_scenario(case["base_scenario_id"])
    cset = repo.get_candidate_set(case["candidate_set_id"])
    return build_request(scenario["container"], case, cset, "workspace.png", "candidates.png")


def valid_raw(request, display="C01", **extra):
    value = {
        "schema_version": "pallet_vlm_choice_v1", "request_id": request["request_id"],
        "state_hash": request["state_hash"], "display_candidate_id": display,
        "confidence": 0.7, "reason": "test",
    }
    value.update(extra)
    return json.dumps(value)


def test_candidate_mapping_is_deterministic_complete_and_private(repo):
    request = fixed_request(repo)
    first = build_candidate_mapping(request, 123)
    second = build_candidate_mapping(request, 123)
    assert first.mapping_sha256 == second.mapping_sha256
    assert first.model_request == second.model_request
    assert set(first.display_to_candidate.values()) == {c["candidate_id"] for c in request["candidates"]}
    assert all(c["display_label"] == f"C{i:02d}" for i, c in enumerate(first.model_request["candidates"], 1))
    serialized = json.dumps(first.model_request)
    assert not any(cid in serialized for cid in first.display_to_candidate.values())


def test_mapping_is_method_independent_and_seed_sensitive(repo):
    request = fixed_request(repo)
    assert build_candidate_mapping(request, 1).display_to_candidate == build_candidate_mapping(request, 1).display_to_candidate
    assert build_candidate_mapping(request, 1).display_to_candidate != build_candidate_mapping(request, 2).display_to_candidate


def test_prompt_modes_and_leakage(repo, tmp_path):
    request = fixed_request(repo)
    mapping = build_candidate_mapping(request, 7)
    text_prompt = build_prompt(mapping.model_request, "text")
    report = scan_model_input(mapping.model_request, text_prompt.user_text,
                              list(mapping.display_to_candidate.values()))
    assert report["passed"] and text_prompt.image_paths == ()
    image1 = tmp_path / "one.png"; image1.write_bytes(b"one")
    image2 = tmp_path / "two.png"; image2.write_bytes(b"two")
    visual_prompt = build_prompt(mapping.model_request, "visual", (str(image1), str(image2)))
    assert len(visual_prompt.image_paths) == 2
    with pytest.raises(ValueError):
        build_prompt(mapping.model_request, "visual", (str(image1),))


def test_response_parser_maps_display_id_and_rejects_injection(repo):
    request = fixed_request(repo)
    mapping = build_candidate_mapping(request, 4)
    response, parsed = parse_choice(valid_raw(request), request, mapping.display_to_candidate)
    assert response["candidate_id"] == mapping.display_to_candidate["C01"]
    assert resolve_response(request, response)["candidate_id"] == response["candidate_id"]
    with pytest.raises(VLMResponseError, match="Additional properties") as caught:
        parse_choice(valid_raw(request, x_mm=1), request, mapping.display_to_candidate)
    assert caught.value.category == "coordinate_injection"
    with pytest.raises(VLMResponseError) as caught:
        parse_choice(valid_raw(request, display="C99"), request, mapping.display_to_candidate)
    assert caught.value.category == "unknown_display_candidate"


def test_response_parser_accepts_only_exact_outer_json_fence(repo):
    request = fixed_request(repo)
    mapping = build_candidate_mapping(request, 4)
    raw = "```json\n" + valid_raw(request) + "\n```"
    response, _ = parse_choice(raw, request, mapping.display_to_candidate)
    assert response["candidate_id"] == mapping.display_to_candidate["C01"]
    with pytest.raises(VLMResponseError) as caught:
        parse_choice("prefix\n" + raw, request, mapping.display_to_candidate)
    assert caught.value.category == "invalid_json"


def test_cache_key_tracks_images_and_cache_replays(tmp_path):
    image = tmp_path / "image.png"; image.write_bytes(b"image-a")
    request = ModelRequest("model", "system", "user", (str(image),), response_schema=OUTPUT_SCHEMA)
    key1 = cache_key("glm", request, "v1")
    image.write_bytes(b"image-b")
    key2 = cache_key("glm", request, "v1")
    assert key1 != key2
    cache = ResponseCache(tmp_path / "cache")
    calls = []
    result = cache.complete(key2, lambda: calls.append(1) or ModelResult("{}", input_tokens=1))
    replay = cache.complete(key2, lambda: calls.append(2) or ModelResult("bad"))
    assert len(calls) == 1 and not result.cache_hit and replay.cache_hit and replay.raw_text == "{}"


def test_text_selector_end_to_end_and_artifacts(repo, tmp_path):
    request = fixed_request(repo)
    selector = VLMSelector(mode="text", client=FakeClient("C01"), model="fake", seed=9,
                           artifact_root=tmp_path / "inputs", cache=ResponseCache(tmp_path / "cache"))
    response = selector.select(request, rng=None, memories=None)
    assert resolve_response(request, response)
    assert selector.last_trace["vlm_response_valid"]
    directory = tmp_path / "inputs/vlm_text" / request["request_id"]
    assert (directory / "prompt.json").exists() and (directory / "leakage_report.json").exists()
    assert json.loads((directory / "leakage_report.json").read_text())["passed"]


def test_visual_selector_renders_private_mapping(repo, tmp_path):
    request = fixed_request(repo)
    selector = VLMSelector(mode="visual", client=FakeClient("C01"), model="fake", seed=9,
                           artifact_root=tmp_path / "inputs", cache=ResponseCache(tmp_path / "cache"))
    response = selector.select(request, rng=None)
    assert resolve_response(request, response)
    directory = tmp_path / "inputs/vlm_visual" / request["request_id"]
    assert (directory / "workspace.png").exists() and (directory / "candidates_montage.png").exists()
    prompt = json.loads((directory / "prompt.json").read_text())
    assert prompt["image_paths"] and not any(c["candidate_id"] in prompt["user_text"] for c in request["candidates"])


def test_selector_repairs_once(repo, tmp_path):
    request = fixed_request(repo)
    client = FakeClient(responses=["not json", valid_raw(request)])
    selector = VLMSelector(mode="text", client=client, model="fake", seed=9,
                           artifact_root=tmp_path / "inputs", cache=ResponseCache(tmp_path / "cache"))
    assert resolve_response(request, selector.select(request, rng=None))
    assert client.calls == 2 and selector.last_trace["repair_count"] == 1


def test_missing_api_key_is_not_serialized(monkeypatch):
    from semantic_pallet_planner.vlm.glm_client import GLMClient, GLMClientError
    monkeypatch.delenv("UNSET_GLM_TEST_KEY", raising=False)
    client = GLMClient(api_key_env="UNSET_GLM_TEST_KEY")
    with pytest.raises(GLMClientError) as caught:
        client.complete(ModelRequest("glm-4.6v-flash", "s", "u"))
    assert caught.value.category == "missing_api_key" and "Bearer" not in str(caught.value)


def test_glm_adapter_builds_multimodal_request(monkeypatch, tmp_path):
    from semantic_pallet_planner.vlm.glm_client import GLMClient
    image = tmp_path / "view.png"; image.write_bytes(b"png-test")
    captured = {}
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps({"id": "req-1", "choices": [{"finish_reason": "stop",
                "message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2}}).encode()
    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data); captured["timeout"] = timeout
        captured["authorization"] = request.headers["Authorization"]
        return Reply()
    monkeypatch.setenv("GLM_TEST_KEY", "secret-test-only")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = GLMClient(api_key_env="GLM_TEST_KEY")
    result = client.complete(ModelRequest("glm-4.6v-flash", "system", "user", (str(image),)))
    content = captured["body"]["messages"][1]["content"]
    assert result.raw_text == "{}" and captured["authorization"] == "Bearer secret-test-only"
    assert [part["type"] for part in content] == ["text", "image_url"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert captured["body"]["thinking"] == {"type": "disabled"}
    assert captured["body"]["do_sample"] is False and "response_format" not in captured["body"]


def test_deepseek_flash_adapter_uses_json_mode_and_images(monkeypatch, tmp_path):
    from semantic_pallet_planner.vlm.deepseek_client import DeepSeekClient
    image = tmp_path / "view.png"; image.write_bytes(b"png-test")
    captured = {}
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps({"id": "ds-1", "choices": [{"finish_reason": "stop",
                "message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3}}).encode()
    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["authorization"] = request.headers["Authorization"]
        return Reply()
    monkeypatch.setenv("DEEPSEEK_TEST_KEY", "secret-test-only")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DeepSeekClient(api_key_env="DEEPSEEK_TEST_KEY")
    result = client.complete(ModelRequest("deepseek-flash", "system", "user", (str(image),)))
    content = captured["body"]["messages"][1]["content"]
    assert result.raw_text == "{}" and captured["authorization"] == "Bearer secret-test-only"
    assert [part["type"] for part in content] == ["text", "image_url"]
    assert content[1]["image_url"]["detail"] == "original"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["thinking"] == {"type": "disabled"}


def test_deepseek_v4_pro_rejects_visual_input(monkeypatch, tmp_path):
    from semantic_pallet_planner.vlm.deepseek_client import DeepSeekClient,DeepSeekClientError
    image = tmp_path / "view.png"; image.write_bytes(b"png-test")
    monkeypatch.setenv("DEEPSEEK_TEST_KEY", "secret-test-only")
    client = DeepSeekClient(api_key_env="DEEPSEEK_TEST_KEY")
    with pytest.raises(DeepSeekClientError) as caught:
        client.complete(ModelRequest("deepseek-v4-pro", "system", "user", (str(image),)))
    assert caught.value.category == "model_capability_error"

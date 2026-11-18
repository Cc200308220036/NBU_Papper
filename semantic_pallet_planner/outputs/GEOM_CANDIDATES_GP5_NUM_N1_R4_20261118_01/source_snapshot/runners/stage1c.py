"""为现有固定案例运行器装配阶段1C选择器。"""
from __future__ import annotations

from ..selectors.baselines import register
from ..selectors.vlm import VLMSelector
from ..vlm.cache import ResponseCache
from ..vlm.glm_client import GLMClient
from ..vlm.deepseek_client import DeepSeekClient


def register_stage1c_selectors(cfg, experiment, client=None):
    settings = cfg["vlm"]
    if client is None:
        client_class = {"glm": GLMClient, "deepseek": DeepSeekClient}.get(settings["provider"])
        if client_class is None:
            raise ValueError(f"unsupported VLM provider: {settings['provider']}")
        client = client_class(
            api_key_env=settings["api_key_env"], base_url=settings["base_url"],
            thinking=settings.get("thinking", "disabled"),
            input_cost_per_million=settings.get("input_cost_per_million"),
            output_cost_per_million=settings.get("output_cost_per_million"),
        )
    cache = ResponseCache(experiment.root / "cache", settings.get("cache_mode", "read_write"))
    common = dict(client=client, model=settings["model"], seed=cfg["seed"],
                  artifact_root=experiment.root / "selector_inputs", cache=cache,
                  provider=settings["provider"], temperature=settings.get("temperature", 0.0),
                  max_output_tokens=settings.get("max_output_tokens", 512),
                  timeout_s=settings.get("timeout_s", 60),
                  max_format_repairs=settings.get("max_format_repairs", 1))
    register("vlm_text", lambda: VLMSelector(mode="text", **common))
    register("vlm_visual", lambda: VLMSelector(mode="visual", **common))
    return client

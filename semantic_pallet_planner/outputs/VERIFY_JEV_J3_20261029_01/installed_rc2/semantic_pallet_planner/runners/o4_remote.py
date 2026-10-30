"""O4-D frozen plans, explicit remote calls, offline checks and read-only replay."""
from __future__ import annotations

import argparse
from dataclasses import fields
import json
import os
from pathlib import Path

import yaml

from ..config import WORKSPACE
from ..o4.common import O4Error
from ..o4.remote.experiment import DEFAULT_C, PROFILES, execute, prepare, replay
from ..o4.remote.testing import ProtocolServiceDouble
from ..o4.remote.transport import ChatTransport, ModelConfig


DEFAULT_CONFIG = WORKSPACE / "semantic_pallet_planner/configs/o4_d_deepseek_flash.yaml"


def load_model_config(path) -> ModelConfig:
    values = yaml.safe_load(Path(path).read_text())
    allowed = {field.name for field in fields(ModelConfig)}
    if not isinstance(values, dict) or set(values) - allowed:
        raise ValueError("unknown model configuration fields")
    config = ModelConfig(**values)
    config.validate()
    return config


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("prepare", help="freeze inputs/model/prompts before any API calls")
    plan.add_argument("--output", required=True)
    plan.add_argument("--config", default=str(DEFAULT_CONFIG))
    plan.add_argument("--profile", choices=PROFILES, default="compile-smoke")
    plan.add_argument("--baseline", default=str(DEFAULT_C))
    plan.add_argument("--task-limit", type=int, default=2, help="orders-smoke only")
    run = commands.add_parser("run", help="execute a frozen plan in a NEW directory")
    run.add_argument("--plan", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--api-budget", type=int, required=True, help="hard cap including repairs and failed HTTP attempts")
    modes = run.add_mutually_exclusive_group(required=True)
    modes.add_argument("--remote", action="store_true", help="send real requests; reads key from frozen environment variable name")
    modes.add_argument("--offline", action="store_true", help="labelled service double, no real model metrics")
    replay_parser = commands.add_parser("replay", help="read-only; no keys or network required")
    replay_parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args.output, load_model_config(args.config), profile=args.profile,
                             baseline=args.baseline, task_limit=args.task_limit)
            result = {key: value for key, value in result.items() if key != "jobs"}
        elif args.command == "replay":
            result = replay(args.output)
        else:
            config = ModelConfig(**json.loads((Path(args.plan) / "config.snapshot.json").read_text()))
            if args.remote:
                if not os.environ.get(config.api_key_env):
                    parser.error(f"set {config.api_key_env} in the environment first")
                transport = None
            else:
                # The double still traverses credential/header construction;
                # this local temporary sentinel is never written into artifacts.
                previous = os.environ.get(config.api_key_env)
                os.environ[config.api_key_env] = "O4_OFFLINE_SENTINEL"
                transport = ChatTransport(config, opener=ProtocolServiceDouble(), test_double=True)
            try:
                result = execute(args.plan, args.output, budget=args.api_budget,
                                 remote=args.remote, transport=transport)
            finally:
                if not args.remote:
                    if previous is None:
                        os.environ.pop(config.api_key_env, None)
                    else:
                        os.environ[config.api_key_env] = previous
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status", "PASS") == "PASS" else 2
    except (O4Error, ValueError, OSError, KeyError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

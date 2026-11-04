"""O4-D source-separated fixed/online studies; remote execution is explicit."""
import argparse
import json
import os
from pathlib import Path

from ..o4.common import O4Error, read
from ..o4.remote.transport import ChatTransport, ModelConfig
from ..o4.research.data import DEFAULT_BED, DEFAULT_CONFIG, build, verify
from ..o4.research.episode import PLANNERS
from ..o4.research.experiment import execute, prepare, replay
from ..o4.research.testing import StudyServiceDouble
from ..o4.research.overlay import import_expressions
from .o4_remote_v2 import DEFAULT_CONFIG as MODEL_CONFIG, load_model_config


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    corpus = commands.add_parser("build", help="audit historical sources and seal new study inputs, no network")
    corpus.add_argument("--output", required=True)
    corpus.add_argument("--design", default=str(DEFAULT_CONFIG))
    corpus.add_argument("--bed", default=str(DEFAULT_BED))
    check = commands.add_parser("verify", help="read-only corpus integrity/source checks")
    check.add_argument("--corpus", required=True)
    overlay = commands.add_parser("import-expressions", help="seal external expression overlay in a NEW corpus; does not certify annotations")
    overlay.add_argument("--corpus", required=True)
    overlay.add_argument("--overlay", required=True)
    overlay.add_argument("--output", required=True)
    plan = commands.add_parser("prepare", help="freeze mode, split, model, repetitions and full job denominator")
    plan.add_argument("--corpus", required=True)
    plan.add_argument("--output", required=True)
    plan.add_argument("--mode", choices=("fixed", "online"), required=True)
    plan.add_argument("--split", choices=("development", "calibration", "test"), required=True)
    plan.add_argument("--planner", choices=PLANNERS)
    plan.add_argument("--config", default=str(MODEL_CONFIG))
    run = commands.add_parser("run", help="run a sealed plan in a new directory; no paid-request resume")
    run.add_argument("--plan", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--api-budget", type=int, required=True)
    modes = run.add_mutually_exclusive_group(required=True)
    modes.add_argument("--remote", action="store_true")
    modes.add_argument("--offline", action="store_true")
    replay_parser = commands.add_parser("replay", help="no network, no key, no original file changes")
    replay_parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build(args.output, args.design, args.bed)
        elif args.command == "verify":
            result = verify(args.corpus)
        elif args.command == "import-expressions":
            result = import_expressions(args.corpus, args.overlay, args.output)
        elif args.command == "prepare":
            result = prepare(args.corpus, args.output, load_model_config(args.config), mode=args.mode, split=args.split, planner=args.planner)
        elif args.command == "replay":
            result = replay(args.output)
        else:
            config = ModelConfig(**read(Path(args.plan) / "config.snapshot.json"))
            if args.remote:
                result = execute(args.plan, args.output, budget=args.api_budget, remote=True)
            else:
                previous = os.environ.get(config.api_key_env)
                os.environ[config.api_key_env] = "O4_STUDY_OFFLINE_SENTINEL"
                try:
                    transport = ChatTransport(config, opener=StudyServiceDouble(), test_double=True)
                    result = execute(args.plan, args.output, budget=args.api_budget, transport=transport)
                finally:
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

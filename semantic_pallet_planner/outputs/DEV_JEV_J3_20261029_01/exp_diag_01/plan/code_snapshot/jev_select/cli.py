"""J0 export, J1 offline closure, J2 native smoke and read-only replay."""
from __future__ import annotations

import argparse
import json


def budget_value(value):
    if value == "unlimited": return value
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use a positive integer or unlimited") from exc
    if not 1 <= parsed <= 10000:
        raise argparse.ArgumentTypeError("use 1..10000 or unlimited")
    return parsed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export-j0", help="export public Choice requests; zero API calls")
    export.add_argument("--output", required=True); export.add_argument("--config")
    check = commands.add_parser("validate-j0", help="read-only J0 reconstruction")
    check.add_argument("--artifact", required=True)
    prepare = commands.add_parser("prepare", help="freeze public tasks, source code, mode and attempt policy")
    prepare.add_argument("--profile", choices=("constructed-smoke", "jev-smoke", "orders-smoke", "orders", "constructed-eval", "dataset-dev", "dataset-validation", "dataset-orders"), default="constructed-smoke")
    prepare.add_argument("--mode", choices=("offline", "remote"), default="offline")
    prepare.add_argument("--api-budget", type=budget_value)
    prepare.add_argument("--config"); prepare.add_argument("--input-snapshot"); prepare.add_argument("--output", required=True)
    prepare.add_argument("--methods", nargs="+", choices=("jev_choice", "shared_geometry", "shared_constrained_first", "shared_business_lexicographic"))
    prepare.add_argument("--offline-scenario", default="normal")
    prepare.add_argument("--dataset-root"); prepare.add_argument("--business-spec"); prepare.add_argument("--split-manifest")
    prepare.add_argument("--partitions",nargs="+",choices=("train","validation","test_id","test_geometry_ood","test_semantic_ood"))
    prepare.add_argument("--source-limit",type=int)
    prepare.add_argument("--global-attempts", type=int, default=128); prepare.add_argument("--per-job-attempts", type=int, default=32)
    validate = commands.add_parser("validate-plan", help="validate frozen code, input and registry")
    validate.add_argument("--plan", required=True)
    pre = commands.add_parser("preflight", help="inspect first request and credential readiness; zero API calls")
    pre.add_argument("--plan", required=True); pre.add_argument("--api-key-file")
    run = commands.add_parser("run", help="run an explicitly matching offline/remote frozen plan")
    run.add_argument("--plan", required=True); run.add_argument("--output", required=True)
    mode = run.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true"); mode.add_argument("--remote", action="store_true")
    run.add_argument("--api-budget", type=budget_value); run.add_argument("--api-key-file"); run.add_argument("--resume", action="store_true")
    replay = commands.add_parser("replay", help="read-only replay using saved native answers; no API/key")
    replay.add_argument("--experiment", required=True)
    args = parser.parse_args(argv)
    from .config import load_config,load_v2_config,is_v2
    from .experiment import export_j0, validate_j0, prepare_plan, validate_plan, run_experiment, preflight, METHODS
    try:
        if args.command == "export-j0":
            result = export_j0(args.output, load_config(args.config))
        elif args.command == "validate-j0":
            result = validate_j0(args.artifact)
        elif args.command == "prepare":
            j3 = args.profile in ('constructed-eval','dataset-dev','dataset-validation','dataset-orders')
            config = load_config(args.config) if args.config else load_v2_config() if j3 else load_config()
            from .batch import METHODS_V2
            methods = args.methods or (METHODS_V2 if is_v2(config) else ["jev_choice"] if args.mode == "remote" else METHODS)
            result = prepare_plan(args.output, profile=args.profile, config=config, input_snapshot=args.input_snapshot,
                                  methods=methods, offline_scenario=args.offline_scenario,
                                  global_attempts=args.global_attempts, per_job_attempts=args.per_job_attempts,
                                  mode=args.mode, api_budget=args.api_budget, dataset_root=args.dataset_root,
                                  spec_config=args.business_spec,split_manifest=args.split_manifest,
                                  partitions=args.partitions,source_limit=args.source_limit)
        elif args.command == "validate-plan":
            result = validate_plan(args.plan)
        elif args.command == "preflight":
            result = preflight(args.plan, api_key_file=args.api_key_file)
        elif args.command == "run":
            result = run_experiment(args.plan, args.output, offline=args.offline, remote=args.remote,
                                    api_budget=args.api_budget, api_key_file=args.api_key_file, resume=args.resume)
        else:
            from .replay import replay_experiment
            result = replay_experiment(args.experiment)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1

"""Versioned Jev candidate selection: J0/J1/J2 compatibility and J3 frozen order batches."""
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
    ready = commands.add_parser('audit-j4', help='read-only A0 data/dependency audit; zero network')
    ready.add_argument('--repo', required=True); ready.add_argument('--output', required=True)
    ready.add_argument('--raw-path'); ready.add_argument('--reme-path')
    ts = commands.add_parser('prepare-training-sources',help='freeze two new full-order train source groups; zero model calls')
    ts.add_argument('--repo',required=True); ts.add_argument('--readiness',required=True); ts.add_argument('--output',required=True)
    dv2 = commands.add_parser('build-dataset-v2',help='build fixed exposed-train v2 data only; zero episodes/network/credentials')
    dv2.add_argument('--repo',required=True); dv2.add_argument('--output',required=True)
    vv2 = commands.add_parser('validate-dataset-v2',help='authenticate and load v2 delivery; no simulation')
    vv2.add_argument('--dataset',required=True)
    pack = commands.add_parser('build-packaging-dataset', help='build frozen packaging/load data; static only')
    pack.add_argument('--repo', required=True); pack.add_argument('--output', required=True)
    packcheck = commands.add_parser('validate-packaging-dataset', help='independently load and validate packaging/load delivery')
    packcheck.add_argument('--dataset', required=True)
    prs = commands.add_parser('smoke-packaging-runtime', help='two bounded source prefixes using explicit local test substitute only')
    prs.add_argument('--dataset', required=True); prs.add_argument('--output', required=True)
    prv = commands.add_parser('validate-packaging-runtime', help='validate saved bindings and physical records without replay')
    prv.add_argument('--artifact', required=True)
    inspect = commands.add_parser('inspect-j4', help='saved-state diagnostic and offline process page')
    inspect.add_argument('--experiment', required=True); inspect.add_argument('--output', required=True)
    inspect.add_argument('--jobs', nargs='+')
    cases = commands.add_parser('inspect-decision-cases', help='offline state/action/outcome cases and bounded early-choice branches; no model or memory writes')
    cases.add_argument('--experiment', required=True); cases.add_argument('--output', required=True)
    cases.add_argument('--job', default='J0000'); cases.add_argument('--max-branches', type=int, default=4)
    cases.add_argument('--fork-mode', choices=('first_pick','first_violation'), default='first_violation')
    cb = commands.add_parser('compare-same-box-candidates', help='offline native-probability-ranked placement branches for the same box')
    cb.add_argument('--experiment', required=True); cb.add_argument('--output', required=True)
    cb.add_argument('--job', default='J0000'); cb.add_argument('--decision', default='J0000_D0000')
    cb.add_argument('--top-k', type=int, choices=(2,3), default=3)
    j4 = commands.add_parser('prepare-j4', help='freeze J4 five-method plan and memory identities')
    j4.add_argument('--profile', choices=('constructed-dev','dev'), default='constructed-dev')
    j4.add_argument('--mode', choices=('offline','remote'), default='offline')
    j4.add_argument('--dataset-root'); j4.add_argument('--source-limit', type=int, default=4)
    j4.add_argument('--business-spec'); j4.add_argument('--difficulty',choices=('loose','moderate','strict'))
    j4.add_argument('--task-ids',nargs='+',help='explicit preregistered task identities within the selected source scope')
    j4.add_argument('--task-limit',type=int,help='explicit deterministic prefix of diagnostic/development tasks')
    j4.add_argument('--methods', nargs='+', default=['shared_geometry','shared_business_lexicographic','jev_no_memory'])
    j4.add_argument('--output', required=True); j4.add_argument('--memory'); j4.add_argument('--api-budget', type=int)
    j4.add_argument('--offline-scenario', default='normal')
    pre4 = commands.add_parser('preflight-j4', help='zero-network v3 preflight')
    pre4.add_argument('--plan', required=True); pre4.add_argument('--api-key-file')
    run4 = commands.add_parser('run-j4', help='run explicit v3 frozen-memory plan; records verification')
    run4.add_argument('--plan', required=True); run4.add_argument('--output', required=True)
    runmode = run4.add_mutually_exclusive_group(required=True)
    runmode.add_argument('--offline', action='store_true'); runmode.add_argument('--remote', action='store_true')
    run4.add_argument('--api-key-file'); run4.add_argument('--resume', action='store_true')
    exp4 = commands.add_parser('export-memory', help='export sealed real training D0 facts; no generation')
    exp4.add_argument('--experiment', required=True); exp4.add_argument('--output', required=True)
    exp4.add_argument('--export-version',choices=('v1','v2'),default='v1')
    freeze = commands.add_parser('freeze-memory', help='freeze corpus identity or create empty snapshot')
    freeze.add_argument('--include-history', action='store_true', help='B1-A offline indexed history snapshot; no runtime enablement')
    freeze.add_argument('--store'); freeze.add_argument('--output', required=True)
    vm = commands.add_parser('validate-memory', help='read-only snapshot integrity validation')
    vm.add_argument('--memory', required=True)
    pm = commands.add_parser('preflight-memory', help='B1-A offline projection, freeze and deterministic retrieval audit')
    pm.add_argument('--store', required=True); pm.add_argument('--output', required=True)
    records4=commands.add_parser('validate-j4',help='read-only sealed J4 records audit; no trajectory replay')
    records4.add_argument('--experiment',required=True)
    gp = commands.add_parser('prepare-generation', help='B2 deterministic summary + independent R0/model budget preflight; zero network')
    gp.add_argument('--protocol',choices=('v1','v2','v3','v4'),default='v1')
    gp.add_argument('--store', required=True); gp.add_argument('--output', required=True)
    gp.add_argument('--experiment'); gp.add_argument('--mode', choices=('remote_text','offline_fixture'), required=True)
    gg = commands.add_parser('generate-memory', help='explicit one-episode generate/merge with shared durable accounting')
    gg.add_argument('--prepared', required=True); gg.add_argument('--request', required=True); gg.add_argument('--store', required=True)
    gg.add_argument('--mode', choices=('remote_text','offline_fixture'), required=True)
    gg.add_argument('--repo'); gg.add_argument('--fixture'); gg.add_argument('--repair-fixture')
    gate = commands.add_parser('inspect-generation-gate',help='read-only expansion gate; parsed output alone is insufficient')
    gate.add_argument('--store',required=True);gate.add_argument('--request',required=True)
    gb = commands.add_parser('generate-memory-batch',help='frozen ordered episode generation; stop at first technical refusal')
    gb.add_argument('--prepared',required=True);gb.add_argument('--requests',nargs='+',required=True)
    gb.add_argument('--store',required=True);gb.add_argument('--output',required=True)
    gb.add_argument('--mode',choices=('remote_text','offline_fixture'),required=True)
    gb.add_argument('--repo');gb.add_argument('--fixtures',help='offline-only JSON mapping request digests to response fixture paths')
    gb.add_argument('--resume',action='store_true')
    mg = commands.add_parser('prepare-memory-merge', help='prepare compatible parent merge, frequency enforced on execution')
    mg.add_argument('--additional-prepared',nargs='*',default=[])
    mg.add_argument('--compatibility',help='content-bound pairwise compatibility assessment for developer-reviewed parents')
    mg.add_argument('--prepared',required=True); mg.add_argument('--store',required=True); mg.add_argument('--output',required=True)
    mg.add_argument('--parents',nargs='+',required=True)
    gr = commands.add_parser('inspect-memory-review', help='export independent human review materials; no model')
    gr.add_argument('--store', required=True); gr.add_argument('--output', required=True)
    gr.add_argument('--reviewer-mode',choices=('independent_human','developer_agent'),default='independent_human')
    gr.add_argument('--authorization-digest')
    ga=commands.add_parser('register-review-authorization',help='record an explicit review-role policy change; no model calls')
    ga.add_argument('--store',required=True);ga.add_argument('--authorization',required=True)
    ca=commands.add_parser('admit-unit-context-correction',help='offline versioned revalidation of unchanged unit-refused raw output')
    ca.add_argument('--store',required=True);ca.add_argument('--proposal',required=True);ca.add_argument('--authorization-digest',required=True)
    gi = commands.add_parser('import-memory-review', help='import content-bound independent human review; no model')
    gi.add_argument('--store', required=True); gi.add_argument('--review', required=True)
    gv = commands.add_parser('validate-generation', help='validate facts, raw responses and lifecycle; zero network')
    gv.add_argument('--store', required=True)
    gf = commands.add_parser('freeze-generation', help='freeze B1-compatible snapshot with full B2 artifacts')
    gf.add_argument('--store', required=True); gf.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    from .config import load_config,load_v2_config,is_v2
    from .experiment import export_j0, validate_j0, prepare_plan, validate_plan, run_experiment, preflight, METHODS
    try:
        if args.command == 'compare-same-box-candidates':
            from .candidate_branch import compare_same_box
            result = compare_same_box(args.experiment,args.output,job_id=args.job,decision_id=args.decision,top_k=args.top_k)
            result = dict(result, status='PASS')
        elif args.command == 'inspect-decision-cases':
            from .diagnostics import inspect_decision_cases
            result = inspect_decision_cases(args.experiment,args.output,job_id=args.job,max_branches=args.max_branches,fork_mode=args.fork_mode)
        elif args.command == 'smoke-packaging-runtime':
            from .packaging_runtime import smoke_runtime
            result = smoke_runtime(args.dataset, args.output)
        elif args.command == 'validate-packaging-runtime':
            from .packaging_runtime import verify_runtime_output
            result = verify_runtime_output(args.artifact)
        elif args.command == 'build-packaging-dataset':
            from .dataset_packaging import build_packaging_dataset
            result = build_packaging_dataset(args.repo, args.output)
        elif args.command == 'validate-packaging-dataset':
            from .dataset_packaging import validate_packaging_dataset
            result = validate_packaging_dataset(args.dataset)
        elif args.command == 'build-dataset-v2':
            from .dataset_j4 import build_dataset_v2
            result = build_dataset_v2(args.repo,args.output)
        elif args.command == 'validate-dataset-v2':
            from .dataset_j4 import validate_dataset_v2
            result = validate_dataset_v2(args.dataset)
        elif args.command == 'prepare-training-sources':
            from .dataset_j4 import prepare_training_sources
            result = prepare_training_sources(args.repo,args.readiness,args.output)
        elif args.command == 'prepare-generation':
            from .memory_generation import prepare_generation
            result = prepare_generation(args.store,args.output,experiment=args.experiment,mode=args.mode,protocol=args.protocol)
        elif args.command == 'generate-memory':
            from .memory_generation import generate_candidates
            result = generate_candidates(args.prepared,args.request,args.store,mode=args.mode,repo=args.repo,
                                         fixture=args.fixture,repair_fixture=args.repair_fixture)
            from .memory_generation import generation_gate
            result['processing_status'] = result['status']
            result['technical_gate'] = generation_gate(args.store,args.request)
            result['status'] = result['technical_gate']['status']
        elif args.command == 'inspect-generation-gate':
            from .memory_generation import generation_gate
            result = generation_gate(args.store,args.request)
        elif args.command == 'generate-memory-batch':
            from .memory_generation import run_generation_batch
            from .ledger import read
            result = run_generation_batch(args.prepared,args.requests,args.store,args.output,mode=args.mode,repo=args.repo,
                fixtures=read(args.fixtures) if args.fixtures else None,resume=args.resume)
        elif args.command == 'prepare-memory-merge':
            from .memory_generation import prepare_merge
            result = prepare_merge(args.prepared,args.store,args.parents,args.output,additional_prepared=args.additional_prepared,compatibility_file=args.compatibility)
        elif args.command == 'inspect-memory-review':
            from .memory_validation import review_materials
            result = review_materials(args.store,args.output,reviewer_mode=args.reviewer_mode,authorization_digest=args.authorization_digest)
        elif args.command == 'register-review-authorization':
            from .memory_validation import register_review_authorization
            result = register_review_authorization(args.store,args.authorization)
        elif args.command == 'admit-unit-context-correction':
            from .memory_validation import admit_unit_context_correction
            result=admit_unit_context_correction(args.store,args.proposal,args.authorization_digest)
        elif args.command == 'import-memory-review':
            from .memory_validation import import_review
            result = import_review(args.store,args.review)
        elif args.command == 'validate-generation':
            from .memory_validation import validate_store
            result = validate_store(args.store)
        elif args.command == 'freeze-generation':
            from .memory_validation import freeze_generation
            result = freeze_generation(args.store,args.output)
        elif args.command == 'audit-j4':
            from .dataset_j4 import audit_readiness
            result = audit_readiness(args.repo,args.output,raw_path=args.raw_path,reme_path=args.reme_path)
        elif args.command == 'inspect-j4':
            from .diagnostics import inspect_experiment
            report = inspect_experiment(args.experiment,args.output,job_ids=args.jobs)
            result = {k:v for k,v in report.items() if k != 'jobs'}
        elif args.command == 'prepare-j4':
            from .batch_j4 import prepare_j4
            result = prepare_j4(args.output,profile=args.profile,mode=args.mode,dataset_root=args.dataset_root,
                source_limit=args.source_limit,task_limit=args.task_limit,task_ids=args.task_ids,methods=args.methods,memory=args.memory,api_budget=args.api_budget,
                offline_scenario=args.offline_scenario,spec_config=args.business_spec,difficulty=args.difficulty)
        elif args.command == 'validate-j4':
            from .batch_j4 import audit_records_j4
            from .dataset_j4 import verify_seal
            if verify_seal(args.experiment)['status']!='PASS':raise ValueError('experiment_seal_not_verified')
            result=audit_records_j4(args.experiment)[0]
        elif args.command == 'preflight-j4':
            from .batch_j4 import preflight_j4
            result = preflight_j4(args.plan,api_key_file=args.api_key_file)
        elif args.command == 'run-j4':
            from .batch_j4 import run_j4
            result = run_j4(args.plan,args.output,offline=args.offline,remote=args.remote,
                            api_key_file=args.api_key_file,resume=args.resume)
        elif args.command == 'export-memory':
            from .memory_export import export_experiment
            result = export_experiment(args.experiment,args.output,version='jev_episode_export_'+args.export_version)
        elif args.command == 'preflight-memory':
            from .memory_retrieval import preflight_memory
            result = preflight_memory(args.store,args.output)
        elif args.command == 'freeze-memory':
            if args.include_history and not args.store:
                raise ValueError('history_freeze_requires_store')
            from .memory_store import MemoryStore,freeze_snapshot,empty_snapshot
            receipt = MemoryStore(args.store).freeze_snapshot(args.output,include_history=args.include_history) if args.store else freeze_snapshot(empty_snapshot(),args.output)
            result = dict(receipt,status='PASS',model_api_calls=0)
        elif args.command == 'validate-memory':
            from .memory_store import load_snapshot
            from .contracts import digest
            result = {'status':'PASS','memory_snapshot_digest':digest(load_snapshot(args.memory).data),'model_api_calls':0}
        elif args.command == "export-j0":
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
    if args.command in ('build-packaging-dataset', 'validate-packaging-dataset'):
        return 0 if result['status'] == 'STATIC_CHECKS_COMPLETE' else 1
    return 0 if result["status"] == "PASS" else 1

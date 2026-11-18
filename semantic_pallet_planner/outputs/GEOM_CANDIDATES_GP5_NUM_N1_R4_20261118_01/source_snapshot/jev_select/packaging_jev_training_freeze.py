"""Independent B2 offline freeze receipt over immutable v1 preparations.

No sender/episode/sampler/solver calls. A freeze binds saved material and QA,
not a real execution permit or independent review of this new delivery.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import packaging_jev_training_plan as plan
from .packaging_versions import JM_TRAINING_FREEZE_VERSION

require = plan.require
digest = plan.digest
BASE = plan.BASE
HISTORICAL_PACKAGE = BASE+'JEV_JM1_B2_FORMAL_PREP_20261112_01/'
HISTORICAL_PLAN = HISTORICAL_PACKAGE+'materials/training_plan.json'
PREP_QA_ROOT = BASE+'JEV_JM_B2_FORMAL_PREP_QA_20261112_01/'
PREP_QA_REPORT = 'docs/03_阶段产出分析/Jev/Jev_JM1-B2正式计划离线准备独立质检与冻结收尾交接_20261112_01.md'
QA_REQUIRED = plan.QA_REQUIRED + [PREP_QA_REPORT] + [PREP_QA_ROOT+n+'.json' for n in
                            ('quality_review', 'next_stage_admission', 'handoff', 'delivery_manifest')]
NAVIGATION = 'docs/03_阶段产出分析/Jev/README.md'
GATES = {'baseline':'SEPARATE_C1_AUTHORIZATION_AND_INDEPENDENT_CLOSURE_QA_REQUIRED',
         'suffix':'SEPARATELY_FROZEN_CONCRETE_C1_PLAN_AND_SEPARATE_C2_AUTHORIZATION_REQUIRED',
         'c1_stop':'STOP_AFTER_CONCRETE_PLAN_MATERIALIZATION_BEFORE_SUFFIX'}


def freeze_readiness(*, root):
    root = Path(root).resolve()
    missing = [p for p in QA_REQUIRED if not (root/p).is_file()]
    return {'version':'jev_jm_training_freeze_readiness_v1',
            'status':'DEFER_MISSING_QA' if missing else 'QA_PRESENT_NOT_YET_VALIDATED',
            'missing':missing, 'execution_authorized':False}


def _bytes(ref, *, root):
    require(plan.ref(ref['path'], root=root) == ref, 'FREEZE_REFERENCE_BYTES_DRIFT')


def _qa_audit(refs, *, root):
    require(len(refs) == len(QA_REQUIRED) and {r['path'] for r in refs} == set(QA_REQUIRED),
            'FREEZE_QA_INVENTORY')
    for ref in refs:
        _bytes(ref, root=root)
    audits = []
    for folder in (plan.QA_ROOT, PREP_QA_ROOT):
        manifest = plan.load(next(r for r in refs if r['path'] == folder+'delivery_manifest.json'), root=root)
        seen = set(); files = []; navigation = []
        for row in manifest['files']:
            require(row['path'] not in seen, 'FREEZE_QA_DUPLICATE_MANIFEST_FILE')
            seen.add(row['path'])
            if row['path'] == NAVIGATION:
                # Historical navigation bytes are known incomplete for parent QA.
                # Keep its expected hash; it is not runtime material or a waiver
                # for any report/JSON/script. Never rewrite the original manifest.
                navigation.append({'path':row['path'], 'expected_sha256':row['sha256'],
                                   'expected_bytes':row['bytes'],
                                   'status':'MUTABLE_NAVIGATION_EXCLUDED_NONBLOCKING'})
            else:
                ref = plan.ref(row['path'], root=root)
                require(ref['sha256'] == row['sha256'] and
                        (Path(root)/row['path']).stat().st_size == row['bytes'], 'FREEZE_QA_MANIFEST_DRIFT')
                files.append(ref)
        required_members = {p for p in QA_REQUIRED if p.startswith(folder) and not p.endswith('delivery_manifest.json')}
        require(required_members <= seen, 'FREEZE_QA_MANIFEST_INCOMPLETE')
        audits.append({'manifest_path':folder+'delivery_manifest.json',
                       'verified_non_navigation':files, 'navigation':navigation})
    parent = plan.load(next(r for r in refs if r['path'] == plan.QA_ROOT+'quality_review.json'), root=root)
    prep = plan.load(next(r for r in refs if r['path'] == PREP_QA_ROOT+'quality_review.json'), root=root)
    parent_admission = plan.load(next(r for r in refs if r['path'] == plan.QA_ROOT+'next_stage_admission.json'), root=root)
    prep_admission = plan.load(next(r for r in refs if r['path'] == PREP_QA_ROOT+'next_stage_admission.json'), root=root)
    require(parent['version'] == 'jm_v13_fix_independent_qa_v1' and
            any(f['id'] == 'QA-JMV13-01' and f['status'] == 'CLOSED_CONSTRUCTED_SCOPE'
                for f in parent['closed_findings']) and not parent['remaining_issue_blockers'], 'FREEZE_PARENT_QA_NOT_CLOSED')
    require(prep['version'] == 'jm_b2_formal_prep_independent_qa_v1' and
            not prep['blocking_production_defects_for_offline_scope'] and
            all(any(a['id'] == key and a['status'] == 'PASS' for a in prep['acceptance'])
                for key in ('M12-01', 'M12-04', 'M12-07')), 'FREEZE_PREPARATION_QA_NOT_ACCEPTED')
    require(parent_admission['execution_authorized'] is False and
            parent_admission['real_calls_authorized'] == prep_admission['real_calls_authorized'] == 0 and
            prep_admission['status'] == 'NOT_READY', 'FREEZE_QA_AUTHORITY_BOUNDARY')
    return audits


def _same_study(new, old, *, root):
    """Allow only new storage/allocation/source identity, never a new study."""
    for key in ('selection_rule', 'requested_count', 'smaller_scope_reason', 'catalog_ref',
                'input_refs', 'audit_ref', 'sampling', 'gates', 'model_declaration'):
        if key == 'audit_ref':
            require(plan.load(new[key], root=root) == plan.load(old[key], root=root), 'FREEZE_STUDY_DRIFT')
        else:
            require(new[key] == old[key], 'FREEZE_STUDY_DRIFT')
    require(len(new['assignments']) == len(old['assignments']) == 6, 'FREEZE_STUDY_TASK_COUNT')
    for a, b in zip(new['assignments'], old['assignments']):
        excluded = {'execution_ref', 'job_id'}
        require({k:v for k,v in a.items() if k not in excluded} ==
                {k:v for k,v in b.items() if k not in excluded}, 'FREEZE_STUDY_TASK_DRIFT')
        nc = plan.load(a['execution_ref'], root=root)['config']
        oc = plan.load(b['execution_ref'], root=root)['config']
        require({k:v for k,v in nc.items() if k != 'runtime_identity'} ==
                {k:v for k,v in oc.items() if k != 'runtime_identity'}, 'FREEZE_CONFIG_DRIFT')
        require({k:v for k,v in nc['runtime_identity'].items() if k != 'strategy_identity'} ==
                {k:v for k,v in oc['runtime_identity'].items() if k != 'strategy_identity'}, 'FREEZE_RUNTIME_CONTRACT_DRIFT')
    # Job allocation IDs change with storage roots; all numerical reservations stay.
    def budget_without_jobs(b):
        return {**b, 'baseline_jobs':[{k:v for k,v in r.items() if k != 'job_id'} for r in b['baseline_jobs']]}
    require(budget_without_jobs(new['budget']) == budget_without_jobs(old['budget']), 'FREEZE_BUDGET_STUDY_DRIFT')


def _bindings(value, plan_ref, *, root):
    schedule = plan.load(value['schedule_ref'], root=root)
    runtime_root = (Path(root)/plan_ref['path']).parent/'future_runs'
    require(schedule['storage_root'] == str(runtime_root), 'FREEZE_SCHEDULE_PATH_DRIFT')
    jobs = []
    for i, row in enumerate(value['assignments']):
        ex = plan.load(row['execution_ref'], root=root)
        require(ex['storage_root'] == str(runtime_root/f'baseline_{i+1}'), 'FREEZE_JOB_PATH_DRIFT')
        c = ex['config']
        jobs.append({'task_id':row['task_id'], 'slot_id':row['slot_id'], 'job_id':row['job_id'],
                     'allocation_id':ex['allocation_id'], 'storage_root':ex['storage_root'],
                     'execution_ref':row['execution_ref'], 'execution_digest':digest(ex),
                     'config_digest':digest(c), 'task_digest':row['runtime_task_digest'],
                     'arrival_digest':row['arrival_digest'], 'strategy_identity':c['runtime_identity']['strategy_identity'],
                     'physical_identity':c['runtime_identity']['physical_identity'],
                     'monitor_identity':c['runtime_identity']['monitor_identity'], 'max_sends':ex['max_sends']})
    return str(runtime_root), jobs


def freeze_plan(plan_ref, *, root):
    """Return a new formal offline freeze receipt, never modify its preparation."""
    require(not freeze_readiness(root=root)['missing'], 'FREEZE_QA_MISSING_DEFER')
    root = Path(root).resolve()
    qa_refs = [plan.ref(p, root=root) for p in QA_REQUIRED]
    qa_audit = _qa_audit(qa_refs, root=root)
    value = plan.load(plan_ref, root=root)
    require(plan_ref['path'] != HISTORICAL_PLAN, 'FREEZE_NEW_PLAN_REQUIRED')
    plan.validate_plan(value, root=root)
    require(not value['missing_qa'] and len(value['qa_refs']) == len(plan.QA_REQUIRED), 'FREEZE_PREPARATION_QA_MISSING')
    require(value['qa_refs'] == qa_refs[:len(plan.QA_REQUIRED)], 'FREEZE_PREPARATION_QA_BINDING')
    history_ref = plan.ref(HISTORICAL_PLAN, root=root)
    history_manifest_ref = plan.ref(HISTORICAL_PACKAGE+'delivery_manifest.json', root=root)
    historical_manifest = plan.load(history_manifest_ref, root=root)
    require(any(r['path'] == HISTORICAL_PLAN and r['sha256'] == history_ref['sha256']
                for r in historical_manifest['files']), 'FREEZE_HISTORICAL_PLAN_DRIFT')
    old = plan.load(history_ref, root=root)
    require(old['formal_frozen'] is False and old['qa_refs'] == [] and
            old['missing_qa'] == plan.QA_REQUIRED and
            old['plan_digest'] == digest({k:v for k,v in old.items() if k != 'plan_digest'}),
            'FREEZE_HISTORICAL_SNAPSHOT')
    _same_study(value, old, root=root)
    runtime_root, jobs = _bindings(value, plan_ref, root=root)
    receipt = {'version':JM_TRAINING_FREEZE_VERSION, 'state':'FROZEN_OFFLINE', 'formal_frozen':True,
               'execution_authorized':False, 'operation_root':str(root), 'runtime_root':runtime_root,
               'plan_ref':plan_ref, 'preparation_digest':value['plan_digest'],
               'historical_plan_ref':history_ref, 'historical_manifest_ref':history_manifest_ref,
               'qa_refs':qa_refs, 'qa_audit':qa_audit, 'runtime_identity':value['runtime_identity'],
               'jobs':jobs, 'budget':value['budget'], 'sampling':value['sampling'], 'gates':GATES,
               'admission':{'B2_plan':'FORMALLY_FROZEN_OFFLINE', 'new_delivery_review':'PENDING_INDEPENDENT_QA',
                            'C1':'NOT_AUTHORIZED', 'C2':'NOT_AUTHORIZED',
                            'QA-JMB2P-01':'REMEDIATION_IMPLEMENTED_PENDING_INDEPENDENT_QA'},
               'materialization':{'epsilon':plan.DEFER, 'points':plan.DEFER, 'exact_actions':plan.DEFER,
                                  'suffix_jobs':plan.DEFER},
               'identity_change_reason':'NEW_QA_BOUND_PLAN_AND_STORAGE_ALLOCATION; ADDITIVE_FREEZE_PROTOCOL_SOURCE; STUDY_UNCHANGED'}
    receipt['receipt_digest'] = digest(receipt)
    return receipt


def validate_frozen_plan(receipt, *, root):
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).with_name('schemas')/'jm_training_freeze_v1.schema.json').read_text())
    require(Draft202012Validator(schema).is_valid(receipt), 'FREEZE_SCHEMA')
    require(receipt['receipt_digest'] == digest({k:v for k,v in receipt.items() if k != 'receipt_digest'}), 'FREEZE_DIGEST')
    require(receipt['operation_root'] == str(Path(root).resolve()), 'FREEZE_OPERATION_ROOT_DRIFT')
    for ref in receipt['qa_refs']:
        _bytes(ref, root=root)
    require(receipt == freeze_plan(receipt['plan_ref'], root=root), 'FREEZE_IDENTITY_OR_BINDING_DRIFT')
    return {'version':'jev_jm_training_freeze_check_v1', 'saved_facts':'PASS', 'formal_freeze':'FROZEN_OFFLINE',
            'new_delivery_review':'PENDING_INDEPENDENT_QA', 'execution_authorized':False,
            'C1':'NOT_RUN_NOT_AUTHORIZED', 'C2':'NOT_RUN_NOT_AUTHORIZED'}


def require_send_authorization(receipt, *, root, stage, permit=None):
    validate_frozen_plan(receipt, root=root)
    require(stage in ('BASELINE', 'SUFFIX'), 'FREEZE_UNKNOWN_SEND_GATE')
    require(False, 'FREEZE_NOT_A_SEND_PERMIT')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['validate', 'baseline-gate', 'suffix-gate'])
    parser.add_argument('input'); parser.add_argument('--root', default='.')
    args = parser.parse_args()
    value = plan.sampling.strict_load(Path(args.input).read_bytes())
    if args.mode == 'validate':
        print(json.dumps(validate_frozen_plan(value, root=args.root), ensure_ascii=False, indent=2))
    else:
        require_send_authorization(value, root=args.root, stage='BASELINE' if args.mode == 'baseline-gate' else 'SUFFIX')


if __name__ == '__main__':
    main()

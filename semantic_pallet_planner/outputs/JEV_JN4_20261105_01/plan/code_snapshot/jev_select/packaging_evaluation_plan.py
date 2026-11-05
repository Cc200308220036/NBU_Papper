"""JN4-A blocked-plan and placebo contracts. Deliberately has NO run command.

An incomplete data admission is a deliverable, not permission to dispatch v9.
A future executable protocol requires its own closed schema and integration.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from .contracts import canonical, digest, validate_schema
from .packaging_source_audit import require, sha, load, validate_partition

VERSION = 'jev_evaluation_plan_blocked_v1'
REGISTRY = {
    'local_geometry_test_double': {'origin':'local_test_double','memory':'none','remote':False},
    'local_first_test_double': {'origin':'local_test_double','memory':'none','remote':False},
    'jev_no_memory': {'origin':'jev','memory':'none','remote':True},
    'jev_with_trajectory': {'origin':'jev','memory':'T','remote':True},
    'jev_with_contrast_experience': {'origin':'jev','memory':'E','remote':True},
    'jev_with_unrelated_E_control': {'origin':'jev','memory':'E_unrelated_control','remote':True},
}
CONTROL_RULE = {
    'version':'jev_unrelated_E_placebo_v1','target':'E', 'seed':20261105,
    'factor':'relevant evidence vs unrelated additional prompt content',
    'selection':'same frozen E public query, source exclusions, ranking and whole-entry budgets; replace admitted E fragment by paired placebo',
    'content':'predeclared ASCII text about typesetting punctuation; explicitly NON_EVIDENCE, no packing advice, measured numbers or invented claims',
    'length':'canonical JSON entry chars AND UTF-8 bytes exactly equal paired E fragment; array overhead identical; tolerance zero',
    'residual_difference':'different fields/meaning and repetitive filler; equal bytes do not equate tokens, attention or semantic information',
    'mutability':'one deterministic version; no alternate seeds or result-dependent reconstruction',
}


def build_control(snapshot):
    from .packaging_contrast import validate_snapshot
    value=validate_snapshot(snapshot)
    entries=[]
    for card in value['cards']:
        target=canonical(card['public_fragment'])
        require(len(target)==len(target.encode()),'control_non_ascii_reference')
        public={'kind':'UNRELATED_NON_EVIDENCE','topic':'typesetting',
                'notice':'Placebo text. No packing evidence or recommendation.', 'text':''}
        n=len(target)-len(canonical(public))
        require(n>=0,'control_length_unachievable')
        sentence='A comma separates clauses. A period ends a sentence. Spaces separate words. '
        public['text']=(sentence*((n//len(sentence))+1))[:n]
        require(len(canonical(public))==len(target),'control_length_mismatch')
        entries.append({'reference_public_digest':card['public_digest'],
                        'public_fragment':public,'public_digest':digest(public),
                        'chars':len(target),'utf8_bytes':len(target.encode())})
    result={'version':'jev_unrelated_E_snapshot_v1','mode':'E_unrelated_control',
        'review_status':'APPROVED_DETERMINISTIC_PLACEBO_NOT_EVIDENCE',
        'source_snapshot_digest':value['snapshot_digest'], 'source_groups':value['source_groups'],
        'rule':CONTROL_RULE,'entries':entries}
    result['snapshot_digest']=digest(result)
    return result


def validate_control(control, snapshot):
    validate_schema('evaluation_control_v1',control)
    require(control==build_control(snapshot),'control_tampered_or_unreviewed')
    return control


def budget_for_tasks(tasks, repetitions=1):
    require(type(repetitions) is int and repetitions==1,'unregistered_repeats')
    require(len({t['task_id'] for t in tasks})==len(tasks),'duplicate_tasks')
    jobs=[]
    for t in tasks:
        n=len(t['items'])
        require(n>0,'empty_task')
        for method,meta in REGISTRY.items():
            jobs.append({'job_id':f'J{len(jobs):04d}','task_id':t['task_id'],
                'method_id':method,'repeat':0,'max_sends':n if meta['remote'] else 0,
                'status':'NOT_RUN'})
    return {'jobs':jobs,'natural_job_slots':len(jobs),
            'remote_job_slots':sum(REGISTRY[j['method_id']]['remote'] for j in jobs),
            'per_job':{j['job_id']:j['max_sends'] for j in jobs},
            'shared_batch_max_sends':sum(j['max_sends'] for j in jobs),
            'formula':'sum(task_box_count * 4 remote methods * 1 repeat); local/singleton sends zero; no credit recycling'}


def validate_plan(root, *, repo, for_execution=False):
    root=Path(root);repo=Path(repo);p=load(root/'plan/plan.json')
    validate_schema('evaluation_plan_blocked_v1',p)
    require(p['method_registry']==REGISTRY,'method_registry_changed')
    require(p['plan_digest']==digest({k:v for k,v in p.items() if k!='plan_digest'}),'plan_tampered')
    for name,expected in p['artifacts'].items():
        path=(root/name).resolve()
        require(path.is_relative_to(root.resolve()) and path.is_file() and sha(path)==expected,'artifact_changed')
    for name,expected in p['external_refs'].items():
        path=(repo/name).resolve()
        require(path.is_relative_to(repo.resolve()) and path.is_file() and sha(path)==expected,'parent_or_contract_changed')
    from .experiment import source_manifest
    require(source_manifest()==load(root/'source_manifest.json'),'production_identity_changed')
    from .packaging_experience import validate_snapshot as validate_T
    validate_T(load(repo/p['snapshots']['T']))
    from .packaging_contrast import validate_snapshot as validate_E
    e=validate_E(load(repo/p['snapshots']['E']))
    validate_control(load(root/p['snapshots']['control']),e)
    require(p['matrix']==budget_for_tasks([]),'blocked_matrix_not_empty')
    validate_partition(load(root/'split_manifest.json')['assignments'])
    if for_execution:
        require(False,'NOT_READY_JN4_B_NOT_ADMITTED')
    return {'status':'VALID_BLOCKED_PLAN','JN4_B_admitted':False,
            'model_api_calls':0,'formal_test_jobs_executed':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['validate','check-execution-admission'])
    parser.add_argument('--output',required=True);parser.add_argument('--repo',default='.')
    a=parser.parse_args()
    result=validate_plan(a.output,repo=a.repo,for_execution=a.command=='check-execution-admission')
    print(canonical(result))


if __name__=='__main__':main()

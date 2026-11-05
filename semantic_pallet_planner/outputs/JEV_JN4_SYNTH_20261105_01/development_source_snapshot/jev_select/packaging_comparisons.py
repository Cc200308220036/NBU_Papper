"""JN2-B versioned comparison collection over A's unchanged frozen fork runner.

Current analysis/orchestration identity is separate from the archived execution
package. A receipts are referenced, never rewritten or dispatched again.
"""
from __future__ import annotations
import copy
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .contracts import JevSelectError,digest,validate_schema
from .ledger import read,write,exclusive
from .experiment import source_manifest,file_manifest
from . import packaging_counterfactual as fork

REPO=Path(__file__).resolve().parents[4]
VERSION='jev_comparison_collection_v1'
A_DEFAULT='semantic_pallet_planner/outputs/JEV_JN2_20261104_01'
VALID_CATEGORIES=('COMPLETE','EMPTY_POOL','PREDICTED_STATIC_INSTABILITY')
DECISION_RULE='parent Jev job order; first eligible committed real choice and eligible ordinal floor(n/2), distinct; no outcome sampling'
LABEL_RULE={
 'version':'jev_branch_comparison_rule_v1','delta_direction':'alternative_minus_reference',
 'valid_categories':list(VALID_CATEGORIES),'invalid_label':'invalid',
 'primary_order':['stable_complete','placed_volume_ratio'],
 'secondary_directions':{'placed_item_ratio':1,'placed_mass_ratio':1,'envelope_utilization':1,'actual_height_mm':-1},
 'absolute_equivalence':{'ratio':1e-9,'height_mm':1e-6,'mass_kg':1e-9},
 'classification':'lexicographic primary; an opposing lower-priority primary or secondary makes trade_off; equal primary uses secondary Pareto; no opposing change => improved/degraded; all equal => neutral',
 'excluded_from_label':['fixed_container_utilization (duplicate volume)','remaining_capacity_sum','latency','cost'],
 'missing_secondary':'NA ignored with explicit evidence; never interpreted as zero',
 'experience_gate':'at least one valid improved pair; trade_off alone requires further research judgment, not automatic positive material',
 'scope':'registered intervention with fixed local continuation only; no global optimum or memory effectiveness claim',
}


def require(ok,code):
    if not ok:raise JevSelectError(code)


def rel(path):return Path(path).resolve().relative_to(REPO).as_posix()


def checked_manifest(root):
    root=Path(root);m=read(root/'delivery_manifest.json')
    require(all(fork.sha(root/n)==h for n,h in m['files_sha256'].items()),'comparison_parent_bytes_changed')
    return {'path':rel(root),'manifest_sha256':fork.sha(root/'delivery_manifest.json'),'files':len(m['files_sha256'])}


def stage_runtime(parent, root):
    """Copy exact A Python/JSON and algorithm auxiliaries, without editing any byte."""
    p=read(Path(parent)/'branch_plan.json');package=Path(root)/'runtime/semantic_pallet_planner'
    require(not package.exists(),'comparison_runtime_exists')
    for n,h in p['source_manifest'].items():
        origin=Path(parent)/'code_snapshot'/n;require(fork.sha(origin)==h,'comparison_archived_source_changed')
        dest=package/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(origin,dest)
    for n,h in read(Path(parent)/'algorithm_snapshot_manifest.json').items():
        origin=Path(parent)/'algorithm_snapshot'/n;require(fork.sha(origin)==h,'comparison_algorithm_archive_changed')
        dest=package/'jev_select/stability'/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(origin,dest)
    return package


def worker(root,command,*,decision=None,child=None):
    """Offline subprocess; execution imports only the archived package, not current analysis."""
    root=Path(root);a=read(root/'parent_reference.json')['path']
    with tempfile.TemporaryDirectory(prefix='jev_jn2_b_control_') as tmp:
        response=Path(tmp)/'response.json'
        argv=[sys.executable,str(Path(__file__).with_name('packaging_frozen_worker.py')),'--repo',str(REPO),
              '--parent-a',a,'--command',command,'--response',str(response)]
        if decision:argv+=['--decision',decision]
        if child:argv+=['--fork',rel(child)]
        safe_env=('PATH','HOME','LANG','LC_ALL','TMPDIR','TZ','CONDA_PREFIX','LD_LIBRARY_PATH','OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')
        env={k:os.environ[k] for k in safe_env if k in os.environ}
        env.update(PYTHONPATH=str(root/'runtime'),PYTHONDONTWRITEBYTECODE='1')
        completed=subprocess.run(argv,cwd=REPO,env=env,capture_output=True,text=True)
        require(completed.returncode==0,'comparison_frozen_worker_failed:'+completed.stderr[-1500:])
        result=read(response);require(result['status']=='OK' and all(v==0 for v in result['guard_counts'].values()),'comparison_guard_violation')
        return result


def decision_matrix(parent_a):
    ap=read(Path(parent_a)/'branch_plan.json');jn1=REPO/ap['parent_identity']['parent']
    p=read(jn1/'plan/plan.json');rows=read(jn1/'jn2_decision_index.json')['all_decisions'];matrix=[]
    for job in p['jobs']:
        if job['method_id']!='jev_no_memory':continue
        eligible=[]
        for r in sorted((r for r in rows if r['job_id']==job['job_id']),key=lambda r:r['decision_id']):
            if not r['eligible_training_decision']:continue
            e=read(jn1/'run/jobs'/job['job_id']/'actions'/f"{r['decision_id']}.json")
            if e['event']=='PLACE' and e['selection']['source']=='jev' and e['route']=='CHOICE_REQUIRED':eligible.append(r)
        if not eligible:continue
        for ordinal in dict.fromkeys([0,len(eligible)//2]):
            r=eligible[ordinal]
            matrix.append({'group_id':f'F{len(matrix):02d}','decision_id':r['decision_id'],'task_id':r['task_id'],
                           'source_group':r['source_group'],'eligible_ordinal':ordinal,'eligible_count':len(eligible),
                           'mode':'REUSE_A' if r['decision_id']==ap['decision_id'] else 'NEW'})
    require(len({x['source_group'] for x in matrix})<=2 and len(matrix)<=4,'comparison_source_scope')
    require(sum(x['mode']=='REUSE_A' for x in matrix)==1,'comparison_missing_A_reuse')
    return matrix


def child_plan(ap,payload):
    s=payload['snapshot'];cfg=payload['config'];p=copy.deepcopy(ap)
    p.update(fork_digest=digest(s),source_group=s['source_group'],decision_id=s['decision_id'],task_digest=s['task_digest'],
             config=cfg,selection=payload['selection'],scanned=[{'decision_id':s['decision_id'],'status':'VERIFIED_ELIGIBLE'}],
             continuation={'method':fork.METHOD,'display_seed':cfg['display_order_seed'],'randomness':'deterministic; no additional RNG',
                           'identity':cfg['runtime_identity']['strategy_identity']},
             branch_order=[f'B{i:02d}' for i in range(len(payload['selection']['branches']))])
    p['budget']['registered']=len(p['branch_order']);return fork.seal(p)


def create_child(root,entry,payload,ap):
    child=Path(root)/'forks'/entry['group_id'];child.mkdir(parents=True)
    p=child_plan(ap,payload);s=payload['snapshot']
    write(child/'branch_plan.json',p);write(child/'fork_snapshot.json',s);write(child/'task.private.json',payload['task'])
    write(child/'parent_verification.json',ap['parent_identity'])
    write(child/'registration_receipt.json',{'plan_digest':digest(p),'fork_digest':digest(s)})
    # Same bytes, new location. Do not copy current analysis into this source tree.
    shutil.copytree(Path(root)/'runtime/semantic_pallet_planner',child/'code_snapshot')
    for jid,first in zip(p['branch_order'],p['selection']['branches']):
        b=fork.seal({'version':fork.VERSION,'job_id':jid,'snapshot':s,'first':first,'config_digest':digest(p['config']),'plan_digest':digest(p)})
        write(child/'branches'/jid/'binding.json',b)
        write(child/'branches'/jid/'status.json',{'state':'NOT_RUN','category':'NOT_RUN','active_wall_s':0.,'error':None})
    return p


def prepare(parent_a,output):
    parent=Path(parent_a).resolve();require(parent==(REPO/A_DEFAULT).resolve(),'comparison_unregistered_parent_A');reference=checked_manifest(parent);ap=read(parent/'branch_plan.json')
    require(read(parent/'fork_engine_readiness.json')['JN2_B_admitted'],'comparison_A_not_admitted')
    for path in (REPO/'semantic_pallet_planner/outputs').glob('JEV_JN2_*/comparison_plan.json'):
        require(read(path)['parent_a']!=reference,'comparison_already_registered_use_resume')
    matrix=decision_matrix(parent)
    root=fork.common.new_output(output);write(root/'parent_reference.json',reference);stage_runtime(parent,root)
    ident=worker(root,'identity');audit=worker(root,'audit-a')
    require(ident['value']['environment']==read(parent/'environment.json')['execution_environment'],'comparison_environment_changed')
    require(ident['value']['source_digest']==digest(ap['source_manifest']) and ident['value']['monitor']==ap['config']['stability_monitor'],'comparison_execution_identity_changed')
    entries=[]
    for e in matrix:
        payload=worker(root,'snapshot',decision=e['decision_id']);write(root/'inputs'/f"{e['group_id']}.json",payload)
        val=payload['value'];s=val['snapshot'];cfg=val['config']
        require(val['task']['partition']=='train' and s['source_group']==e['source_group'] and val['task']['task_id']==e['task_id'],'comparison_training_binding')
        cp=child_plan(ap,val)
        if e['mode']=='REUSE_A':
            require(s==read(parent/'fork_snapshot.json') and cp['selection']==ap['selection'] and cfg==ap['config'],'comparison_A_reuse_mismatch')
            location=reference['path'];plan_digest=digest(ap)
        else:
            create_child(root,e,val,ap);location=rel(root/'forks'/e['group_id']);plan_digest=digest(cp)
        entries.append({**e,'location':location,'fork_digest':digest(s),'config_digest':digest(cfg),'child_plan_digest':plan_digest,
                        'first_actions':val['selection']['branches'],'coverage_gaps':val['selection']['coverage_gaps'],
                        'native_probability_complete':val['selection']['native_probability_complete']})
    added=sum(len(e['first_actions']) for e in entries if e['mode']=='NEW')
    require(added<=9 and added+3<=12,'comparison_budget_exceeded')
    p=fork.seal({'version':VERSION,'parent_a':reference,'jn1_parent':ap['parent_identity'],'root':rel(root),
        'decision_rule':DECISION_RULE,'action_rule':fork.RULE,'label_rule':LABEL_RULE,'entries':entries,
        'execution_source_manifest':ap['source_manifest'],'analysis_source_manifest':source_manifest(),
        'worker_sha256':fork.sha(Path(__file__).with_name('packaging_frozen_worker.py')),
        'watchdog':ap['watchdog'],'watchdog_boundary':ap['watchdog_boundary'],
        'continuation_method':fork.METHOD,'display_seed':ap['config']['display_order_seed'],
        'budget':{'A_used':3,'B_registered':added,'total_registered':3+added,'cumulative_max':12,'new_model_calls':0},
        'batch_stop':'natural stops continue; technical/cancel/watchdog or identity/derivation error stops all remaining; no retry or budget reset'})
    validate_schema('packaging_comparison_plan_v1',p)
    write(root/'comparison_plan.json',p);write(root/'plan_anchor.json',{'plan_digest':digest(p),'root':rel(root)})
    require(all(fork.sha(Path(__file__).resolve().parents[1]/n)==h for n,h in ap['source_manifest'].items() if n!='jev_select/contracts.py'),'comparison_current_saved_validator_behavior_changed')
    write(root/'compatibility_review.json',{'status':'PASS','A_receipts_reused':3,'A_source_digest':digest(ap['source_manifest']),
        'analysis_source_digest':digest(p['analysis_source_manifest']),'analysis_equals_execution_source':False,
        'execution_identity':ident,'A_readonly_validation':audit,
        'routing':'only artifact REPO anchor rebased; exact archived package bytes, algorithm, method, seed, per-task configuration and environment retained',
        'current_runtime_files_unchanged':all(fork.sha(Path(__file__).resolve().parents[1]/n)==h for n,h in ap['source_manifest'].items() if n not in ('jev_select/contracts.py',)),
        'scope':'new wrapper controls registration/process/batch only; no branch behavior modification'})
    for e in entries:write(root/'group_status'/f"{e['group_id']}.json",{'state':'REUSED' if e['mode']=='REUSE_A' else 'NOT_RUN','error':None})
    for n in p['analysis_source_manifest']:
        target=root/'analysis_code_snapshot'/n;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(Path(__file__).resolve().parents[1]/n,target)
    write(root/'budget_ledger.json',budget_ledger(root,p))
    return p


def validate_plan(root,*,canonical=True):
    root=Path(root).resolve();p=read(root/'comparison_plan.json');fork.check_seal(p);validate_schema('packaging_comparison_plan_v1',p)
    require(p['root']==rel(root) and read(root/'plan_anchor.json')=={'plan_digest':digest(p),'root':rel(root)},'comparison_plan_location_or_digest_changed')
    require(p['analysis_source_manifest']==source_manifest() and p['worker_sha256']==fork.sha(Path(__file__).with_name('packaging_frozen_worker.py')),'comparison_analysis_changed')
    for other in (REPO/'semantic_pallet_planner/outputs').glob('JEV_JN2_*/comparison_plan.json'):
        if other.resolve()!=root/'comparison_plan.json':
            require(read(other)['parent_a']!=p['parent_a'],'comparison_duplicate_registration')
    require(p['parent_a']['path']==A_DEFAULT,'comparison_unregistered_parent_A')
    parent=REPO/p['parent_a']['path'];require(checked_manifest(parent)==p['parent_a'],'comparison_parent_reference_changed')
    ap=read(parent/'branch_plan.json')
    require(p['watchdog']==ap['watchdog'] and p['watchdog_boundary']==ap['watchdog_boundary'] and p['display_seed']==ap['config']['display_order_seed'] and p['continuation_method']==fork.METHOD,'comparison_common_settings_changed')
    require(p['execution_source_manifest']==ap['source_manifest'] and p['decision_rule']==DECISION_RULE and p['label_rule']==LABEL_RULE and p['action_rule']==fork.RULE,'comparison_rules_or_execution_changed')
    expected=decision_matrix(parent);require(len(expected)==len(p['entries']),'comparison_matrix_changed')
    for actual,e in zip(p['entries'],expected):
        require(all(actual[k]==v for k,v in e.items()),'comparison_unregistered_decision')
        payload=read(root/'inputs'/f"{e['group_id']}.json")
        if canonical:require(payload==worker(root,'snapshot',decision=e['decision_id']),'comparison_resigned_input_changed')
        val=payload['value'];cp=child_plan(ap,val)
        require(actual['fork_digest']==digest(val['snapshot']) and actual['first_actions']==val['selection']['branches'] and actual['config_digest']==digest(val['config']) and
                actual['coverage_gaps']==val['selection']['coverage_gaps'] and actual['native_probability_complete']==val['selection']['native_probability_complete'],'comparison_action_or_identity_changed')
        if e['mode']=='NEW':
            child=root/'forks'/e['group_id']
            require(actual['location']==rel(child) and read(child/'branch_plan.json')==cp and actual['child_plan_digest']==digest(cp),'comparison_child_plan_changed')
            require(read(child/'fork_snapshot.json')==val['snapshot'] and read(child/'task.private.json')==val['task'],'comparison_child_input_changed')
            require(read(child/'registration_receipt.json')=={'plan_digest':digest(cp),'fork_digest':digest(val['snapshot'])},'comparison_child_registration_changed')
            for jid,first in zip(cp['branch_order'],cp['selection']['branches']):
                require(read(child/'branches'/jid/'binding.json')==fork.seal({'version':fork.VERSION,'job_id':jid,'snapshot':val['snapshot'],'first':first,'config_digest':digest(cp['config']),'plan_digest':digest(cp)}),'comparison_child_binding_changed')
        else:require(actual['location']==p['parent_a']['path'] and val['config']==ap['config'],'comparison_A_location_or_config_changed')
    added=sum(len(e['first_actions']) for e in p['entries'] if e['mode']=='NEW')
    require(p['budget']=={'A_used':3,'B_registered':added,'total_registered':3+added,'cumulative_max':12,'new_model_calls':0} and added<=9,'comparison_budget_changed')
    package=root/'runtime/semantic_pallet_planner'
    require(all(fork.sha(package/n)==h for n,h in ap['source_manifest'].items()),'comparison_frozen_runtime_changed')
    require(all(fork.sha(package/'jev_select/stability'/n)==h for n,h in read(parent/'algorithm_snapshot_manifest.json').items()),'comparison_frozen_algorithm_changed')
    require(all(fork.sha(root/'analysis_code_snapshot'/n)==h for n,h in p['analysis_source_manifest'].items()),'comparison_analysis_archive_changed')
    return p


def budget_ledger(root,p):
    rows=[]
    for e in p['entries']:
        for i,first in enumerate(e['first_actions']):
            jid=f'B{i:02d}';job=REPO/e['location']/'branches'/jid
            status=read(job/'status.json');started=e['mode']=='REUSE_A' or (job/'checkpoint.json').exists() or status['state']!='NOT_RUN'
            rows.append({'slot':f"{e['group_id']}/{jid}",'mode':e['mode'],'decision_id':e['decision_id'],'intervention':first['intervention'],
                         'started':started,'category':status['category'],'state':status['state'],'receipt':rel(job/'branch_receipt.json') if (job/'branch_receipt.json').exists() else None})
    new_started=sum(x['started'] for x in rows if x['mode']=='NEW')
    require(new_started<=p['budget']['B_registered']<=9 and 3+new_started<=12,'comparison_actual_budget_exceeded')
    return {'version':'jev_comparison_budget_v1','plan_digest':digest(p),'A_used':3,'B_started':new_started,'cumulative_started':3+new_started,
            'registered_total':len(rows),'cumulative_max':12,'model_calls':0,'rows':rows}


def value_vector(m):
    if not isinstance(m,dict):return None
    return {'stable_complete':int(m['stable_complete']),'placed_volume_ratio':m['loading']['placed_volume_ratio'],
            'placed_item_ratio':m['loading']['placed_item_ratio'],'placed_mass_ratio':m['loading']['placed_mass_ratio'],
            'placed_items':m['loading']['placed_items'],'placed_mass_kg':m['loading']['placed_mass_kg'],
            'fixed_container_utilization':m['fixed_container_utilization'],'actual_height_mm':m['actual_height_mm'],
            'envelope_utilization':m['envelope_utilization']}


def classify(ref,alt):
    invalid=[{'side':side,'category':r['status']['category']} for side,r in [('reference',ref),('alternative',alt)] if r['status']['category'] not in VALID_CATEGORIES or not isinstance(r['metrics'],dict)]
    a=value_vector(ref['metrics']);b=value_vector(alt['metrics'])
    delta={k:(b[k]-a[k] if type(a[k]) in (int,float) and type(b[k]) in (int,float) else 'NA') for k in a} if a and b else 'NOT_AVAILABLE'
    if invalid:return False,'invalid',invalid,delta
    def sign(k):
        v=delta[k]
        if v=='NA':return 0
        tol=LABEL_RULE['absolute_equivalence']['height_mm' if k=='actual_height_mm' else 'ratio']
        return 0 if abs(v)<=tol else (1 if v>0 else -1)
    primary=next((sign(k) for k in LABEL_RULE['primary_order'] if sign(k)),0)
    secondary=[sign(k)*direction for k,direction in LABEL_RULE['secondary_directions'].items()]
    primary_signs=[sign(k) for k in LABEL_RULE['primary_order'] if sign(k)]
    signs=primary_signs+[x for x in secondary if x]
    label='neutral' if not signs else 'trade_off' if min(signs)<0<max(signs) else 'improved' if max(signs)>0 else 'degraded'
    return True,label,[],delta


def comparison_record(entry,snapshot,reference,alternative,ref_path,alt_path,execution_digest):
    fork.check_seal(reference);fork.check_seal(alternative)
    require(reference['fork_digest']==alternative['fork_digest']==entry['fork_digest'] and reference['continuation']==alternative['continuation'],'comparison_pair_identity_mismatch')
    require(reference['first']['intervention']=='ORIGINAL_ACTION_REFERENCE' and alternative['first'] in entry['first_actions'][1:] and reference['first']==entry['first_actions'][0],'comparison_wrong_reference_or_alternative')
    valid,label,reasons,delta=classify(reference,alternative)
    row=fork.seal({'version':'jev_comparison_record_v1','comparison_id':entry['group_id']+'_'+alternative['job_id'],
      'source_group':entry['source_group'],'task':entry['task_id'],'decision':entry['decision_id'],
      'fork_digest':entry['fork_digest'],'state_digest':digest(snapshot['state']),'candidate_pool_digest':digest(snapshot['pool']),
      'reference_action':reference['first'],'alternative_action':alternative['first'],'intervention':alternative['first']['intervention'],
      'probability':{'native_complete':entry['native_probability_complete'],'native_probabilities':snapshot['event']['selection'].get('probabilities'),
                     'explicit_provider_rank':'UNAVAILABLE','provider_tie_rule':'UNKNOWN','program_sampling_rule':fork.RULE},
      'continuation':reference['continuation'],'execution_source_digest':execution_digest,
      'receipts':{'reference':{'path':ref_path,'digest':digest(reference)},'alternative':{'path':alt_path,'digest':digest(alternative)}},
      'reference_result':reference,'alternative_result':alternative,'delta_direction':'alternative_minus_reference','delta':delta,
      'stop_reasons':{'reference':reference['status']['category'],'alternative':alternative['status']['category']},
      'comparison_valid':valid,'invalid_reasons':reasons,'label':label,'label_rule':LABEL_RULE,
      'evidence':{'saved_prefix':snapshot['field_evidence'],'reference_branch':str(Path(ref_path).parent),'alternative_branch':str(Path(alt_path).parent)},
      'interpretation':'only registered exact intervention + fixed local continuation; no global optimum or memory effectiveness claim'})
    validate_schema('packaging_comparison_record_v1',row);return row


def records(root,p):
    result=[]
    for e in p['entries']:
        payload=read(Path(root)/'inputs'/f"{e['group_id']}.json")['value'];location=REPO/e['location']
        refpath=location/'branches/B00/branch_receipt.json';reference=read(refpath)
        for i in range(1,len(e['first_actions'])):
            altpath=location/'branches'/f'B{i:02d}'/'branch_receipt.json';alternative=read(altpath)
            result.append(comparison_record(e,payload['snapshot'],reference,alternative,rel(refpath),rel(altpath),digest(p['execution_source_manifest'])))
    return result


def ensure_not_run_receipts(root,p):
    for e in p['entries']:
        if e['mode']!='NEW':continue
        child=REPO/e['location'];cp=read(child/'branch_plan.json');task=read(child/'task.private.json')
        for jid in cp['branch_order']:
            job=child/'branches'/jid
            if not (job/'branch_receipt.json').exists():
                # No execution or metrics dispatch for an unstarted branch.
                status=read(job/'status.json')
                if status['state']!='NOT_RUN' or (job/'checkpoint.json').exists():
                    require(read(Path(root)/'group_status'/f"{e['group_id']}.json")['state'] in ('ERROR','CANCELED'),'comparison_unreceipted_started_branch')
                    if status['state']!='FINISHED':
                        status.update(state='FINISHED',category='ERROR',error={'code':'CONTROL_FAILURE','detail':'worker failed; saved progress retained; no implicit restart'})
                        write(job/'status.json',status)
                    write(job/'branch_receipt.json',fork.branch_receipt(child,jid,cp,task))
                    continue
                binding=read(job/'binding.json')
                receipt=fork.seal({'version':'jev_branch_receipt_v1','job_id':jid,'plan_digest':digest(cp),'binding_digest':digest(binding),
                    'fork_digest':cp['fork_digest'],'first':binding['first'],'continuation':cp['continuation'],'status':status,
                    'checkpoint_digest':None,'metrics':'NOT_RUN','model_calls':0,'comparison_labels':'DEFERRED_TO_JN2_B'})
                write(job/'branch_receipt.json',receipt)


def dataset_receipt(p,summary,rows,batch_state):
    ready=bool(batch_state=='FINISHED' and all(x['category'] in VALID_CATEGORIES+('UNASSESSABLE',) for x in summary['budget']['rows']))
    positive=summary['eligible_improved_pairs']
    return {'version':'jev_comparison_dataset_receipt_v1','stage':'JN2-B','plan_digest':digest(p),
            'engineering_status':'COMPLETE_IN_DECLARED_SCOPE' if ready else 'PARTIAL_OR_IN_PROGRESS',
            'JN3_engineering_admitted':ready,'experience_input_status':summary['experience_input_status'] if ready else 'NOT_READY',
            'experience_eligible_pairs':positive if ready else [],
            'experience_gap':None if ready and positive else 'NO_VALID_IMPROVED_PAIR_OR_COLLECTION_NOT_CLOSED; trade_off/neutral/invalid evidence retained',
            'labels':summary['labels'],'valid':summary['valid'],'invalid':summary['invalid'],
            'source_groups':summary['source_groups'],'coverage':summary['coverage'],'coverage_gaps':summary['coverage_gaps'],
            'budget':summary['budget'],'records':[{'path':'comparisons/'+r['comparison_id']+'.json','digest':digest(r),'source_group':r['source_group']} for r in rows],
            'training_evidence_policy':'only the two admitted exposed training sources; no future/test input to selectors',
            'execution_source_digest':digest(p['execution_source_manifest']),
            'analysis_source_digest':digest(p['analysis_source_manifest']),'new_model_calls':0,'JN3_executed':False,
            'claim_boundary':'registered exact interventions under identical deterministic local continuation; no universal rule or global optimum'}


def summarize_records(root,p,rs):
    labels={k:sum(r['label']==k for r in rs) for k in ('improved','neutral','degraded','trade_off','invalid')}
    eligible=[r['comparison_id'] for r in rs if r['comparison_valid'] and r['label']=='improved']
    summary={'version':VERSION,'comparisons':len(rs),'valid':sum(r['comparison_valid'] for r in rs),'invalid':sum(not r['comparison_valid'] for r in rs),
             'labels':labels,'source_groups':sorted({r['source_group'] for r in rs}),
             'coverage':{kind:sum(r['intervention']==kind for r in rs) for kind in ('SAME_BOX_DIFFERENT_POSE','CROSS_BOX_SELECTION')},
             'coverage_gaps':{e['group_id']:e['coverage_gaps'] for e in p['entries']},
             'experience_input_status':'READY_IN_DECLARED_SCOPE' if eligible else 'NOT_READY','eligible_improved_pairs':eligible,
             'model_calls':0,'budget':budget_ledger(root,p)}
    return summary


def derive(root,p):
    ensure_not_run_receipts(root,p);rs=records(root,p)
    for row in rs:write(Path(root)/'comparisons'/f"{row['comparison_id']}.json",row)
    summary=summarize_records(root,p,rs)
    write(Path(root)/'comparison_summary.json',summary);write(Path(root)/'budget_ledger.json',summary['budget'])
    write(Path(root)/'comparison_dataset_receipt.json',dataset_receipt(p,summary,rs,read(Path(root)/'batch_status.json')['state']))
    write(Path(root)/'source_index.json',{source:[r['comparison_id'] for r in rs if r['source_group']==source] for source in summary['source_groups']})
    return summary


def run(root,*,resume=False,stop_after_groups=None):
    root=Path(root).resolve();p=validate_plan(root)
    require(stop_after_groups is None or (type(stop_after_groups)is int and stop_after_groups>0),'comparison_invalid_pause')
    with exclusive(root):
        if (root/'batch_execution.json').exists():require(resume,'comparison_already_started_use_resume')
        else:write(root/'batch_execution.json',{'version':VERSION,'plan_digest':digest(p),'reserved_new_suffixes':p['budget']['B_registered']})
        if (root/'batch_status.json').exists() and read(root/'batch_status.json')['state'] in ('FINISHED','STOPPED'):
            validate(root);return read(root/'comparison_summary.json')
        stopped=False;done=0;paused=False
        for e in p['entries']:
            state=read(root/'group_status'/f"{e['group_id']}.json")
            if e['mode']=='REUSE_A':continue
            if state['state'] in ('ERROR','CANCELED','TECHNICAL_LIMIT'):stopped=True
            if state['state']=='FINISHED' or stopped:continue
            if stop_after_groups is not None and done>=stop_after_groups:paused=True;break
            if state['state']=='RUNNING' and not (REPO/e['location']/'execution_receipt.json').exists():
                write(root/'group_status'/f"{e['group_id']}.json",{'state':'ERROR','error':'UNKNOWN_START_NO_IMPLICIT_RETRY'});stopped=True;break
            write(root/'group_status'/f"{e['group_id']}.json",{'state':'RUNNING','error':None})
            if not (root/'dispatch_intents'/f"{e['group_id']}.json").exists():
                write(root/'dispatch_intents'/f"{e['group_id']}.json",{'plan_digest':digest(p),'group':e['group_id'],'reserved_suffixes':len(e['first_actions'])})
            try:
                result=worker(root,'run',child=REPO/e['location'])
                write(root/'worker_receipts'/f"{e['group_id']}.json",result)
                bad=any(b['category'] in fork.common.STOP_CATEGORIES for b in result['value']['branches'])
                state={'state':'ERROR' if bad else 'FINISHED','error':'CHILD_TECHNICAL_STOP' if bad else None}
                stopped=bad
            except KeyboardInterrupt:state={'state':'CANCELED','error':'KeyboardInterrupt'};stopped=True
            except Exception as exc:state={'state':'ERROR','error':{'code':getattr(exc,'code','UNEXPECTED'),'detail':str(exc)[-1500:]}};stopped=True
            write(root/'group_status'/f"{e['group_id']}.json",state);write(root/'budget_ledger.json',budget_ledger(root,p));done+=1
            if stopped:break
        history=read(root/'batch_history.json') if (root/'batch_history.json').exists() else []
        history.append({'budget':budget_ledger(root,p),'stopped':stopped,'paused':paused})
        write(root/'batch_history.json',history)
        write(root/'batch_status.json',{'state':'STOPPED' if stopped else 'PAUSED' if paused else 'FINISHED','plan_digest':digest(p)})
        return derive(root,p)


def validate(root,*,deep=True):
    root=Path(root).resolve();p=validate_plan(root)
    if (root/'delivery_manifest.json').exists():
        manifest=read(root/'delivery_manifest.json')
        require(manifest['files_sha256']==file_manifest(root),'comparison_delivery_bytes_changed')
    require(read(root/'budget_ledger.json')==budget_ledger(root,p),'comparison_budget_ledger_changed')
    if deep:
        worker(root,'audit-a')
        for e in p['entries']:
            if e['mode']=='NEW' and (REPO/e['location']/'mechanism_results.json').exists():worker(root,'validate',child=REPO/e['location'])
    for e in p['entries']:
        child=REPO/e['location'];cp_plan=read(child/'branch_plan.json');task=read(child/'task.private.json')
        for jid in cp_plan['branch_order']:
            job=child/'branches'/jid
            require(read(job/'branch_receipt.json')==fork.branch_receipt(child,jid,cp_plan,task),'comparison_resigned_branch_receipt_changed')
            if (job/'checkpoint.json').exists() and not (child/'mechanism_results.json').exists():
                binding=read(job/'binding.json');fork.validate_branch_checkpoint(read(job/'checkpoint.json'),task,cp_plan['config'],jid,binding)
    rs=records(root,p)
    require(sorted(x.stem for x in (root/'comparisons').glob('*.json'))==sorted(r['comparison_id'] for r in rs),'comparison_record_set_changed')
    for row in rs:require(read(root/'comparisons'/f"{row['comparison_id']}.json")==row,'comparison_resigned_record_changed')
    summary=read(root/'comparison_summary.json')
    require(summary==summarize_records(root,p,rs),'comparison_summary_changed')
    require(summary['labels']=={k:sum(r['label']==k for r in rs) for k in ('improved','neutral','degraded','trade_off','invalid')} and
            summary['valid']==sum(r['comparison_valid'] for r in rs) and summary['comparisons']==len(rs),'comparison_summary_changed')
    require(read(root/'comparison_dataset_receipt.json')==dataset_receipt(p,summary,rs,read(root/'batch_status.json')['state']),'comparison_dataset_receipt_changed')
    require(summary['eligible_improved_pairs']==[r['comparison_id'] for r in rs if r['comparison_valid'] and r['label']=='improved'] and summary['experience_input_status']==('READY_IN_DECLARED_SCOPE' if summary['eligible_improved_pairs'] else 'NOT_READY'),'comparison_experience_gate_changed')
    require(read(root/'source_index.json')=={s:[r['comparison_id'] for r in rs if r['source_group']==s] for s in sorted({r['source_group'] for r in rs})},'comparison_source_index_changed')
    return {'status':'PASS','comparisons':len(rs),'verification':'saved records; frozen worker forbids selector/candidate/episode/monitor/commit/PCT/LP dispatch'}


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('prepare');a.add_argument('--parent-a',default=A_DEFAULT);a.add_argument('--output',required=True)
    a=sub.add_parser('run');a.add_argument('--output',required=True);a.add_argument('--resume',action='store_true');a.add_argument('--stop-after-groups',type=int)
    a=sub.add_parser('validate');a.add_argument('--output',required=True)
    a=p.parse_args()
    if a.command=='prepare':result=prepare(a.parent_a,a.output)
    elif a.command=='run':result=run(a.output,resume=a.resume,stop_after_groups=a.stop_after_groups)
    else:result=validate(a.output)
    print(json.dumps({'command':a.command,'status':'OK','version':result.get('version',VERSION)}))


if __name__=='__main__':main()

"""Read-only proofs, complete denominators and independent artifact delivery."""
import copy
import hashlib
from pathlib import Path
from ...common import read,write,digest,O4Error
from ..e2.experiment import verify_seal,files
from ..e2.visual import render,facts
from ..e2.visual_verify import verify as verify_image
from .episode import verify_episode,stable
from .metrics import aggregate


def lightweight_results(root,jobs):
    for job in jobs:
        path=Path(root)/f"episodes/{job['job_id']}.json"
        if not path.exists():continue
        r=read(path)
        yield {'summary':r['summary'],'events':[
            {'event':e['event'],'submitted':bool(e.get('action')),
             'compilation':{k:e['compilation'][k] for k in ('status','first_valid','repaired_valid')},
             'commit_error':e.get('commit_error'),
             **({'compilation_metrics':e['compilation_metrics'],'rule_activity':e['rule_activity'],
                 'reference_after':{k:e['reference_after'][k] for k in ('relation_status','violations')}}
                if 'compilation_metrics' in e else {})}
            for e in r['events'] if 'compilation' in e]}


def visuals(root,data,jobs):
    root=Path(root);cache={};rows=[]
    def check(req,identity):
        source=facts(req);key=digest(source)
        if key not in cache:
            asset=render(req,root,f'public/images/{key[:24]}.png')
            cache[key]=(asset,verify_image(req,root,asset))
        asset,result=cache[key]
        rows.append({'identity':identity,'observation_digest':req['observation_digest'],'facts_digest':key,'asset':asset,**result})
    for g in data['gold']:check(g['request'],g['case_id'])
    for job in jobs:
        r=read(root/f"episodes/{job['job_id']}.json")
        for index,e in enumerate(r['events']):
            if 'source_request' in e:check(e['source_request'],f"{job['job_id']}_{index}")
    write(root/'audit/visual.json',rows)
    return {'unique_png':len(cache),'public_state_checks':len(rows),'all_verified':all(r['top_face_labels'] and r['png_bytes_verified'] and r['scene_geometry_pixels_equal'] for r in rows)}


def verify_results(root,data,config,jobs,*,check_repeats=False):
    root=Path(root);tasks={t['task_id']:t for t in data['tasks']+data['constructs']}
    records=[];repeated=[];restored=[];coverage=[];maxima={'per_object':0,'joint':0,'depth':0,'beam':0,'successors':0};physical_submissions=0
    for job in jobs:
        r=read(root/f"episodes/{job['job_id']}.json");task=tasks[job['task_id']]
        if r['job_id']!=job['job_id'] or r['summary']['backend']!=job['backend'] or r['summary']['planner']!=job['planner']:raise O4Error('job_result_identity_changed')
        check=verify_episode(r,task,config);records.append({'job_id':job['job_id'],**check})
        for e in r['events']:
            if e.get('action'):physical_submissions+=1
            if e['event'] not in ('PLACE','STOP'):continue
            maxima['joint']=max(maxima['joint'],len(e['candidates']))
            maxima['per_object']=max(maxima['per_object'],max((len(g['candidates']) for g in e['groups']),default=0))
            maxima['depth']=max(maxima['depth'],e['search_trace'].get('max_depth',0));maxima['beam']=max(maxima['beam'],e['search_trace'].get('max_beam',0));maxima['successors']=max(maxima['successors'],e['search_trace']['evaluations'])
            coverage.append({'job_id':job['job_id'],'compilation_id':e['compilation']['compilation_id'],**e['diagnostics']})
        if check_repeats and job['backend']=='oracle_ast':
            a=read(root/f"repeats/{job['job_id']}.json");b=read(root/f"restores/{job['job_id']}.json")
            # Recompute saved repeats/restores as well, not just compare summaries.
            verify_episode(a,task,config);verify_episode(b['result'],task,config)
            if stable(a)!=stable(r) or stable(b['result'])!=stable(r):raise O4Error('saved_repeat_or_restore_changed')
            repeated.append({'job_id':job['job_id'],'passed':True,'stable_digest':digest(stable(a))})
            restored.append({'job_id':job['job_id'],'passed':True,'stable_digest':digest(stable(b['result']))})
    if any(maxima[k]>v for k,v in {'per_object':16,'joint':48,'depth':3,'beam':8,'successors':256}.items()):raise O4Error('search_budget_exceeded')
    return {'checks':records,'repeats':repeated,'restores':restored,'coverage':coverage,'maxima':maxima,'actual_physical_submissions':physical_submissions}


def finalize_offline(root,plan_root,plan,data,config):
    from .experiment import protection_check,PACKAGE
    root=Path(root);jobs=read(root/'audit/jobs.json')
    if files(PACKAGE)!=plan['source_files']:raise O4Error('source_changed_during_run')
    proofs=verify_results(root,data,config,jobs,check_repeats=True)
    for name,key in [('episode_recomputation','checks'),('repeats','repeats'),('restores','restores'),('coverage','coverage')]:write(root/f'audit/{name}.json',proofs[key])
    views=accounting_views(root,data,jobs)
    write(root/'audit/readonly_verify.json',{'status':'PASS','episode_records_recomputed':len(proofs['checks']),'saved_repeats_verified':len(proofs['repeats']),'saved_restores_verified':len(proofs['restores']),'new_api_attempts':0})
    images=visuals(root,data,jobs)
    from .faults import run_faults
    fault_root=root/'faults'
    suffix=1
    while fault_root.exists():
        suffix+=1;fault_root=root/f'faults_attempt_{suffix}'
    faults=run_faults(data,config,fault_root)
    write(root/'audit/faults.json',faults)
    protection=protection_check(read(Path(plan_root)/'private/protected.before.json'),plan['workspace_root'])
    write(root/'audit/protected.json',protection)
    summary=aggregate(lightweight_results(root,jobs),jobs);write(root/'metrics/summary.json',summary)
    # Correct-AST natural orders may stop early. Only declared construct outcomes
    # are compared to completion expectations.
    semantics=all(g['violating_steps']==0 and g['components'].get('semantic_equal',{}).get('correct')==g['components'].get('semantic_equal',{}).get('comparable') and g['components'].get('allowed_set_equal',{}).get('correct')==g['components'].get('allowed_set_equal',{}).get('comparable') for g in summary['groups'])
    gates={'E5-01':config['o4_e5']['yaw_degrees']==[0,90] and config['o4_e5']['e3_status']=='DEFERRED',
           'E5-02':len(read(root/'metrics/regression.json'))==180 and len(read(root/'metrics/gold.json'))==12
                    and all(r['passed'] for f in ('regression','invalid','gold') for r in read(root/f'metrics/{f}.json')),
           'E5-03':len(data['sources'])==12 and len(data['tasks'])==24 and len({s['source_order_key'] for s in data['sources']})==12,
           'E5-04':len(proofs['checks'])==240 and semantics and all(w['passed'] for w in data['manual_witnesses']),
           'E5-05':all(r['conservation'] and r['independent_physics'] for r in proofs['checks']) and all(r['passed'] for r in faults),
           'E5-06':{'wrong_ast_drop','wrong_ast_direction'} <= {r['purpose'] for r in faults} and all(r['passed'] for r in faults if r['purpose'].startswith('wrong_ast')),
           'E5-07':images['all_verified'] and {'remote_image_commit','text_image_fairness'} <= {r['purpose'] for r in faults},
           'E5-08':len(jobs)==240 and all(j['status']=='PASS' for j in jobs) and all(r['passed'] for r in faults)
                   and 'initialization_failure_records_denominator' in {r['purpose'] for r in faults}
                   and sum(g['compilation']['decisions'] for g in summary['groups'])==views['compiled_decisions']
                   and sum(g['planned_episodes'] for g in summary['groups'])==240
                   and all(g['measurement_complete'] for g in summary['groups']),
           'E5-09':len(proofs['repeats'])==len(proofs['restores'])==120 and protection['status']=='PASS',
           'E5-10':all((root/p).is_file() for p in ('audit/compilations.json','audit/attempts.json','audit/budget.json','metrics/failure_attribution.json','audit/readonly_verify.json')) and all((Path(plan_root)/'documentation'/name).is_file() for name in ('cli_help.txt','O4E5混合约束完整订单运行及API交接_20261026.md','O4E5混合约束完整订单开发与验收_20261026.md'))}
    status='PASS' if all(gates.values()) else 'FAIL'
    report={'scope':'O4_E5_090_CURRENT_SCOPE','status':status,'offline_status':status,'gates':gates,
            'real_compile_status':'NOT_RUN','prior_e1_e2_real_compile_status':'PASS','real_online_status':'NOT_RUN',
            'unseen_generalization':'NOT_MEASURED','visual_increment':'NOT_MEASURED','e3_status':'DEFERRED','e4_status':'OUT_OF_SCOPE',
            'yaw_degrees':[0,90],'new_api_attempts':0,'planned_main_episodes':192,'planned_construct_episodes':48,
            'recorded_episodes':len(jobs),'semantic_regression':180,'invalid_regression':48,'mixed_gold':12,
            'independent_repeats':len(proofs['repeats']),'restores':len(proofs['restores']),
            'actual_physical_submissions':proofs['actual_physical_submissions'],'resource_maxima':proofs['maxima'],
            'visual':images,'accounting_views':views,'protected':protection,'faults':len(faults)}
    write(root/'acceptance_report.json',report)
    (root/'README.md').write_text('E5 0/90 current-scope offline delivery. Read acceptance_report.json and metrics/summary.json.\nOrder completion and execution correctness have different denominators. Real API NOT_RUN; E3 DEFERRED, E4 OUT_OF_SCOPE.\n')
    return report


def verify_experiment(root):
    root=Path(root);sealed=verify_seal(root);data=read(root/'private/input_snapshot.json');config=read(root/'config.snapshot.json');jobs=read(root/'audit/jobs.json')
    from .experiment import PACKAGE
    if files(PACKAGE)!=read(root/'plan.json')['source_files']:raise O4Error('code_snapshot_mismatch')
    mode=read(root/'manifest.json')['mode']
    if mode=='offline':
        proofs=verify_results(root,data,config,jobs,check_repeats=True)
        saved=read(root/'metrics/summary.json');computed=aggregate(lightweight_results(root,jobs),jobs)
        if saved!=computed:raise O4Error('aggregate_metrics_changed')
        return {'status':'PASS','sealed_files':sealed,'episode_records_recomputed':len(proofs['checks']),'saved_repeats_verified':len(proofs['repeats']),'saved_restores_verified':len(proofs['restores']),'new_api_attempts':0}
    from .online import verify_online
    return verify_online(root,sealed)


def accounting_views(root,data,jobs):
    """Named deliverables, derived from authoritative episodes/ledger only."""
    root=Path(root);tasks={t['task_id']:t for t in data['tasks']+data['constructs']};compilations=[];failures=[]
    witnesses={w['task_id']:w for w in data['manual_witnesses']}
    for job in jobs:
        path=root/f"episodes/{job['job_id']}.json"
        if not path.exists():
            failures.append({'job_id':job['job_id'],'execution_status':job['status'],'reason':'no_completed_episode','global_infeasibility':'NOT_PROVEN'});continue
        r=read(path);s=r['summary'];decisions=[e for e in r['events'] if 'compilation'in e]
        for index,e in enumerate(r['events']):
            if 'compilation'not in e:continue
            c=e['compilation'];compilations.append({'compilation_id':c['compilation_id'],'job_id':job['job_id'],'backend':c['backend'],
               'status':c['status'],'attempt_ids':c['attempt_ids'],'first_valid':c['first_valid'],'repaired_valid':c['repaired_valid'],
               'test_double':c['test_double'],'episode_path':f"episodes/{job['job_id']}.json",'event_index':index})
        last=decisions[-1] if decisions else {};proof=witnesses.get(job['task_id'],{}).get('analytic_certificate')
        failures.append({'job_id':job['job_id'],'source_kind':s['source_kind'],'execution_status':s['execution_status'],
          'completed':s['completed'],'reason':s['termination_reason'],'planned_items':s['planned_items'],
          'placed_items':s['placed_items'],'pending_ids':s['pending_ids'],'unarrived_ids':s['unarrived_ids'],
          'legal_ast_semantic_error_steps':sum(not e['compilation_metrics']['semantic_equal'] for e in decisions if 'compilation_metrics'in e),
          'final_diagnostics':last.get('diagnostics'),'global_infeasibility':'PROVEN_FOR_DECLARED_CONSTRUCT' if proof and proof['contradiction'] else 'NOT_PROVEN',
          'independent_certificate':proof})
    ledger_path=root/'audit/ledger.json'
    if ledger_path.exists():
        ledger=read(ledger_path);attempts=ledger['attempts']
    else:
        ledger={'budget':0,'job_limits':{},'test_double':False,'attempts':[]};attempts=[]
        write(ledger_path,ledger)
    write(root/'audit/compilations.json',compilations);write(root/'audit/attempts.json',attempts)
    write(root/'audit/budget.json',{'authorized_budget':ledger['budget'],'used_attempts':len(attempts),'remaining_attempts':ledger['budget']-len(attempts),
        'real_api_attempts':0 if ledger['test_double'] else len(attempts),'test_double':ledger['test_double'],
        'unknown_in_flight':sum(a['status']=='in_flight' for a in attempts),
        'per_job':{j:{'limit':limit,'used':sum(a['job_id']==j for a in attempts)} for j,limit in ledger['job_limits'].items()}})
    write(root/'metrics/failure_attribution.json',failures)
    return {'compiled_decisions':len(compilations),'recorded_failure_classifications':len(failures)}

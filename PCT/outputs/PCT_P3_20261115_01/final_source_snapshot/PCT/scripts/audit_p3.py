"""Read saved P3 facts and produce independent counters/denominators; no dispatch."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[os.environ.get('PCT_P3_FROZEN_SOURCE',str(ROOT/'PCT/src')),str(ROOT/'semantic_pallet_planner/src')]
import torch
from pct_baseline import p3_runtime as rt
from pct_baseline.contracts import read,digest,sha,require
from pct_baseline.persistence import atomic_new

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--run',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    plan=read(args.run/'plan.json');rows=[];failures=[]
    require(plan['plan_digest']==digest({k:v for k,v in plan.items() if k!='plan_digest'}),'AUDIT_PLAN')
    pre=read(args.run/'pre_execution_identity.json')
    current_differences=[]
    for path,h in pre['source_sha256'].items():
        require(sha(args.run/'source_snapshot'/path)==h,'AUDIT_ARCHIVED_SOURCE_DRIFT:'+path)
        if sha(path)!=h:current_differences.append(path)
    roots=[(job['job_id'],Path(job['output']),'diagnostic') for job in plan['jobs']]
    roots += [(f'training_{i:02d}',args.run/'training'/f'training_{i:02d}','training') for i in range(16)]
    drift_tests=[]
    for jid,root,mode in roots:
        if not (root/'header.json').exists():
            rows.append({'job_id':jid,'mode':mode,'status':'NOT_RUN'});continue
        try:
            header,journal=rt.read_records(root);rt.check_header(header);rt.check_journal_stages(journal)
            cp=journal[-1]['checkpoint'] if journal else None
            if cp:rt.validate_checkpoint(cp,header['task'],header['config'],header['job_id'],header['config']['selector'])
            model=rt.load_bound(header['model_binding']);rt.verify_model_records(root,cp,header['config'],model)
            ep=read(root/'episode.json') if (root/'episode.json').exists() else None
            if ep:
                require(ep['checkpoint']==cp and ep['final_state']==cp['state'] and ep['events']==cp['events'],'AUDIT_EPISODE')
                expected=rt.summarize_episode(header['task'],header['config'],header['config']['selector'],cp['state'],cp['events'],cp['reason'])
                require(ep['summary']==expected,'AUDIT_METRICS')
            ends=[read(p) for p in sorted((root/'sessions').glob('*_end.json'))]
            raw_counts={k:sum(s['counts'][k] for s in ends) for k in ends[0]['counts']} if ends else {}
            counts=dict(raw_counts)
            # Original after_checkpoint hook does not observe intermediate
            # stages. Completed sessions + immutable chain give exact saved
            # stage counts; retain original erroneous zero counters separately.
            require(all(s['status']=='FINISHED' for s in ends),'AUDIT_UNRESOLVED_SESSION')
            counts['monitor_calls']=sum(r['checkpoint']['phase']=='MONITORED' for r in journal)
            counts['commits']=sum(r['checkpoint']['phase']=='COMMITTED' for r in journal)
            counts['candidate_generations']=sum(r['checkpoint']['phase']=='DECISION_READY' for r in journal)
            counts['candidate_actions']=sum(len(r['checkpoint']['pending_event']['bundle']['physical_candidates']) for r in journal if r['checkpoint']['phase']=='DECISION_READY')
            events=cp['events'] if cp else []
            decisions=[e for e in events if e.get('bundle') is not None]
            monitor_events=[e for e in decisions if e.get('monitor') is not None]
            commits=sum(e['event']=='PLACE' for e in events)
            require(counts.get('monitor_calls',0)==len(monitor_events),'AUDIT_MONITOR_CALLS')
            require(counts.get('commits',0)==commits,'AUDIT_COMMIT_CALLS')
            require(counts.get('candidate_generations',0)==len(decisions),'AUDIT_CANDIDATE_GENERATIONS')
            unique={'decisions':len(decisions),'choices':sum(e['route']=='CHOICE_REQUIRED' for e in decisions),
                    'singletons':sum(e['route']=='SINGLETON_BYPASS' for e in decisions),
                    'empty_pools':sum(e['route']=='STOP_NO_PHYSICAL_CANDIDATE' for e in decisions),
                    'candidate_actions':sum(len(e['bundle']['physical_candidates']) for e in decisions),
                    'monitor_events':len(monitor_events),'commits':commits}
            rows.append({'job_id':jid,'mode':mode,'method':header['config']['selector'],'status':'FINISHED' if ep else 'PARTIAL',
                'raw_session_counts':raw_counts,'count_correction_basis':'completed session and immutable journal stage entries; no original receipt rewritten',
                'measured_public_selection_s':sum(e.get('timings',{}).get('selection_s',0.) for e in events),
                'monitor_duration_s':sum(e['monitor']['result']['duration_s'] for e in monitor_events),
                'kernel_calls':sum(e['monitor']['result']['kernel_calls'] for e in monitor_events),
                'placeholder_inference_receipt_zero':'NOT_MEASURED; exclude from latency statistics; use public selection_s',
                'reason':cp['reason'] if cp else None,'saved_fact_validation':'PASS','actual_session_counts':counts,'unique_saved_facts':unique,
                'session_elapsed_s':sum(s['elapsed_s'] for s in ends),'sessions':len(ends),
                'session_recovery':[{'start_phase':s['start_phase'],'status':s['status'], 'counts':s['counts']} for s in ends],
                'candidate_counts_by_decision':[len(e['bundle']['physical_candidates']) for e in decisions],
                'summary':ep['summary'] if ep else None,'saved_bytes':sum(p.stat().st_size for p in root.rglob('*') if p.is_file())})
            # Negative checks on independent header copies, never re-sign originals.
            if model is not None and len(drift_tests)<2:
                bad=copy.deepcopy(header);bad['model_binding']['weights_sha256']='0'*64
                bad['config']['model_identity']=digest(bad['model_binding']);bad['header_digest']=digest({k:v for k,v in bad.items() if k!='header_digest'})
                try:rt.check_header(bad)
                except ValueError as exc:drift_tests.append({'job_id':jid,'weights_drift_rejected':str(exc)})
                else:raise ValueError('AUDIT_MODEL_DRIFT_NOT_REJECTED')
        except Exception as exc:
            failures.append({'job_id':jid,'error':type(exc).__name__+':'+str(exc)})
            rows.append({'job_id':jid,'mode':mode,'status':'AUDIT_FAIL'})
    def totals(mode):
        rs=[r for r in rows if r['mode']==mode and 'actual_session_counts' in r]
        keys=rs[0]['actual_session_counts'] if rs else []
        return {'slots':sum(r['mode']==mode for r in rows),'finished':sum(r.get('status')=='FINISHED' for r in rs),
                'actual_calls':{k:sum(r['actual_session_counts'][k] for r in rs) for k in keys},
                'unique_choices':sum(r['unique_saved_facts']['choices'] for r in rs),
                'unique_singletons':sum(r['unique_saved_facts']['singletons'] for r in rs),
                'session_elapsed_s':sum(r['session_elapsed_s'] for r in rs),
                'saved_bytes':sum(r['saved_bytes'] for r in rs)}
    matrix=totals('diagnostic');training=totals('training')
    updates=[read(p) for p in sorted((args.run/'training').glob('update_*.json'))]
    require(len(updates)<=2,'AUDIT_UPDATE_CAP')
    if matrix.get('actual_calls'):
        require(matrix['actual_calls']['monitor_calls']<=99 and matrix['actual_calls']['policy_choice_forwards']<=66,'AUDIT_MATRIX_CAP')
    if training.get('actual_calls'):require(training['actual_calls']['monitor_calls']<=264,'AUDIT_TRAIN_CAP')
    for update in updates:
        require(update['parameters_changed'] and update['before']!=update['after'] and update['optimizer_rng_roundtrip']=='EXACT','AUDIT_UPDATE')
    count=training.get('actual_calls',{}).get('monitor_calls',0)
    rate=training['session_elapsed_s']/count if count else None
    bytes_per=count and training['saved_bytes']/count
    results={'version':'pct_p3_saved_audit_v1','status':'PASS_SAVED_FACTS' if not failures else 'FAIL',
        'current_source_differences_from_execution':current_differences,'failures':failures,'jobs':rows,'matrix_totals':matrix,'training_totals':training,
        'updates':[{k:u[k] for k in ('update_id','transition_count','choice_count','singleton_count','loss','actor_loss','critic_loss',
            'unclipped_grad_norm','parameters_changed','optimizer_rng_roundtrip','reward_sum','critic_gradient_forwards',
            'policy_gradient_choice_forwards','singleton_critic_gradient_forwards')} for u in updates],
        'identity_negative_tests':drift_tests,'P1C_Q01':'CLOSED_FOR_P3_SESSION_ACCOUNTING; historical event.saved_result_reuses unchanged',
        'resource_estimate':{'basis':'observed training collection only; no claim of formal budget approval; wall includes persistence and verification',
            'seconds_per_monitored_training_action':rate,'bytes_per_monitored_training_action':bytes_per or None,
            '198000_action_collection_seconds_estimate':198000*rate if rate else 'UNKNOWN',
            '198000_action_storage_bytes_estimate':198000*bytes_per if bytes_per else 'UNKNOWN',
            'optimizer_and_gradient_cost':'separately recorded; exclude from collection rate; no linear convergence claim'},
        'scope':'read-only saved-state/selection/layout verification, not reexecution or LP or independent QA'}
    atomic_new(args.output,results)
    print(json.dumps({k:results[k] for k in ('status','failures','matrix_totals','training_totals','updates')},ensure_ascii=False,indent=2))
    require(not failures,'P3_SAVED_AUDIT_FAILURES')

if __name__=='__main__':main()

"""Four bounded saved-prefix continuations, no complete-order replay.

Uses original frozen implementation before the instrumentation correction.
Stops as soon as the saved pending action is appended to history (READY).
"""
import copy
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'PCT/src'),str(ROOT/'semantic_pallet_planner/src')]
import torch
from pct_baseline import p3_runtime as rt
from pct_baseline.contracts import read,digest,require
from pct_baseline.persistence import JobLock,JournalSink,atomic_new,read_records
from semantic_pallet_planner.jev_select.episode import run_episode

class PrefixStop(BaseException):pass

def main():
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    base=Path('PCT/outputs/PCT_P3_20261115_01');run=base/'attempt_02'
    frozen_plan={'version':'pct_p3_prefix_recovery_plan_v1','scope':'necessary model recovery checks, pending action only, stop at next READY; no new full orders or training',
        'cases':[{'source':'diagnostic_pct_geo_b1_0','phase':'DECISION_READY'},
                 {'source':'diagnostic_pct_geo_b1_1','phase':'SELECTED'},
                 {'source':'diagnostic_pct_load_b1_0','phase':'MONITORED'},
                 {'source':'diagnostic_pct_load_b1_1','phase':'COMMITTED'}],
        'caps':{'network_choices':1,'monitor_calls':2,'physical_commits':3},
        'original_matrix_caps_including_probes':{'network_choices':66,'monitors':99}}
    out=base/'prefix_recovery';out.mkdir(exist_ok=False);atomic_new(out/'plan.json',frozen_plan)
    results=[]
    for case in frozen_plan['cases']:
        source=run/'jobs'/case['source'];header,rows=read_records(source)
        # Last successful action minimizes work; DECISION_READY of terminal
        # empty pool is excluded because it would not test a model choice.
        eligible=[i for i,row in enumerate(rows) if row['checkpoint']['phase']==case['phase']
                  and row['checkpoint']['pending_event'] is not None
                  and row['checkpoint']['pending_event']['route']=='CHOICE_REQUIRED']
        require(bool(eligible),'PREFIX_PHASE_UNAVAILABLE')
        index=eligible[-1];prefix=rows[:index+1];cp=prefix[-1]['checkpoint'];root=out/case['phase'];root.mkdir()
        for name in ('journal','records','sessions','decision_rng'):(root/name).mkdir()
        shutil.copyfile(source/'header.json',root/'header.json')
        for i in range(index+1):shutil.copyfile(source/'journal'/f'{i:08d}.json',root/'journal'/f'{i:08d}.json')
        events=cp['events']+[cp['pending_event']]
        for e in events:
            if e.get('selection') is not None:
                p=source/'records'/(e['decision_id']+'.json')
                if p.exists():shutil.copyfile(p,root/'records'/p.name)
        require(not list((root/'decision_rng').iterdir()),'PREFIX_NO_FUTURE_RNG')
        counters={k:0 for k in ('policy_choice_forwards','singleton_critic_forwards','selection_record_reuses')}
        model=rt.load_bound(header['model_binding']);config=header['config'];selector=rt.ModelSelector(config,model,root,counters)
        rt.check_header(header);rt.validate_checkpoint(cp,header['task'],config,header['job_id'],config['selector'])
        rt.verify_model_records(root,cp,config,model)
        before_records={p.name:p.read_bytes() for p in (root/'journal').glob('*.json')}
        calls={'monitor_calls':0,'commits':0,'candidate_generations':0,'saved_selection_reuses':int(case['phase'] in ('SELECTED','MONITORED')),
               'saved_monitor_reuses':int(case['phase']=='MONITORED')}
        with JobLock(root) as lock:
            def cut(saved):
                if saved['phase']=='MONITORED':calls['monitor_calls']+=1
                if saved['phase']=='COMMITTED':calls['commits']+=1
                if saved['phase']=='DECISION_READY':calls['candidate_generations']+=1
                if saved['phase']=='READY':raise PrefixStop()
            sink=JournalSink(root,header,prefix,lock,cut=cut)
            def hook(phase,value):
                if phase=='decision_ready' and case['phase']=='DECISION_READY':selector.bind(value)
                if phase=='before_commit':sink.hook(phase,value)
            try:
                run_episode(header['task'],selector,config,job_id=header['job_id'],method=config['selector'],resume=cp,
                    on_checkpoint=sink,hook=hook,extension_execution={'version':'pct_p3_execution_v1','header_digest':header['header_digest']})
            except PrefixStop:pass
            else:raise ValueError('PREFIX_STOP_NOT_REACHED')
            tail=sink.rows[-1]['checkpoint']
            rt.validate_checkpoint(tail,header['task'],config,header['job_id'],config['selector'])
            rt.verify_model_records(root,tail,config,model)
        for name,value in before_records.items():require((root/'journal'/name).read_bytes()==value,'PREFIX_HISTORY_OVERWRITTEN')
        saved_event=tail['events'][-1];require(saved_event['event']=='PLACE','PREFIX_NOT_COMMITTED')
        if cp['pending_event']['selection'] is not None:require(saved_event['selection']==cp['pending_event']['selection'],'PREFIX_SELECTION_REPLACED')
        if cp['pending_event']['monitor'] is not None:require(saved_event['monitor']==cp['pending_event']['monitor'],'PREFIX_MONITOR_REPLACED')
        require(calls['candidate_generations']==0,'PREFIX_UNEXPECTED_CANDIDATE_GENERATION')
        expected_monitor=int(case['phase'] in ('DECISION_READY','SELECTED'))
        require(calls['monitor_calls']==expected_monitor and calls['commits']==int(case['phase']!='COMMITTED'),'PREFIX_DUPLICATED_WORK')
        require(counters['policy_choice_forwards']==int(case['phase']=='DECISION_READY'),'PREFIX_DUPLICATED_INFERENCE')
        result={'phase':case['phase'],'source_job':case['source'],'prefix_last_sequence':index,
                'status':'PASS_ONE_PENDING_ACTION_ONLY','counts':{**calls,**counters},
                'history_bytes_unchanged':True,'monitor_seal_unchanged':True,
                'tail_phase':tail['phase'],'tail_checkpoint_digest':digest(tail)}
        atomic_new(root/'receipt.json',result);results.append(result)
    atomic_new(out/'results.json',results)
    print(json.dumps(results,ensure_ascii=False,indent=2))

if __name__=='__main__':main()

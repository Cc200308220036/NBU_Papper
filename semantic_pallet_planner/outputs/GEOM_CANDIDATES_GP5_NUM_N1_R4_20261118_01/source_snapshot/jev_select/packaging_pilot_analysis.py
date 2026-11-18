"""Pure saved-record pilot analysis. Matched public states only for behavior."""
from itertools import combinations
from math import prod
from pathlib import Path
from .contracts import digest
from .ledger import read
from .packaging_reanalysis import evaluate,RULE_VERSION


def pairs(root,plan,rows):
    by={(r['task_id'],r['method_id']):r for r in rows};result=[]
    for tid in plan['task_ids']:
        task=read(Path(root)/'jobs'/next(j['job_id'] for j in plan['jobs'] if j['task_id']==tid)/'task.snapshot.json')
        den={'items':len(task['items']),'mass_kg':sum(o['mass_kg'] for o in task['items']),'volume_mm3':sum(prod(o['dimensions_mm'].values()) for o in task['items'])}
        for a,b in combinations(plan['method_ids'],2):
            ra=by.get((tid,a));rb=by.get((tid,b))
            def norm(r):return {'task_digest':digest(task),'data_identity':plan['data_identity'],'denominators':den,'category':r['category'],'stable_complete':r['stable_complete'],
                'placed_items':r['loading']['placed_items'],'placed_volume_ratio':r['loading']['placed_volume_ratio'],'placed_mass_kg':r['loading']['placed_mass_kg'],
                'actual_height_mm':r['actual_height_mm'],'envelope_utilization':r['envelope_utilization']}
            comparison=evaluate(norm(ra),norm(rb),rule_version=RULE_VERSION) if ra and rb else {'comparison_valid':False,'label_v2':'invalid','invalid_reasons':['NOT_RUN_OR_MISSING_METRICS'],'delta':'NOT_RUN'}
            result.append({'task_id':tid,'reference_method':a,'alternative_method':b,'delta_direction':'alternative_minus_reference','rule_version':RULE_VERSION,
                'categories':{a:ra['category'] if ra else 'NOT_RUN_OR_UNKNOWN',b:rb['category'] if rb else 'NOT_RUN_OR_UNKNOWN'},'evaluation':comparison,
                'scope':'two exposed-source pilot trajectories; no causal attribution, significance or unseen generalization'})
    return result


def behaviors(root,plan):
    root=Path(root);groups={};observations=[]
    for j in plan['jobs']:
        path=root/'jobs'/j['job_id']/'checkpoint.json'
        if not path.exists():continue
        cp=read(path);events=cp['events']+([cp['pending_event']] if cp['pending_event'] else [])
        for ev in events:
            if not ev.get('decision_id') or not ev.get('selection') or ev['selection']['status'] not in ('selected','singleton'):continue
            # Exact physical state and exact original candidates. Memory and its
            # private context/config identities do not define the physical match.
            key=(j['task_id'],digest(ev['before']),digest(ev['bundle']['physical_candidates']))
            chosen=next(c for c in ev['bundle']['physical_candidates'] if c['candidate_id']==ev['selection']['selected_candidate_id'])
            row={'job_id':j['job_id'],'method':j['method_id'],'decision_id':ev['decision_id'],
                 'candidate_id':ev['selection']['selected_candidate_id'],'box_id':next(c['pick_item_id'] for c in ev['bundle']['physical_candidates'] if c['candidate_id']==ev['selection']['selected_candidate_id']),
                 'pose':chosen['pose'],'oriented_size_mm':chosen['oriented_size_mm'],'view_nonempty':bool(ev['context']['memory_view']['entries']),
                 'actual_injection':bool(ev['context']['request_body'] and ev['context']['request_body']['state']['memories'] and ev['selection']['network_attempted']),
                 'route':ev['context']['route']}
            groups.setdefault(key,[]).append(row);observations.append(row)
    matches=[]
    for (tid,state,pool),rows in groups.items():
        for a,b in combinations(rows,2):
            if a['method']==b['method']:continue
            matches.append({'task_id':tid,'state_digest':state,'candidate_pool_digest':pool,'reference':a,'alternative':b,
               'same_box':a['box_id']==b['box_id'],'same_exact_action':a['candidate_id']==b['candidate_id'],
               'classification':'SAME_ACTION' if a['candidate_id']==b['candidate_id'] else 'SAME_BOX_DIFFERENT_POSITION' if a['box_id']==b['box_id'] else 'DIFFERENT_BOX',
               'causal_memory_use':'NOT_ESTABLISHED; same-state pilot choice differences only'})
    return {'version':'jev_pilot_behavior_v1','matched_state_comparisons':matches,'all_saved_choices':observations,
            'matching':'exact before-state and original physical candidate list, within same task; never pair divergent trajectories by step index',
            'unmatched_choice_records':sum(not any(r['job_id']==o['job_id'] and r['decision_id']==o['decision_id'] for m in matches for r in (m['reference'],m['alternative'])) for o in observations),
            'extra_model_requests':0,'interpretation':'nonempty injection proves exposure; changed choice does not prove causal use or long-term benefit'}


def recommendation(root,plan):
    root=Path(root);summary=read(root/'summary.json');jobs=read(root/'job_ledger.json')
    paired=read(root/'paired_differences.json') if (root/'paired_differences.json').exists() else []
    memory_pairs=[r for r in paired if r['reference_method']=='jev_no_memory' and r['alternative_method']!='jev_no_memory']
    valid=[r for r in memory_pairs if r['evaluation']['comparison_valid']]
    improvements=[r for r in valid if r['evaluation']['label_v2']=='improved']
    exposure=0;coverage=[]
    for j in plan['jobs']:
        f=root/'jobs'/j['job_id']/'metrics.json'
        if not f.exists() or (f.parent/'technical_failure.json').exists():continue
        m=read(f);coverage.append({'job_id':j['job_id'],'method':j['method_id'],'category':m['category'],
             'view_nonempty':m['memory_metrics']['view_nonempty_count'],'actual_nonempty':m['memory_metrics']['actually_sent_nonempty_count']})
        if m['memory_mode']!='none':exposure+=m['memory_metrics']['actually_sent_nonempty_count']
    complete=len(jobs)==len(plan['jobs']) and all(j['state']=='FINISHED' and j['category'] not in ('NOT_RUN','ERROR','SELECTION_FAILURE','COMMIT_FAILURE','TECHNICAL_LIMIT','CANCELED') for j in jobs) and summary['status']!='ERROR'
    decision='DEFER' if not complete or exposure==0 or not valid else 'PROCEED' if improvements else 'REVISE'
    return {'version':'jev_memory_pilot_recommendation_v1','recommendation':decision,'registered_jobs':len(plan['jobs']),
       'closed_jobs':sum(j['state']=='FINISHED' for j in jobs),'all_registered_engineering_closed':complete,
       'actual_nonempty_memory_requests':exposure,'memory_vs_none_pairs':len(memory_pairs),'valid_memory_vs_none_pairs':len(valid),
       'improved_memory_vs_none_pairs':len(improvements),'coverage':coverage,'rule':plan['recommendation_rule'],
       'reason':plan['recommendation_rule'][decision],'scope':'two exposed development sources, finite exploratory trajectories; no significance, causal use or unseen generalization',
       'research_benefit':'NOT_ESTABLISHED','JN4_execution':'NOT_AUTHORIZED_BY_THIS_RECEIPT',
       'experience_updates':0,'DeepSeek_calls':0,'extra_same_state_model_probes':0}

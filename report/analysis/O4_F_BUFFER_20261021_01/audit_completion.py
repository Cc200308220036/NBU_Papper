"""Independent delivery audit. Run from repository root after F acceptance/replay."""
import sys
sys.path.insert(0,'semantic_pallet_planner/src')
import json
import hashlib
import math
import time
from pathlib import Path
from collections import Counter,defaultdict
from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate
from semantic_pallet_planner.o4.evaluator import reference_state

ROOT=Path('semantic_pallet_planner/outputs/EXP_O4_F_BUFFER_20261021_01')
OUT=Path('report/analysis/O4_F_BUFFER_20261021_01')
def read(p):return json.loads(p.read_text())
def records(p):return [json.loads(l) for l in p.read_text().splitlines() if l]
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(v):return hashlib.sha256(canonical(v).encode()).hexdigest()
def stable(v):
    if isinstance(v,dict):return {k:stable(x) for k,x in v.items() if k not in ('elapsed_seconds','planning_seconds')}
    if isinstance(v,list):return [stable(x) for x in v]
    return v

def main():
    inputs=read(ROOT/'private/input_snapshot.json');rows=read(ROOT/'metrics/per_episode.json');gold=read(ROOT/'cases/gold.json')
    tasks={t['task_id']:t for t in inputs['tasks']};constructs=read(ROOT/'cases/constructs.json');diags=read(ROOT/'cases/diagnostics.json')
    repeats={(r['task_id'],r['method'],r['backend']):r for r in read(ROOT/'audit/repeat_resume.json')}
    failures=[];counts=Counter();runs={};metrics_checks=0;physics_checks=0;reference_checks=0;node_attempts=0
    compatibility=[];selected=[]
    for row in rows:
        key=(row['task_id'],row['method'],row['backend']);task=tasks[row['task_id']];scenario=inputs['scenarios'][task['scenario_id']]
        events=records(ROOT/'episodes'/f"{row['method']}__{row['backend']}"/row['task_id']/'events.jsonl');runs[key]=(row,events)
        counts[(row['method'],row['backend'])]+=1
        arrivals=[];placed=[];pending=[];waits=receives=eos=nonhead=0;after_receive=[];after_place=[];maxpending=0
        for index,e in enumerate(events):
            before=e['before_state'];after=e['after_state'];before_ids=[p['item']['item_id'] for p in sorted(before['pending_items'],key=lambda p:p['arrival_index'])]
            if index and events[index-1]['after_state']!=before:failures.append('event_chain')
            pending=[p['item']['item_id'] for p in after['pending_items']]
            pids=[p['item_id'] for p in after['placed_items']]
            if set(arrivals)!=set(before['arrived_ids']):failures.append('arrival_prefix')
            if e['kind']=='WAIT_NEXT':
                waits+=1
                if before['end_of_stream'] or len(before_ids)>=before['buffer_capacity'] or before['placed_items']!=after['placed_items']:failures.append('wait_semantics')
                if e['received_id'] is not None:arrivals.append(e['received_id']);receives+=1;after_receive.append(len(pending))
                eos+=int(e['received_eos'])
            if e['kind']=='PLACE':
                pick=e['action']['pick_item_id'];placed.append(pick);nonhead+=pick!=before_ids[0];after_place.append(len(pending));physics_checks+=1
                raw=e['chosen_candidate']['raw'];case={'container':scenario['container'],'placed_items':before['placed_items'],'available_items':[p['item'] for p in before['pending_items']]}
                if check_candidate(case,{'container':scenario['container']},raw):failures.append('physical_commit')
                if raw['pose']!=e['chosen_candidate']['pose'] or raw['pick_item_id']!=pick:failures.append('mapping_commit')
                reference=reference_state(e['after_public_state']['observation']['placed_objects'],task['reference_policy']);reference_checks+=1
                if reference['violations']:failures.append('reference_business')
                if reference!=e['reference_after']:failures.append('reference_trace')
                softgroup=next(g for g in e['root_pools'] if g['pick_item_id']==pick)
                if e['chosen_candidate']['candidate_id'] not in {c['candidate_id'] for c in softgroup['eligible']}:failures.append('soft_eligible')
            if len(set(pids+pending))!=len(pids+pending) or set(pids+pending)!=set(arrivals) or len(pending)>after['buffer_capacity']:failures.append('conservation')
            if after['arrival_count']!=len(arrivals) or after['placed_count']!=len(placed):failures.append('accounting')
            if arrivals!=scenario['arrival_order'][:len(arrivals)]:failures.append('real_stream')
            maxpending=max(maxpending,len(pending))
            for group in e.get('root_pools',[]):
                if len(group['joint'])>16:failures.append('per_item_top_k')
            if len(e.get('public_candidates',[]))>48:failures.append('joint_top_k')
            search=e.get('search_trace')
            if search:
                total=sum(len(n['audit']['attempts']) for n in search['nodes']);node_attempts+=total
                if total!=search['evaluations'] or total>256 or search['max_depth']>3 or search['max_beam']>8:failures.append('bounded_search')
                for n in search['nodes']:
                    if len(n['audit']['attempts'])!=n['audit']['evaluations']:failures.append('attempt_count')
                    if any(g['raw_count']>16 for g in n['audit']['generation']):failures.append('simulation_top_k')
                if search['leaf_remaining_uniformly_skipped'] and not search['search_truncated']:failures.append('unknown_leaf_scoring')
        volumes={b['item_id']:math.prod(b['dimensions_mm'].values()) for b in scenario['items']};indices={i:j for j,i in enumerate(scenario['arrival_order'])}
        expected={'planned_items':len(scenario['arrival_order']),'placed_items':len(placed),'placed_sequence':placed,'arrived_ids':arrivals,
                  'arrival_count':len(arrivals),'wait_requests':waits,'successful_receives':receives,'eos_events':eos,'place_events':len(placed),
                  'pending_ids':[p['item']['item_id'] for p in sorted(events[-1]['after_state']['pending_items'],key=lambda p:p['arrival_index'])],
                  'not_arrived_ids':scenario['arrival_order'][len(arrivals):],'max_pending':maxpending,
                  'mean_pending_after_receive':sum(after_receive)/len(after_receive) if after_receive else None,
                  'mean_pending_after_place':sum(after_place)/len(after_place) if after_place else None,
                  'non_head_commits':nonhead,'non_head_fraction':nonhead/len(placed) if placed else 0.,
                  'inversions':sum(indices[a]>indices[b] for i,a in enumerate(placed) for b in placed[i+1:]),
                  'placed_item_ratio':len(placed)/len(scenario['arrival_order']),
                  'placed_volume_ratio':sum(volumes[i] for i in placed)/sum(volumes.values()),
                  'completed':len(placed)==len(scenario['arrival_order']),'termination_reason':events[-1]['status']}
        for k,v in expected.items():
            metrics_checks+=1
            if row[k]!=v:failures.append('metric:'+k)
        r=repeats[key];h=sha(stable({'row':row,'events':events}))
        if any(r[k]!=h for k in ('original_digest','repeat_digest','resume_digest')) or not r['repeat_passed'] or not r['resume_passed']:failures.append('repeat_resume')
    for tid in tasks:
        l,le=runs[(tid,'buffer_search','oracle_ast')];r,re=runs[(tid,'buffer_search','public_parser')]
        if stable(le)!=stable(re):failures.append('parser_oracle_trajectory')
        def sequence(e):return [(x['action']['pick_item_id'],x['chosen_candidate']['pose']) for x in e if x['kind']=='PLACE']
        single=runs[(tid,'single_greedy','oracle_ast')][1];fifo=runs[(tid,'buffer_fifo','oracle_ast')][1]
        legacy=records(Path(inputs['c_path'])/'episodes/oracle_ast'/tid/'steps.jsonl')
        legacy_sequence=[(e['candidate_mapping'][e['committed_label']]['pick_item_id'],e['candidate_mapping'][e['committed_label']]['pose']) for e in legacy if e['committed_label']]
        compatibility.append({'task_id':tid,'single_c':sequence(single)==legacy_sequence,'fifo_single':sequence(fifo)==sequence(single)})
    if not all(c['single_c'] and c['fifo_single'] for c in compatibility):failures.append('C_FIFO_equivalence')
    expected_keys={(m,b) for m,b in [('single_greedy','oracle_ast'),('buffer_fifo','oracle_ast'),('buffer_heuristic','oracle_ast'),('buffer_search','oracle_ast'),('buffer_search','public_parser')]}
    if set(counts)!=expected_keys or any(v!=72 for v in counts.values()):failures.append('matrix_360')
    if len({t['source_order_key'] for t in tasks.values()})!=12 or len(tasks)!=72:failures.append('source_denominator')
    opportunities=[c for c in constructs if c['decision_opportunity']]
    if len(gold)!=24 or not all(g['actual']==g['expected'] and g['passed'] for g in gold):failures.append('gold')
    if len(constructs)!=12 or not all(c['passed'] and c['independent']['max_placed_count']==c['expected_search_count'] for c in constructs):failures.append('constructs')
    if len(opportunities)!=4 or len({c['family'] for c in opportunities})!=4 or not all(c['reordered'] for c in opportunities) or sum(c['progress_gain']>0 for c in opportunities)<2:failures.append('opportunity_quota')
    if sum(c['expected_no_progress_gain'] for c in constructs)<4:failures.append('negative_quota')
    if not all(d['passed'] for d in diags):failures.append('diagnostics')
    tamper=read(ROOT/'audit/tamper.json')
    if {r['kind'] for r in tamper}!={'capacity','EOS','pending_set','simulated_commit'} or not all(r['detected'] and r['reasons']!=['delivery_hash'] for r in tamper):failures.append('semantic_tamper')
    network=read(ROOT/'audit/network.json')
    if network!={'network_attempts':0,'remote_calls':0}:failures.append('network')
    protection=read(ROOT/'audit/protected.before.json');changed=[]
    for name,h in protection.items():
        with Path(name).open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
        if actual!=h:changed.append(name)
    if changed:failures.append('legacy_protection')
    import xml.etree.ElementTree as ET
    test_counts={}
    for name in ('pytest.xml','binding_pytest.xml'):
        suites=list(ET.parse(OUT/name).getroot().iter('testsuite'))
        tests=sum(int(v.get('tests',0)) for v in suites);failed=sum(int(v.get('failures',0))+int(v.get('errors',0)) for v in suites)
        test_counts[name]={'tests':tests,'failed':failed}
        if failed or tests<(344 if name=='pytest.xml' else 1):failures.append('pytest')
    if read(OUT/'semantic_metrics.json')['status']!='PASS':failures.append('chapter8_semantics')
    for filename in ('legacy_ab_snapshot_replay.json','legacy_c_snapshot_replay.json'):
        if read(OUT/filename)['status']!='PASS':failures.append('legacy_replay')
    while not (OUT/'full_rerun_replay.json').exists():time.sleep(2)
    acceptance=read(ROOT/'buffer_acceptance.json')
    if acceptance['status']!='PASS' or not all(acceptance['criteria'].values()):failures.append('acceptance')
    replay=read(OUT/'full_rerun_replay.json')
    if replay['status']!='PASS' or not replay['full_planner_rerun'] or replay['episodes_checked']!=360:failures.append('full_replay')
    result={'status':'PASS' if not failures else 'FAIL','failures':sorted(set(failures)),
            'episodes':len(rows),'source_orders':12,'primary_fresh_episodes':360,'reused_episodes':0,
            'repeat_verified':len(repeats),'resume_verified':len(repeats),'event_checks':sum(len(v[1]) for v in runs.values()),
            'independent_physical_checks':physics_checks,'independent_reference_commit_checks':reference_checks,
            'independent_metric_checks':metrics_checks,'counted_successor_attempts':node_attempts,
            'gold_cases':len(gold),'construct_cases':len(constructs),'opportunity_cases':len(opportunities),
            'negative_cases':sum(c['expected_no_progress_gain'] for c in constructs),'protected_files':len(protection),
            'changed_files':changed,'tests':test_counts,'C_FIFO_compatibility':compatibility,'network':network}
    (OUT/'completion_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='C_FIFO_compatibility'},ensure_ascii=False))
    if failures:raise SystemExit(1)

if __name__=='__main__':main()

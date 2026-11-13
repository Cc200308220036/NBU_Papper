"""Independent saved-fact review. Standard library only; no project imports/dispatch.
Linux paths locate archived bytes only; runtime identity is never substituted.
Writes only this QA package's static_checks.json.
"""
import base64
import collections
import hashlib
import json
import math
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
BASE = ROOT / 'semantic_pallet_planner/outputs'
C2 = BASE / 'JEV_JM1_C2_REAL_SUFFIXES_20261113_01'
C1 = BASE / 'JEV_JM1_C1_REAL_BASELINES_20261112_01'
B2 = BASE / 'JEV_JM1_B2_FREEZE_CLOSURE_20261112_01'

def path(p):
    p = str(p)
    prefix = '/home/cyw/NBU_Papper/'
    return ROOT / p[len(prefix):] if p.startswith(prefix) else ROOT / p

def read(p):
    return json.loads(Path(p).read_text())

def digest(v):
    return hashlib.sha256(json.dumps(v, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def seal(v):
    assert v['record_digest'] == digest({k:x for k,x in v.items() if k != 'record_digest'})

def ref(v):
    p = path(v['path'])
    assert hashlib.sha256(p.read_bytes()).hexdigest() == v['sha256'], str(p)
    return read(p)

def close(a,b):
    assert math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-9), (a,b)

def sign(v,t=1e-9):
    return 0 if abs(v)<=t else 1 if v>0 else -1

def pareto(values):
    v = [x for x in values if x]
    return 'neutral' if not v else 'trade_off' if min(v)<0<max(v) else 'improved' if max(v)>0 else 'degraded'

manifests = {}; navigation_blobs=[]
for p in [C2,C1,B2,BASE/'JEV_JM_C1_REAL_QA_20261113_01']:
    m = read(p/'delivery_manifest.json')
    for r in m['files']:
        raw = path(r['path']).read_bytes()
        if r['path']=='docs/03_阶段产出分析/Jev/README.md' and hashlib.sha256(raw).hexdigest()!=r['sha256']:
            assert p.name=='JEV_JM_C1_REAL_QA_20261113_01'
            raw=subprocess.check_output(['git','show','b986eb4b:'+r['path']],cwd=ROOT)
            navigation_blobs.append(dict(path=r['path'],commit='b986eb4b',policy='Original declared navigation policy; verify archived Git blob, no manifest rewrite'))
        assert len(raw)==r['bytes'] and hashlib.sha256(raw).hexdigest()==r['sha256'],r['path']
    manifests[p.name] = len(m['files'])
pkg = ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
actual = {p.relative_to(pkg).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
    for p in pkg.rglob('*') if p.is_file() and p.suffix in ('.py','.json')
    and not {'tests','__pycache__'}.intersection(p.relative_to(pkg).parts)}
assert actual == read(B2/'source_manifest.json') and len(actual)==505
freeze = read(B2/'formal_freeze.json')
assert freeze['receipt_digest']==digest({k:v for k,v in freeze.items() if k!='receipt_digest'})
assert freeze['receipt_digest']=='255afe2a80736838105c759a46597aa8853bdba736b7795672a491b86bbbcce1'
plan = read(C1/'fork_plan.json'); jobs = {j['job_id']:j for j in plan['jobs']}
auth = read(C2/'authorization_receipt.json')
assert auth['authority']=='USER_EXPLICIT_CURRENT_TURN' and auth['suffix_send_upper']==242
assert (auth['points'],auth['initial_jobs'],auth['repeat_jobs'],auth['initial_send_upper'],auth['repeat_send_upper'])==(5,10,8,130,112)
assert not auth['historical_C1_authorization_reused']
order = read(C2/'execution_order.json')['jobs']
assert [j['job_id'] for j in order]==[j['job_id'] for slot in ('r0','r1') for j in plan['jobs'] if j['repeat_slot']==slot]
assert len({j['storage_root'] for j in order})==len({j['allocation_id'] for j in order})==18
rows_by_id = {r['job_id']:r for r in read(C2/'branch_ledger.json')['jobs']}
assert set(rows_by_id)==set(jobs)=={j['job_id'] for j in auth['execution_bindings']}
summary = read(C2/'full_denominators.json'); total = collections.Counter(); journal_count=0
job_checks=[]; metrics={}; first_events={}
allowed = {'READY':{'READY','DECISION_READY','TERMINATED'},'DECISION_READY':{'DECISION_READY','SELECTED','TERMINATED'},'SELECTED':{'MONITORED','TERMINATED'},'MONITORED':{'COMMITTED','TERMINATED'},'COMMITTED':{'READY','TERMINATED'},'TERMINATED':{'TERMINATED'}}
for jid,j in jobs.items():
    r = rows_by_id[jid]; ex = ref(j['execution_ref']); seal(ex)
    assert ref(r['execution_ref'])==ex and r['execution_digest']==digest(ex)
    assert all(r[k]==j[k]==ex[k] for k in ('job_id','storage_root','allocation_id','max_sends','repeat_slot','forced_label'))
    assert ex['config']['memory_mode']=='none' and ex['config']['max_retries']==0
    allocation = digest(dict(job_id=jid.rsplit('_',1)[0],repeat_slot=ex['repeat_slot'],task=digest(ex['task']),start=ex['start'],forced_label=ex['forced_label'],root=ex['storage_root']))
    assert allocation==ex['allocation_id'] and jid.endswith(allocation[:16])
    parent_a=ref(ex['start']['activation_ref']); parent_cp=ref(ex['start']['checkpoint_ref'])['checkpoint']
    parent=next(e for e in parent_cp['events'] if e.get('decision_id')==ex['start']['decision_id'])
    assert ex['task']==parent_a['execution']['task'] and ex['config']==parent_a['execution']['config']
    root=path(ex['storage_root']); a=read(root/'activation.json'); seal(a)
    assert a['execution']==ex==read(root/'ledger/execution.json')
    permit=ref(a['send_permit_ref'])
    assert permit==read(C2/'permits'/(jid+'.json'))==dict(version='jev_jm_v13_send_permit_v1',execution_digest=digest(ex),allocation_id=allocation,max_sends=ex['max_sends'],authorized=True)
    cp=a['initial_checkpoint'];seal(cp);initial=cp
    assert cp['phase']=='SELECTED' and cp['state']==parent['before'] and cp['events']==[]
    forced=cp['pending_event'];assert forced['bundle']==parent['bundle']
    assert forced['selection']['source']=='FORCED_FROM_FROZEN_POOL' and forced['selection']['model_call_count']==0
    assert forced['selection']['selected_candidate_id']==j['candidate_id'] and forced['selection']['selected_display_id']==ex['forced_label']
    assert parent['context']['display_mapping'][ex['forced_label']]['candidate_id']==j['candidate_id']
    assert next(c for c in parent['bundle']['selectable_candidates'] if c['candidate_id']==j['candidate_id'])==j['frozen_candidate']
    previous=digest(a); phases=[]
    for n,p in enumerate(sorted((root/'stages').glob('*.json')),1):
        row=read(p);seal(row);nxt=row['checkpoint'];seal(nxt)
        assert row['sequence']==n and p.name==f'{n:06d}.json' and row['previous_digest']==previous and row['execution_digest']==digest(ex)
        assert nxt['phase'] in allowed[cp['phase']] and nxt['events'][:len(cp['events'])]==cp['events']
        phases.append(nxt['phase']);cp=nxt;previous=digest(row);journal_count+=1
    assert read(root/'checkpoint_head.json')==dict(sequence=len(phases),digest=previous)
    ep=read(root/'episode.json'); assert ep['checkpoint']==cp and ep['final_state']==cp['state'] and ep['events']==cp['events']
    assert cp['phase']=='TERMINATED' and cp['reason']=='STOP_NO_PHYSICAL_CANDIDATE' and cp['pending_event'] is None
    assert cp['task_digest']==digest(ex['task']) and cp['config_digest']==digest(ex['config']) and cp['runtime_identity']==ex['config']['runtime_identity']
    requests=read(root/'ledger/requests.json')['requests']; by_decision={q['decision_id']:q for q in requests};assert len(by_decision)==len(requests)
    state=initial['state'];new_commits=0;forced_count=0;statuses=collections.Counter();kernel=0
    for e in cp['events']:
        assert e['before']==state
        if e.get('selection'):
            sel=e['selection'];candidate=next(c for c in e['bundle']['selectable_candidates'] if c['candidate_id']==sel['selected_candidate_id'])
            assert e['context']['model_state']['memories']==[]
            assert e['context']['display_mapping'][sel['selected_display_id']]['candidate_id']==sel['selected_candidate_id']
            if sel['source']=='FORCED_FROM_FROZEN_POOL':
                forced_count+=1;assert sel==forced['selection'] and e['bundle']==forced['bundle']
            else:
                q=by_decision[e['decision_id']];ctx=read(root/'ledger/contexts'/(e['decision_id']+'.json'))
                assert ctx==e['context'] and ctx['request_body']['state']['memories']==[] and sel==q['selection']
                assert q['state']=='SELECTION_SAVED' and q['send_started'] and q['origin']=='jev' and q['job_id']==jid
                assert [h['state'] for h in q['history']]==['INTENT','SENDING','RESPONSE_SAVED','SELECTION_SAVED']
                tr=q['transport'];raw=base64.b64decode(tr['raw_body_b64'],validate=True)
                assert hashlib.sha256(raw).hexdigest()==tr['raw_sha256']==sel['raw_response_digest']
                assert digest(tr)==q['transport_digest'] and digest(sel)==q['selection_digest']
                assert tr['network_attempted'] and tr['http_status']==200 and sel['requested_model']==sel['served_model']=='jev-1.14.0'
                response=json.loads(raw);assert response['usage']==sel['usage'] and response['answers']['next_action']['choice']==sel['selected_display_id']
                total['input_tokens']+=sel['usage']['input_tokens'];total['output_tokens']+=sel['usage']['output_tokens']
                reservation=read(root/'ledger/reservations'/(e['decision_id']+'.json'))
                assert reservation['execution_digest']==digest(ex) and reservation['allocation_id']==allocation
            mon=e['monitor'];assert mon['status']==mon['result']['status']=='STABLE' and mon['attempted']
            assert mon['result_digest']==digest(mon['result']) and mon['credential_digest']==digest({k:v for k,v in mon.items() if k!='credential_digest'})
            bind=mon['binding']
            for k,value in [('action',e['proposed_action']),('bundle',e['bundle']),('state',e['before']),('candidate',candidate),('selection',sel),('context',e['context'])]:assert bind[k+'_digest']==digest(value)
            assert bind['runtime_identity']==ex['config']['runtime_identity'] and mon['result']['algorithm_identity']==ex['config']['stability_monitor']['algorithm_identity']
            assert e['event']=='PLACE' and e['action']==e['proposed_action'] and e['after']['placed_count']==e['before']['placed_count']+1
            new=next(x for x in e['after']['placed_items'] if x['item_id']==candidate['pick_item_id'])
            assert new['pose']==candidate['pose'] and new['oriented_size_mm']==candidate['oriented_size_mm']
            assert new['item_id'] not in [x['item']['item_id'] for x in e['after']['pending_items']]
            statuses[mon['status']]+=1;kernel+=mon['result']['kernel_calls'];new_commits+=1
        elif e.get('context'):
            assert e['event']=='STOP' and not e['bundle']['selectable_candidates'] and e['before']==e['after'] and e['monitor'] is None
        state=e['after']
    assert state==cp['state'] and forced_count==1 and new_commits==len(requests)+1
    assert phases.count('MONITORED')==phases.count('COMMITTED')==new_commits
    assert phases.count('SELECTED')==len(requests)  # forced selection was saved in activation
    placed=cp['state']['placed_items'];task=ex['task'];den=dict(items=len(task['items']),mass_kg=sum(x['mass_kg'] for x in task['items']),volume_mm3=sum(math.prod(x['dimensions_mm'].values()) for x in task['items']))
    assert len({x['item_id'] for x in placed})==len(placed)==state['placed_count']
    volume=sum(math.prod(x['oriented_size_mm']) for x in placed);mass=sum(x['mass_kg'] for x in placed)
    height=max(x['pose']['z_base_mm']+x['oriented_size_mm'][2] for x in placed)
    area=state['container']['length_mm']*state['container']['width_mm'];m=r['metrics'];metrics[jid]=m
    for k,v in den.items():close(m['denominators'][k],v)
    assert m['task_digest']==digest(task) and m['category']=='EMPTY_POOL' and not m['stable_complete']
    for k,v in dict(placed_items=len(placed),placed_item_ratio=len(placed)/den['items'],placed_volume_mm3=volume,placed_volume_ratio=volume/den['volume_mm3'],placed_mass_kg=mass,placed_mass_ratio=mass/den['mass_kg'],actual_height_mm=height,envelope_utilization=volume/(area*height),fixed_container_utilization=volume/(area*state['container']['max_height_mm'])).items():close(m[k],v)
    assert m['monitor_statuses']==dict(statuses) and m['kernel_calls']==kernel
    assert m['forced_actions']==1 and m['commits']==new_commits and m['requests']==len(requests)<=ex['max_sends']
    assert r['send_interval']==[len(requests)]*2 and r['technical_valid'] and r['status']=='TERMINATED'
    receipt=ref(r['receipt_ref']);assert receipt['counts']==read(root/'counts.json') and receipt['technical_valid']
    assert receipt['counts']['requests']==len(requests) and receipt['counts']['commits']==new_commits
    assert m['model_cost_usd']=='UNKNOWN'
    lat=[q['transport']['latency_s'] for q in requests]
    close(m['selection_latency_s_total'],sum(lat));close(m['selection_latency_s_mean'],sum(lat)/len(lat))
    assert m['transport_latency_samples_s']==lat
    for key,values in m['stage_latency_samples_s'].items():
        expected=[e['timings'][key] for e in cp['events'] if type(e.get('timings',{}).get(key)) in (int,float)]
        assert values==expected
        if values:close(m['saved_event_'+key+'_total'],sum(values))
        else:assert m['saved_event_'+key+'_total']=='NOT_RECORDED'
    for k in ['requests','commits','forced_actions','singleton_actions','kernel_calls','network_attempted','unknown_sends','failed_requests','usage_records','missing_usage_records','monitor_unassessable','monitor_errors']:total[k]+=m[k]
    first_events[jid]=initial['pending_event']
    job_checks.append(dict(job_id=jid,requests=len(requests),new_commits=new_commits,final_placed=len(placed),journal_rows=len(phases),reason=cp['reason']))
assert dict(total)==summary['totals'] and total['requests']==57 and journal_count==450
assert total['input_tokens']==683410 and total['output_tokens']==19932 and total['commits']==75
labels=collections.Counter();point_pairs=collections.defaultdict(list)
for f in sorted((C2/'comparisons').glob('*.json')):
    c=read(f);ja=c['reference_job'];jb=c['alternative_job'];a=metrics[ja];b=metrics[jb]
    ea=ref(jobs[ja]['execution_ref']);eb=ref(jobs[jb]['execution_ref'])
    assert ea['start']==eb['start'] and ea['config']==eb['config'] and ea['task']==eb['task']
    assert first_events[ja]['before']==first_events[jb]['before'] and first_events[ja]['bundle']==first_events[jb]['bundle']
    assert jobs[ja]['branch_kind']=='ORIGINAL_ACTION_REFERENCE' and jobs[jb]['branch_kind']!='ORIGINAL_ACTION_REFERENCE'
    delta={k:b[k]-a[k] for k in ('placed_volume_ratio','placed_items','placed_mass_kg','actual_height_mm','envelope_utilization')}
    ev=c['evaluation'];assert ev['comparison_valid']
    for k,v in delta.items():close(ev['delta'][k],v)
    if a['stable_complete']!=b['stable_complete']:label='improved' if b['stable_complete'] else 'degraded';level='STABLE_COMPLETION'
    elif sign(delta['placed_volume_ratio']):label='improved' if delta['placed_volume_ratio']>0 else 'degraded';level='LOADED_VOLUME'
    else:
        label=pareto([sign(delta['placed_items'],0),sign(delta['placed_mass_kg'])]);level='COUNT_MASS'
        if label=='neutral':label=pareto([-sign(delta['actual_height_mm'],1e-6),sign(delta['envelope_utilization'])]);level='COMPACTNESS'
    assert ev['label_v2']==label and ev['decisive_level']==level
    for k,v in delta.items():close(c['all_numeric_metric_deltas'][k],v)
    for k,av in a.items():
        bv=b[k]
        if type(av) in (int,float) and type(bv) in (int,float):close(c['all_numeric_metric_deltas'][k],bv-av)
        elif type(av) is bool and type(bv) is bool:assert c['all_numeric_metric_deltas'][k]==int(bv)-int(av)
        else:assert c['all_numeric_metric_deltas'][k]=='NA_NONNUMERIC' and c['non_numeric_metric_changes'][k]==dict(reference=av,alternative=bv)
    assert not c['baseline_whole_trajectory_used_as_benefit_reference'] and not c['technical_invalid_ranked']
    labels[label]+=1;point_pairs[c['point_id']].append(c)
assert dict(labels)=={k:v for k,v in summary['pair_labels'].items() if v}==dict(improved=4,degraded=3,neutral=2)
evidence=read(C2/'evidence_levels_and_conflicts.json')
for p in evidence['points']:
    cs=point_pairs[p['point_id']];conflicts=[]
    if len(cs)==2:
        for k,tol in [('placed_volume_ratio',1e-9),('placed_items',0),('placed_mass_kg',1e-9),('actual_height_mm',1e-6),('envelope_utilization',1e-9)]:
            x,y=[c['evaluation']['delta'][k] for c in cs]
            if abs(x)>tol and abs(y)>tol and x*y<0:conflicts.append(k)
    conflict=len({c['evaluation']['label_v2'] for c in cs})>1 or bool(conflicts)
    assert p['repeat_conflict']==conflict and p['opposing_metric_directions']==conflicts
    assert p['evidence_grade']==('CONFLICTING_LOCAL_OBSERVATIONS' if conflict else 'REPLICATED_LOCAL_OBSERVATION' if len(cs)==2 else 'PROVISIONAL_CASE')
for family in evidence['families']:
    assert family['covered_starts']==1 and family['cross_start_support']==family['cross_source_support']==0
    assert family['executable_admission']=='NOT_GRANTED'
assert read(C2/'handoff.json')['JM2_authorized']==0
support=read(C2/'source_and_start_support.json')
for group in support['sources']:
    ps=[p for p in evidence['points'] if p['source_component']==group['component']]
    assert group['selected_starts']==len(ps) and group['registered_pairs']==sum(p['registered_pairs'] for p in ps)
    assert group['labels']==dict(collections.Counter(x for p in ps for x in p['labels'])) and group['independent_unseen_sources']==0
assert len(evidence['points'])==5 and len(point_pairs)==5 and sum(labels.values())==9
assert not subprocess.check_output(['git','diff','b986eb4b','HEAD','--','semantic_pallet_planner/src','semantic_pallet_planner/tests'],cwd=ROOT)
result=dict(version='jm_c2_independent_saved_review_v1',status='PASS',head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),manifest_counts=manifests,navigation_git_blobs=navigation_blobs,source_files=505,journal_rows=journal_count,jobs=job_checks,pairs=9,pair_labels=dict(labels),totals=dict(total),coverage='PARTIAL_PRESERVED',authorization='ARCHIVED_USER_QUOTE_AND_PERMITS_NOT_INDEPENDENT_EXTERNAL_AUTHENTICATION',original_validator='NOT_RUN_MISSING_DEPENDENCIES_AND_LINUX_ROOT',scope='Standard-library saved seals, references, requests, monitor bindings, exact saved placements, metrics and independent v2 hierarchy; no physical feasibility/LP recalculation or full production validator.',current_model_calls=0,current_orders=0,current_LP=0)
(OUT/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))

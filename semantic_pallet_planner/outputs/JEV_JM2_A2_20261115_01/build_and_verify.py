"""Offline A2 delivery builder/verifier. Only saved JSON; guarded before imports."""
import ast,copy,hashlib,importlib.util,json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'semantic_pallet_planner/src'),str(ROOT/'semantic_pallet_planner/tests/unit')]
import test_packaging_scenario_features as guards
from semantic_pallet_planner.jev_select import packaging_t_projection as m
from semantic_pallet_planner.jev_select.packaging_jev_sampling import exact_action,exact_digest
OUT=Path(__file__).resolve().parent
BASE=ROOT/'semantic_pallet_planner/outputs'
A1=BASE/'JEV_JM2_A1_20261115_01'
C1=BASE/'JEV_JM1_C1_REAL_BASELINES_20261112_01'
C2=BASE/'JEV_JM1_C2_REAL_SUFFIXES_20261113_01'
def read(p):return json.loads(Path(p).read_text())
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ref(p,pointer=''):
 p=Path(p).resolve();assert p.is_relative_to(ROOT)
 return dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p),pointer=pointer)
def resolve(r):
 p=ROOT/r['path'];assert sha(p)==r['sha256'];v=read(p)
 for k in r['pointer'].split('/')[1:]:
  k=k.replace('~1','/').replace('~0','~');v=v[int(k)] if isinstance(v,list) else v[k]
 return v
def checked(r):
 p=Path(r['path']);p=p if p.is_absolute() else ROOT/p
 assert sha(p)==r['sha256'];return read(p),p
def leaves(v,p=''):
 if isinstance(v,dict):
  for k,x in v.items():yield from leaves(x,p+'/'+k.replace('~','~0').replace('/','~1'))
 elif isinstance(v,list):
  for i,x in enumerate(v):yield from leaves(x,p+'/'+str(i))
 else:yield p,v

def main():
 contract=dict(version='jm2_a2_projection_contract_v1',role_semantics={'A':'registered reference','B':'registered alternative'},delta='B_minus_A',result_categories='observed terminal category only; no force, certificate, monitor reason or pre-evaluation',fixed_container_utilization='descriptive only; not proof of layout improvement when both complete',limits=m.LIMITS,scope='ARCHIVE_ONLY_PENDING_A3',query='current public structure/full-pool features only',private='exact IDs, original full task, future boxes, full trajectories and source paths',not_implemented=['retrieval','request injection','A3 sufficiency','execution admission'],metrics=list(m.METRICS),cost='model_cost_usd UNKNOWN retained; latency elapsed_s is observed wall time, not causal cost advantage')
 contract['constants']=dict(version=m.JM_T_PROJECTION,coordinate=m.scenario.COORDINATE,limits=m.LIMITS,execution_eligible=False,sufficiency_review='NOT_RUN_A3',outcome_rule='jev_branch_comparison_rule_v2; B relative to A; labels are local observations')
 write(OUT/'projection_contract.json',contract)
 plan=read(C1/'fork_plan.json');epath=C2/'evidence_levels_and_conflicts.json';evidence=read(epath)
 readiness=read(C2/'experience_input_readiness.json');assert len(evidence['points'])==len(plan['points'])==5
 cards=[];queries=[];maps=[];audits=[];attempts=[];families=[]
 a1orig=read(A1/'field_origin_index.json')['points']
 for i,point in enumerate(plan['points']):
  pid=point['point_id'];ep=next(e for e in evidence['points'] if e['point_id']==pid);ei=evidence['points'].index(ep)
  family=next(f for f in readiness['families'] if pid in f['point_ids']);families.append(copy.deepcopy(family))
  hp=A1/'saved_public_checks'/pid/'historical_input.json';h=read(hp)
  loc=point['public_evidence_location'];state,sp=checked(loc['prefix_ref']);pool,pp=checked(loc['pool_ref'])
  rebuilt=m.scenario.from_saved_public(state,pool,expected_pool_count=len(pool),expected_raw_pool_digest=m.scenario.digest(pool))
  assert rebuilt==h and len(h['pool'])==len(pool)
  origins=next(o for o in a1orig if o['point_id']==pid)
  observations=[];obs_sources=[];private_pairs=[];identity=None;policyrefs=[]
  for cr in ep['comparisons']:
   c,cp=checked(cr);assert c['point_id']==pid and c['same_prefix_pool_task_follow'] is True
   assert c['delta_direction']=='alternative_minus_reference' and c['continuation']=='jev_no_memory / memories=[]'
   assert c['baseline_whole_trajectory_used_as_benefit_reference'] is False
   branches={};brpaths={};expaths={}
   for role,key,planned in [('A','reference_branch',point['branches'][0]),('B','alternative_branch',point['branches'][1])]:
    b,bp=checked(c[key]);branches[role]=b;brpaths[role]=bp
    assert b['candidate_id']==planned['candidate_id'] and b['exact_action_digest']==planned['exact_action_digest']
    original=next(r for r in pool if r['candidate_id']==b['candidate_id'])
    assert exact_action(original)==b['exact_action'] and exact_digest(original)==b['exact_action_digest']
    assert m.scenario.digest(original)==b['candidate_digest']
    ex,xp=checked(b['execution_ref']);expaths[role]=xp
    cfg=ex['config'];assert cfg['selector']=='jev_no_memory' and cfg['memory_mode']=='none'
    sid=cfg['runtime_identity']['strategy_identity'];identity=sid if identity is None else identity;assert sid==identity
    policyrefs.append(ref(xp,'/config/runtime_identity/strategy_identity'))
   row={r:{k:branches[r]['metrics'][k] for k in m.METRICS} | {k:branches[r]['metrics'][k] for k in ('model_cost_usd','stable_complete','category')} for r in ('A','B')}
   row.update(label=c['evaluation']['label_v2'],delta_B_minus_A={k:row['B'][k]-row['A'][k] for k in m.METRICS})
   for k in m.METRICS:assert math.isclose(row['delta_B_minus_A'][k],c['all_numeric_metric_deltas'][k],rel_tol=1e-12,abs_tol=1e-9)
   observations.append(row);obs_sources.append((cp,brpaths))
   private_pairs.append(dict(comparison=ref(cp),branches={r:ref(brpaths[r]) for r in ('A','B')},executions={r:ref(expaths[r]) for r in ('A','B')},trajectories={r:ref(ROOT/branches[r]['storage_root']/'ledger/requests.json') for r in ('A','B')}))
  continuation=dict(policy='jev_no_memory / memories=[]',identity=identity,stochastic_choices_fixed=False)
  card=m.project_case(h,point['branches'][0]['candidate_id'],point['branches'][1]['candidate_id'],observations=observations,continuation=continuation,evidence_grade=ep['evidence_grade'],repeat_conflict=ep['repeat_conflict'])
  query=m.query_projection(h);cards.append(card);queries.append(query)
  # Evidence for every public scalar. Paths never enter the public card/query.
  mapping=[]
  for pointer,value in leaves(card):
   parts=pointer.split('/')[1:];head=parts[0];sources=[];transform='COPY'
   if head=='structure':
    key=parts[1];suffix='/'.join(parts[2:])
    if key=='container':sources=[ref(sp,'/container/'+suffix)]
    else:
     idx=int(parts[2]);field=parts[3];tail='/'.join(parts[4:])
     sources=[ref(sp,'/'+key+'/'+str(idx)+'/'+('item_id' if field=='box_role' else field)+('/'+tail if tail else ''))]
     if field=='box_role':transform='IDENTITY_ALIAS_BY_FULL_BUFFER_OR_PLACED_ORDINAL_NEVER_ATTRIBUTES'
   elif head=='features':
    sources=origins['features'][parts[1]]['historical']+[ref(A1/'saved_public_checks'/pid/'historical_signature.json',pointer)];transform='A1_COMMON_FUNCTION:'+m.scenario.feature_spec()['features'][parts[1]]['formula']
   elif head=='actions':
    role=parts[1];src=origins['action_roles'][role]['saved_action'];sources=[src,ref(sp,'/buffer'),ref(A1/'saved_public_checks'/pid/'action_contrast_binding.json','/roles/'+role)];transform='A1_ROLE_AND_EXACT_PUBLIC_ACTION_WITH_IDENTITY_ALIAS'
   elif head=='observations':
    oi=int(parts[1]);cp,brpaths=obs_sources[oi]
    if parts[2] in ('A','B'):sources=[ref(brpaths[parts[2]],'/metrics/'+parts[3])]
    elif parts[2]=='label':sources=[ref(cp,'/evaluation/label_v2')]
    else:sources=[ref(brpaths[r],'/metrics/'+parts[3]) for r in ('A','B')];transform='B_MINUS_A'
   elif head in ('evidence_grade','repeat_conflict'):sources=[ref(epath,'/points/'+str(ei)+'/'+head)]
   elif head=='continuation':
    if parts[1]=='identity':sources=policyrefs
    elif parts[1]=='policy':sources=[ref(obs_sources[0][0],'/continuation')]
    else:sources=[ref(epath,'/points/'+str(ei)+'/uncertainty')];transform='POLICY_FIXED_NOT_STOCHASTIC_CHOICES'
   elif head in ('intervention','attribute_directions'):sources=[ref(A1/'saved_public_checks'/pid/'action_contrast_binding.json',pointer)]
   elif head=='cross_start_support':sources=[ref(C2/'experience_input_readiness.json','/families/'+str(readiness['families'].index(family))+'/cross_start_support')]
   else:sources=[ref(OUT/'projection_contract.json','/constants'+pointer)];transform='PROTOCOL_CONSTANT_NOT_EMPIRICAL_CLAIM';assert resolve(sources[0])==value
   for source in sources:resolve(source)
   if transform=='COPY':assert resolve(sources[0])==value
   mapping.append(dict(output_pointer=pointer,sources=sources,transform=transform))
  assert len(mapping)==len(list(leaves(card)))
  maps.append(dict(card_index=i,point_id=pid,fields=mapping,claims=[dict(claim='historical labels are B relative to A under identical continuation identity; not causal mechanism',sources=[ref(p[0],'/evaluation') for p in obs_sources]),dict(claim='conflict and all repetitions retained',sources=[ref(epath,'/points/'+str(ei))])]))
  audits.append(dict(card_index=i,point_id=pid,full_pool=ref(pp),public_prefix=ref(sp),a1_input=ref(hp),pairs=private_pairs,role_binding_diagnostic=ref(A1/'saved_public_checks'/pid/'action_contrast_binding.json'),family=family))
  assert not any(isinstance(v,str) and v.startswith('item_') for _,v in leaves(card))
  assert 'candidate_id' not in json.dumps(card)
  forbidden=('task_id','future','monitor_statuses','monitor_result_reasons','frozen_candidate','correspondence_pairs','comparison_id','storage_root','C01')
  assert not any(k in json.dumps(card) for k in forbidden)
  assert set(query)=={'version','coordinate','structure','features'}
 denominators=read(C2/'full_denominators.json')
 assert sum(len(c['observations']) for c in cards)==denominators['registered_pairs']==9
 assert len([pair for a in audits for pair in a['pairs']])*2==denominators['registered_jobs']==18
 assert {Path(r['path']).name for ep in evidence['points'] for r in ep['comparisons']}=={p.name for p in (C2/'comparisons').glob('*.json')}
 for label,count in denominators['pair_labels'].items():
  assert sum(row['label']==label for card in cards for row in card['observations'])==count
 write(OUT/'case_snapshot_candidate.json',dict(version='jm2_a2_case_snapshot_candidate_v1',status='ARCHIVE_CANDIDATE_NOT_FROZEN_MEMORY',cards=cards))
 write(OUT/'query_projection_checks.json',dict(version='jm2_a2_queries_v1',queries=queries,scope='saved public engineering input only; no live retrieval or request'))
 write(OUT/'field_and_claim_evidence.json',dict(version='jm2_a2_field_claim_evidence_v1',private_audit_only=True,cards=maps))
 write(OUT/'private_audit_index.json',dict(version='jm2_a2_private_index_v1',private_audit_only=True,cards=audits,originals_retained=True))
 write(OUT/'inherited_denominators.json',dict(version='jm2_a2_denominators_v1',full=read(C2/'full_denominators.json'),source_support=read(C2/'source_and_start_support.json'),families=readiness['families'],limits=readiness['limitations'],a1_boundary=read(A1/'inherited_evidence_boundary.json')))
 # Constructed rejection checks exercise roles, public/private boundaries and missing facts.
 h=read(A1/'saved_public_checks'/plan['points'][0]['point_id']/'historical_input.json');p=plan['points'][0];c=cards[0]
 def call(v=h,obs=None):return m.project_case(v,p['branches'][0]['candidate_id'],p['branches'][1]['candidate_id'],observations=obs if obs is not None else c['observations'],continuation=c['continuation'],evidence_grade=c['evidence_grade'],repeat_conflict=c['repeat_conflict'])
 def reject(name,fn):
  try:fn()
  except (ValueError,KeyError,TypeError) as e:attempts.append(dict(name=name,status='PASS_EXPECTED_REJECTION',reason=str(e)));return
  raise AssertionError(name)
 bad=copy.deepcopy(h);bad['pool']=bad['pool'][:2];reject('two_actions_are_not_full_pool',lambda:call(bad))
 bad=copy.deepcopy(h);del bad['state']['placed_objects'][0]['pose'];reject('missing_structure',lambda:call(bad))
 bad=copy.deepcopy(h);bad['state']['future_boxes']=[];reject('future_in_query',lambda:m.query_projection(bad))
 bad=copy.deepcopy(h);bad['test_score']=1;reject('test_answer_in_query',lambda:m.query_projection(bad))
 bad=copy.deepcopy(c['observations']);bad[0]['A'],bad[0]['B']=bad[0]['B'],bad[0]['A'];reject('roles_swapped_without_results',lambda:call(obs=bad))
 bad=copy.deepcopy(c['observations']);bad[0]['A']['monitor_statuses']={};reject('pct_diagnostic_in_fragment',lambda:call(obs=bad))
 reject('missing_observations',lambda:call(obs=[]))
 bad=copy.deepcopy(c);bad['actions']['A']['candidate_id']='C01';reject('historical_answer_in_fragment',lambda:m.validate(bad))
 f=guards.fixture();bind=m.scenario.bind_contrast(f,'a0','b0');assert bind['roles']['A']['box_role']!=bind['roles']['B']['box_role'];assert bind['intervention']=='CROSS_BOX_SELECTION'
 attempts.append(dict(name='same_attributes_distinct_boxes_not_merged',status='PASS'))
 a=m.query_projection(f);assert a['features']['candidate_count']['value']==4 and a['features']['candidate_mean_top_mm']['value']==17.5
 attempts.append(dict(name='full_pool_not_two_action_statistics',status='PASS'))
 assert not any(any(n==k or n.startswith(k+'.') for k in guards.BLOCKED) for n in sys.modules)
 attempts.append(dict(name='forbidden_imports_absent',status='PASS'))
 write(OUT/'check_attempts.json',dict(version='jm2_a2_attempts_v1',checks=attempts,unexpected_failures=[]))
 write(OUT/'validation_receipt.json',dict(version='jm2_a2_validation_v1',status='PASS_LIMITED_A2',real_saved_nonempty_cards=len(cards),comparisons=sum(len(c['observations']) for c in cards),full_pool_counts=[q['features']['candidate_count']['value'] for q in queries],public_field_evidence_count=sum(len(x['fields']) for x in maps),constructed_checks=len(attempts),central_jsonschema='AVAILABLE_NOT_IMPORTED' if importlib.util.find_spec('jsonschema') else 'NOT_RUN_MISSING_DEPENDENCY',A3='NOT_RUN',request_injection='NOT_RUN',actual_operations={k:0 for k in ('credentials_read','model_calls','orders','forks','candidate_reconstruction','prefix_replay','stability_solves','subagents')}))
 print('PASS_A2_SAVED_5_CARDS_9_PAIRS_AND_CONSTRUCTED_CHECKS')
if __name__=='__main__':main()

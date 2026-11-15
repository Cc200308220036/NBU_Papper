"""A3 stdlib-only saved-evidence audit. Never imports the order/physics engine.

Geometry below is descriptive arithmetic over already saved rectangles, not
candidate generation, collision/feasibility validation or a stability solver.
The audit guard is a conservative review checklist, not an execution route.
"""
import copy,hashlib,json,sys
from decimal import Decimal as D
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
BASE=ROOT/'semantic_pallet_planner/outputs';A2=BASE/'JEV_JM2_A2_20261115_01';A1=BASE/'JEV_JM2_A1_20261115_01';C2=BASE/'JEV_JM1_C2_REAL_SUFFIXES_20261113_01'
CACHE={}
def read(p):
 p=Path(p).resolve()
 if p not in CACHE:CACHE[p]=json.loads(p.read_text())
 return CACHE[p]
def write(name,v):(OUT/name).write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ref(p,pointer=''):
 p=Path(p).resolve();assert p.is_relative_to(ROOT)
 return dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p),pointer=pointer)
def resolve(r):
 p=Path(r['path']);p=p if p.is_absolute() else ROOT/p
 assert p.resolve().is_relative_to(ROOT) and sha(p)==r['sha256'];v=read(p)
 for k in r.get('pointer','').split('/')[1:]:
  k=k.replace('~1','/').replace('~0','~');v=v[int(k)] if isinstance(v,list) else v[k]
 return v
def leaves(v,p=''):
 if isinstance(v,dict):
  for k,x in v.items():yield from leaves(x,p+'/'+k.replace('~','~0').replace('/','~1'))
 elif isinstance(v,list):
  for i,x in enumerate(v):yield from leaves(x,p+'/'+str(i))
 else:yield p,v
def bounds(o):
 p=o['pose'];l,w,h=map(lambda x:D(str(x)),o['oriented_size_mm']);x,y,z=(D(str(p[k])) for k in ['x_mm','y_mm','z_base_mm'])
 return x-l/2,x+l/2,y-w/2,y+w/2,z,z+h

def geometry(card,role):
 a=card['actions'][role];b=bounds(a);c=card['structure']['container'];contacts=[]
 for placed in card['structure']['placed_objects']:
  q=bounds(placed)
  area=max(D(0),min(b[1],q[1])-max(b[0],q[0]))*max(D(0),min(b[3],q[3])-max(b[2],q[2]))
  if q[5]==b[4] and area>0:contacts.append(dict(box_role=placed['box_role'],xy_overlap_mm2=float(area)))
 return dict(footprint_bounds_mm=list(map(float,b[:4])),base_mm=float(b[4]),top_mm=float(b[5]),floor=b[4]==0,exact_plane_geometric_contacts=contacts,wall_clearance_mm=dict(left=float(b[0]+D(str(c['length_mm']))/2),right=float(D(str(c['length_mm']))/2-b[1]),front=float(b[2]+D(str(c['width_mm']))/2),back=float(D(str(c['width_mm']))/2-b[3])),interpretation='DESCRIPTIVE_ONLY_NOT_SUPPORT_VALIDITY_USABLE_SPACE_OR_FORCE')

def relation(card):
 a,b=(card['actions'][r] for r in ['A','B'])
 if a['box_role']!=b['box_role']:return 'CROSS_BOX_SELECTION'
 moved=any(a['pose'][k]!=b['pose'][k] for k in ['x_mm','y_mm','z_base_mm']);rot=a['pose']['yaw_deg']!=b['pose']['yaw_deg']
 return 'SAME_BOX_TRANSLATION_AND_ROTATION' if moved and rot else 'SAME_BOX_TRANSLATION' if moved else 'SAME_BOX_ROTATION' if rot else 'IDENTICAL_ACTION'

def checklist(card,critical_unknowns,review_source):
 """No similarity score. Presence never certifies explanatory sufficiency."""
 try:
  assert card['structure']['placed_objects'] and card['structure']['buffer']
  for o in card['structure']['placed_objects']:bounds(o)
  for role in ['A','B']:
   a=card['actions'][role];bounds(a)
   assert a['box_role'] in [x['box_role'] for x in card['structure']['buffer']]
  assert relation(card)==card['intervention']
  assert card['observations'] and card['continuation']['identity']
 except (KeyError,AssertionError,TypeError):return 'REJECT_MISSING_OR_INCONSISTENT_CONDITION'
 if critical_unknowns:return 'ARCHIVE_ONLY_UNKNOWN'
 if not review_source.get('trusted_independent_approval',False):return 'PENDING_REVIEW_SOURCE'
 return 'CHECKLIST_READY_ONLY_NOT_APPLICABILITY'

NARRATIVES=[
 ('同一box_1沿y平移−5mm；箱尺寸、重量、承载、朝向、x及底高不变。两动作均地板放置；公开几何能核对墙距变化。',
  '两次装入体积均改善，但垛高差为−40/+40mm。不能解释成稳定的降低垛高机制，也不能从5mm位移推断后续空间收益。'),
 ('从box_1换为box_2，长度/宽度/高度、质量、承载及x均改变；y、底高与朝向相同。两者位于placed_3顶面高度。',
  'B较矮、承载参数较高，却两次装入体积更少；局部高度或容量不能替代长期结果。支撑面积几何可描述，不等于承载路径或未来可用空间。'),
 ('同一box_2沿y平移+2.5mm；底高320mm、朝向和箱体属性不变；box_2与box_3同属性但身份不同。',
  '两次主要结果中性，只能说注册指标等价，不能说布局或机制等价。不可堆叠箱及支撑体属性保留，不据此虚构中性成因。'),
 ('从box_3换为box_1；箱体、尺寸/质量、x/y和朝向90→0均改变，底高290mm及stackable/容量参数相同；支撑位置也不同。',
  '仅一次比较：装入量相同，B垛高+40mm且包络利用率降低，仍为退化；不能把多因素变化单归因为旋转、选箱或支撑变化。'),
 ('同一box_2沿x平移+5mm、y平移−30mm；箱体属性、朝向与地板底高不变。公开几何保留旁侧已有三层箱垛。',
  '两次体积/质量改善而件数与垛高相同；保存结果不足证明位移释放了可装空间。两次时延差异方向不同，不能声称成本更低。')]

def main():
 # Exact byte identities, no tolerant hash exceptions and no historical regeneration.
 source=read(A2/'source_manifest.json')
 for n,d in source.items():assert sha(ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'/n)==d
 parents=[]
 for p in [A2/'delivery_manifest.json',BASE/'JEV_JM2_A2_QA_20261115_01/delivery_manifest.json']:
  man=read(p)
  for e in man['files']:
   fp=ROOT/e['path'];assert sha(fp)==e['sha256'] and fp.stat().st_size==e['bytes']
  parents.append(dict(manifest=ref(p),files=len(man['files']),status='PASS_EXACT_BYTES'))
 cards=read(A2/'case_snapshot_candidate.json')['cards'];index=read(A2/'private_audit_index.json')['cards'];fmap=read(A2/'field_and_claim_evidence.json')['cards']
 spec=read(A1/'scenario_feature_spec.json');origins=read(A1/'field_origin_index.json');a1handoff=read(A1/'handoff.json');c2handoff=read(C2/'handoff.json')
 den=read(C2/'full_denominators.json');support=read(C2/'source_and_start_support.json');levels=read(C2/'evidence_levels_and_conflicts.json');ready=read(C2/'experience_input_readiness.json')
 reviewer=dict(version='jm2_a3_review_source_v1',actual_author='Codex current development session',type='DEVELOPER_AGENT_ANALYTICAL_ASSESSMENT',human_signature=None,independent_reviewer=None,trusted_independent_approval=False,external_review_status='PENDING',scope='actual agent content assessment and reproducible program checks separately recorded; no external model API or fabricated human signoff',review_basis=[ref(BASE/'JEV_JM2_A2_QA_20261115_01/next_stage_admission.json'),ref(OUT/'review_saved.py')])
 write('review_source.json',reviewer)
 reviews=[];checks=[];source_refs=0;labels={};private_seen=[]
 for i,(c,e,mapping) in enumerate(zip(cards,index,fmap)):
  cp=lambda p:ref(A2/'case_snapshot_candidate.json','/cards/'+str(i)+p)
  h=resolve(e['a1_input']);pool=resolve(e['full_pool']);state=resolve(e['public_prefix']);binding=resolve(e['role_binding_diagnostic'])
  assert h['state']==state and len(pool)==c['features']['candidate_count']['value']
  assert len(pool)==len(h['pool'])==h['pool_receipt']['count']
  # Public anonymous structure contains every observed box without attribute merging.
  for key,prefix in [('buffer','box_'),('placed_objects','placed_')]:
   expected=[]
   for j,box in enumerate(state[key]):
    box=copy.deepcopy(box);box.pop('item_id');box['box_role']=prefix+str(j+1);expected.append(box)
   assert expected==c['structure'][key]
  assert state['container']==c['structure']['container']
  assert len(mapping['fields'])==len(list(leaves(c)))
  for row in mapping['fields']:
   for r in row['sources']:resolve(r);source_refs+=1
  geom={r:geometry(c,r) for r in ['A','B']}
  for role in ['A','B']:
   a=c['actions'][role];old=binding['roles'][role];exact=old['exact_action']
   assert a['box_role']==old['box_role'] and a['pose']==exact['pose'] and a['oriented_size_mm']==exact['oriented_size_mm']
   assert a['attributes']==old['attributes']
  assert relation(c)==c['intervention']==binding['intervention'] and binding['ambiguity']
  pair_checks=[]
  for row,pair in zip(c['observations'],e['pairs']):
   comp=resolve(pair['comparison']);assert row['label']==comp['evaluation']['label_v2'] and comp['delta_direction']=='alternative_minus_reference'
   labels[row['label']]=labels.get(row['label'],0)+1
   assert comp['same_prefix_pool_task_follow'] and not comp['baseline_whole_trajectory_used_as_benefit_reference']
   for role in ['A','B']:
    b=resolve(pair['branches'][role]);ex=resolve(pair['executions'][role]);trajectory=resolve(pair['trajectories'][role]);private_seen.append(pair['trajectories'][role])
    assert ex['config']['runtime_identity']['strategy_identity']==c['continuation']['identity']
    assert ex['config']['selector']=='jev_no_memory' and ex['config']['memory_mode']=='none'
    assert b['candidate_id']==binding['roles'][role]['exact_action']['candidate_id']
    frozen=next(x for x in pool if x['candidate_id']==b['candidate_id']);assert frozen==b['frozen_candidate']
    for k,v in row[role].items():assert v==b['metrics'][k]
    assert len(trajectory['requests'])==row[role]['requests']
    for k in ['pose','oriented_size_mm']:assert binding['roles'][role]['exact_action'][k]==frozen[k]
   for k,v in row['delta_B_minus_A'].items():assert v==row['B'][k]-row['A'][k]
   pair_checks.append(dict(comparison=pair['comparison'],label=row['label'],policy_identity_verified=True,branches_and_trajectories_verified=True))
  ep=next(p for p in levels['points'] if p['point_id']==e['point_id']);assert ep['evidence_grade']==c['evidence_grade'] and ep['repeat_conflict']==c['repeat_conflict']
  unknowns=[
   ['5MM_FLOOR_TRANSLATION_LONG_TERM_SPACE_MECHANISM_UNKNOWN','HEIGHT_DIRECTION_CONFLICT_NOT_EXPLAINED_BY_CURRENT_FRAGMENT','FUTURE_OR_STOCHASTIC_SUFFIX_DEPENDENCE_UNKNOWN'],
   ['MULTIPLE_BOX_PROPERTY_CHANGES_NOT_ISOLATED','USABLE_SPACE_AND_LOAD_PATH_RELEVANCE_TO_LOWER_VOLUME_UNKNOWN','FUTURE_OR_STOCHASTIC_SUFFIX_DEPENDENCE_UNKNOWN'],
   ['REGISTERED_METRIC_NEUTRALITY_DOES_NOT_EXPLAIN_LAYOUT_EQUIVALENCE','NECESSITY_OF_SMALL_SUPPORT_EDGE_CLEARANCE_UNKNOWN','FUTURE_OR_STOCHASTIC_SUFFIX_DEPENDENCE_UNKNOWN'],
   ['BOX_SUPPORT_LOCATION_AND_YAW_CHANGES_NOT_ISOLATED','SINGLE_OBSERVATION_COMPACTNESS_MECHANISM_UNKNOWN','FUTURE_OR_STOCHASTIC_SUFFIX_DEPENDENCE_UNKNOWN'],
   ['FLOOR_TRANSLATION_CAUSAL_SPACE_RELEASE_UNKNOWN','VOLUME_GAIN_WITH_EQUAL_COUNT_CANNOT_ESTABLISH_CURRENT_SPACE_RULE','FUTURE_OR_STOCHASTIC_SUFFIX_DEPENDENCE_UNKNOWN']][i]
  fact=lambda text,refs:dict(kind='SAVED_FACT_OR_DETERMINISTIC_DESCRIPTION',statement=text,evidence=refs)
  infer=lambda text,refs:dict(kind='DEVELOPER_ASSESSMENT_NOT_CAUSAL_FACT',statement=text,evidence=refs,source=ref(OUT/'review_source.json'))
  dimensions=[
   dict(item='decision_before_support_space_structure',saved_facts=[fact('放置几何、箱体属性和面积账本标量逐项保留；下表仅为已保存矩形的接触/墙距描述。',[cp('/structure'),e['public_prefix']])],descriptive_geometry=geom,assessment='PARTIAL_FOR_EXPLANATION',unknowns=unknowns[:2],boundary='Exact-plane overlap is not force, support validity, connected free volume or future packing.'),
   dict(item='intervention_and_invariants',saved_facts=[fact(NARRATIVES[i][0],[cp('/actions'),cp('/attribute_directions'),e['role_binding_diagnostic']])],assessment='PASS_FACT_RETENTION',changed_attributes=binding['changed_attributes'],unchanged_attributes=binding['unchanged_attributes'],current_correspondence='AMBIGUOUS_DIAGNOSTIC_ONLY_NO_CHOSEN_ACTION'),
   dict(item='anonymous_identity_coordinates_exact_action',saved_facts=[fact('角色、坐标、朝向、尺寸与原完整保存池及本点全部分支动作一致，同属性不同箱身份保留。',[cp('/actions'),e['full_pool'],e['a1_input']])],assessment='PASS_SAVED_CONSISTENCY'),
   dict(item='continuation_outcomes_costs_counterevidence',saved_facts=[fact('无经验Jev后续身份一致；保留全部本点比较、结果、代价和货币费用UNKNOWN。',[cp('/continuation'),cp('/observations'),cp('/evidence_grade'),cp('/repeat_conflict')]+[p['comparison'] for p in e['pairs']])],assessment='PASS_RETENTION_NOT_BENEFIT',content_assessment=infer(NARRATIVES[i][1],[cp('/observations')]),cost_unknown='MONETARY_COST_UNKNOWN; elapsed wall time is not causal latency benefit'),
   dict(item='future_and_observability',saved_facts=[fact('公开卡片不含私有整单、未来箱或两条完整轨迹，私有执行和请求归档可回指。',[cp(''),ref(A2/'private_audit_index.json','/cards/'+str(i)+'/pairs')])],assessment='NO_PUBLIC_LEAK_FOUND_BUT_EXPLANATORY_DEPENDENCE_UNKNOWN',inference=infer('不能用私有未来箱或后续选择补造公开规则；长期结果差异是否仅凭当前公开条件可解释仍UNKNOWN。',[cp('/structure'),cp('/observations')]),unknowns=unknowns[2:]),
   dict(item='critical_unknowns_and_review_source',assessment='ARCHIVE_ONLY',unknowns=unknowns,external_trusted_review='PENDING',review_source=ref(OUT/'review_source.json'))]
  for d in dimensions:
   for f in d.get('saved_facts',[]):
    for r in f['evidence']:resolve(r)
  outcome=checklist(c,unknowns,reviewer);assert outcome=='ARCHIVE_ONLY_UNKNOWN'
  reviews.append(dict(card_index=i,point_id=e['point_id'],card_ref=cp(''),program_checks='PASS_SAVED_CONSISTENCY',content_assessment_source=ref(OUT/'review_source.json'),trusted_content_approval='PENDING',dimensions=dimensions,unknown_critical_conditions=unknowns,criticality_boundary='候选解释条件的必要性本身未建立；未实现特征不自动视为所有取舍都必需。保留原始几何不等于已证明解释充分。',disposition='ARCHIVE_ONLY',sufficiency='NOT_ESTABLISHED',execution_eligible=False,mechanism_transfer='NOT_ESTABLISHED',M21_07=dict(record_completeness='PASS',unknown_non_execution_guard='PASS',trusted_review_source='PENDING',overall='PARTIAL_PENDING_TRUSTED_REVIEW'),pair_checks=pair_checks))
  checks.append(dict(point_id=e['point_id'],pool_count=len(pool),pairs=len(e['pairs']),public_geometry_matches_source=True,role_action_outcome_matches=True))
 assert len(cards)==5 and sum(labels.values())==9 and labels=={'improved':4,'degraded':3,'neutral':2}
 assert len(private_seen)==18 and den['independent_unseen_sources']==0
 assert all(f['cross_start_support']==0 for f in ready['families'])
 # Necessary constructed cases are review diagnostics only; no historical pool rebuild.
 # Equal cached signatures are deliberately stale: review must compare raw geometry.
 # Move the saved support geometry under a base-height action to change exact contact.
 support_a=copy.deepcopy(cards[1]);support_b=copy.deepcopy(support_a)
 support_b['structure']['placed_objects'][2]['pose']['x_mm']+=800
 assert support_a['structure']['buffer']==support_b['structure']['buffer']
 assert support_a['features']==support_b['features']
 assert geometry(support_a,'A')['exact_plane_geometric_contacts']!=geometry(support_b,'A')['exact_plane_geometric_contacts']
 swap=copy.deepcopy(cards[2]);swap['actions']['B']['box_role']='box_3'
 assert swap['actions']['A']['attributes']=={**swap['actions']['B']['attributes'],'y_over_width':swap['actions']['A']['attributes']['y_over_width']}
 assert relation(swap)=='CROSS_BOX_SELECTION' and relation(cards[2])=='SAME_BOX_TRANSLATION'
 deletion=[]
 for path in [('structure','placed_objects',0,'pose'),('structure','buffer'),('continuation','identity')]:
  bad=copy.deepcopy(cards[0]);target=bad
  for k in path[:-1]:target=target[k]
  del target[path[-1]]
  assert checklist(bad,[],reviewer)=='REJECT_MISSING_OR_INCONSISTENT_CONDITION'
  deletion.append(list(path))
 assert checklist(cards[0],[],reviewer)=='PENDING_REVIEW_SOURCE'
 constructed=dict(version='jm2_a3_constructed_checks_v1',scope='CONSTRUCTED_REVIEW_DIAGNOSTICS_NOT_POLICY_EVIDENCE',checks=[dict(name='equal_buffer_means_different_support_space',status='PASS',input_A=support_a,input_B=support_b,buffer_means_identical=True,stale_signature_equal=True,geometry_A=geometry(support_a,'A'),geometry_B=geometry(support_b,'A'),interpretation='raw structure and exact-plane overlap differ; cached vector equality cannot establish sufficiency'),dict(name='same_attributes_different_box_not_same_translation',status='PASS',original=cards[2]['actions'],mutated=swap['actions'],original_intervention=relation(cards[2]),mutated_intervention=relation(swap),guard=checklist(swap,[],reviewer)),dict(name='deleted_critical_condition_refused',status='PASS',deleted_paths=deletion,result='REJECT_MISSING_OR_INCONSISTENT_CONDITION'),dict(name='no_trusted_review_source_not_sufficient',status='PASS',result='PENDING_REVIEW_SOURCE')])
 write('constructed_validation.json',constructed)
 write('projection_sufficiency_review.json',dict(version='jm2_a3_projection_sufficiency_review_v1',date='2026-11-15',scope='PRIVATE_AUDIT_ONLY_NOT_MODEL_INPUT',review_source=ref(OUT/'review_source.json'),cards=reviews,summary=dict(cards=5,comparisons=9,archive_only=5,approved_sufficient=0,pending_trusted_review=5,labels=labels,coverage='PARTIAL',cross_start_support_per_family=0,independent_unseen_sources=0),program_vs_content='Program consistency PASS does not imply explanatory sufficiency or trusted content approval.',M21_07='PARTIAL_PENDING_TRUSTED_REVIEW',engineering_status='COMPLETE_A3_AUDIT_DELIVERY_PENDING_INDEPENDENT_QA',evidence_readiness='READY_FOR_INDEPENDENT_REVIEW_NOT_GENERATION',research_result='NOT_ESTABLISHED',next_stage_admission='INDEPENDENT_QA_ONLY'))
 write('evidence_mapping.json',dict(version='jm2_a3_evidence_mapping_v1',parent_manifests=parents,inherited_field_evidence=ref(A2/'field_and_claim_evidence.json'),inherited_field_source_references_checked=source_refs,production_source_files_unchanged=len(source),per_card_program_checks=checks,source_support=ref(C2/'source_and_start_support.json'),denominators=ref(C2/'full_denominators.json'),levels=ref(C2/'evidence_levels_and_conflicts.json'),feature_contract=ref(A1/'scenario_feature_spec.json'),private_trajectory_refs=private_seen,all_review_dimension_sources='embedded in projection_sufficiency_review.json with path/SHA256/pointer',numerical_tolerance_used=False,source_hash_exemption=False))
 write('inherited_boundaries.json',dict(full_denominators=den,source_and_start_support=support,experience_readiness=ready,point_evidence=levels,QA_failure_log=ref(BASE/'JEV_JM2_A2_QA_20261115_01/tests.log'),QA_checks=ref(BASE/'JEV_JM2_A2_QA_20261115_01/static_checks.json'),A1_handoff=ref(A1/'handoff.json'),C2_handoff=ref(C2/'handoff.json')))
 print('PASS_A3_SAVED_CHECKS_5_CARDS_9_PAIRS_18_BRANCHES; CONTENT_ARCHIVE_ONLY_5; TRUSTED_REVIEW_PENDING_5')
if __name__=='__main__':main()

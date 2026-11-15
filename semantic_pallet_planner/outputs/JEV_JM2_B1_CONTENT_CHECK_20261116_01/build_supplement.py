"""Private, stdlib-only supplemental saved-content audit; no production imports.

Writes only this new directory. Subprocesses are read-only local Git metadata.
No geometry/candidate reconstruction, prefix replay, solver, model or credentials.
"""
import copy,hashlib,json,platform,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
BASE=ROOT/'semantic_pallet_planner/outputs';A2=BASE/'JEV_JM2_A2_20261115_01';A3=BASE/'JEV_JM2_A3_20261115_01';QA=BASE/'JEV_JM2_B1_FIX_QA_20261116_01';FIX=BASE/'JEV_JM2_B1_FIX_20261115_01';A1=BASE/'JEV_JM2_A1_20261115_01';C2=BASE/'JEV_JM1_C2_REAL_SUFFIXES_20261113_01';C1=BASE/'JEV_JM1_C1_REAL_BASELINES_20261112_01'
REPORT='docs/03_阶段产出分析/Jev/Jev_JM2-B1真实内容前置补充核查_20261116_01.md'
CACHE={};REFS={}
def read(p):
 p=Path(p).resolve()
 if p not in CACHE:CACHE[p]=json.loads(p.read_text())
 return CACHE[p]
def write(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ref(p,pointer=''):
 p=Path(p).resolve();assert p.is_relative_to(ROOT)
 r=dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p),pointer=pointer)
 if p.suffix=='.json':resolve(r)
 else:assert not pointer
 REFS[(r['path'],pointer)]=r
 return r
def resolve(r):
 p=Path(r['path']);p=p if p.is_absolute() else ROOT/p
 assert p.resolve().is_relative_to(ROOT) and sha(p)==r['sha256'];v=read(p)
 for k in r.get('pointer','').split('/')[1:]:
  k=k.replace('~1','/').replace('~0','~');v=v[int(k)] if isinstance(v,list) else v[k]
 return v
def git(*a):return subprocess.check_output(['git',*a],cwd=ROOT,text=True).strip()
def entry(p):return dict(path=p.relative_to(ROOT).as_posix(),bytes=p.stat().st_size,sha256=sha(p))

# Explicit developer analyses, never generated advice or trusted approval.
SPEC=[
 dict(tradeoff='同箱沿y−5mm的两位置比较；体积改善与垛高方向不一致、请求/token增加并存。',necessary='保持同一箱身份、朝向、底高、原有放置几何及前墙相对位置；评价方向必须同时保留体积、垛高、代价及重复槽。',gap='不能把两次体积改善改写成必然降低垛高或无代价改进；更一般的“贴墙更优”范围未受信审核。',critical_unknown='允许哪类指标权衡作为条件化方向、对哪些不同公开状态适用尚无可信审核结论；跨起点为0。',mechanism='为何5mm位置变化带来后续差异未证明；这不是核对两次历史结果或限定体积方向必须补做的因果证明。',direction='两次B−A体积均正，垛高一负一正；仅能保留该起点、该后续身份的历史向量，不给统一垛高方向。',disposition='ARCHIVE_AND_PENDING_SCOPE_REVIEW',reject='拒绝“B总能降低垛高/成本”或无条件贴墙建议。',delete='删同箱身份/位置或删重复垛高与代价，会将另一干预或冲突事实误读为单向收益，须判信息不足。',attrs=['y_over_width','base_over_height','yaw_deg'],conditions=['placed_count','placed_projection_union_ratio'],raw='前墙距10/5mm已由A3保存描述，原几何在A2；墙距不是已注册生成谓词。'),
 dict(tradeoff='跨箱联合配置比较：B更宽长、较矮、更重、承载参数较高，体积装入量两次更少。',necessary='同时保留全部箱体属性、x/底高/朝向、承接箱placed_3及原堆叠几何，不能只按容量或高度归组。',gap='不能由单个容量或高度特征确定方向；若限定为联合属性/位置对比，原记录已说明多因素共变，无需额外隔离单属性因果。',critical_unknown='该联合取舍在何种可观察上下文可迁移、哪些空间/支撑关系必须成为可计算门尚未获可信审核；局部接触未注册为生成谓词。',mechanism='造成体积下降的单一原因未知；保留联合比较事实或局部负向教训不以证明单因素机制为前提。',direction='两次体积退化同时高度降低、包络利用率提高、时长减少；不得从较低垛高或更大容量倒推装入改善。',disposition='ARCHIVE_NEGATIVE_AND_PENDING_SCOPE_REVIEW',reject='拒绝“容量越大越好/更矮必装更多”或把联合变化归因为单个属性。',delete='删去尺寸/质量/x或承接结构，只剩容量/高度会虚构单因素对照；须拒绝该单因素表达或补回现存字段。',attrs=['length_mm','width_mm','height_mm','mass_kg','max_top_load_kg','x_over_length','base_over_height'],conditions=['placed_count','placed_max_top_mm'],raw='A3记录同placed_3顶面XY相交230100/238000mm²；不是有效支撑或承载路径证明。'),
 dict(tradeoff='同箱沿y+2.5mm换位，两次注册主要指标中性；另有同属性box_3不能代换box_2。',necessary='保留具体箱体身份、不可堆叠属性、支撑箱placed_1几何、320mm底高及位置差；中性按注册指标而非布局解释。',gap='记录足以核对有限指标中性；不需要解释为何必然中性。若要变成等价位置规则，适用范围及布局等价证据不足。',critical_unknown='小边缘位移在其他公开上下文是否影响结果未知；接触边距/局部可用面未注册，不能编造阈值。',mechanism='中性成因未知不阻断中性档案；不得要求必须找出机制才承认已保存指标等价。',direction='两次主要结果差为0，仅时间/token有少量差别；不推出位置或箱体可互换。',disposition='ARCHIVE_NEUTRAL_AND_PENDING_SCOPE_REVIEW',reject='拒绝“同属性箱相同”“两位置普遍等价”及中性意味着无布局影响。',delete='删箱体身份或stackable/底高/支撑几何，会把同箱换位改成跨箱或跨结构条件；不能判同一对照或信息充分。',attrs=['stackable','y_over_width','base_over_height'],conditions=['placed_count','placed_top_level_count'],raw='A3保存placed_1同平面相交面积相同、前墙距2.5/5mm；这些并非完整自由空间相同。'),
 dict(tradeoff='跨箱、跨支撑位置并伴随朝向90→0的联合配置；一次体积/件数相同而B垛高更高、包络更低。',necessary='箱身份、长宽高/质量、朝向和x/y、两支撑位置及其顶高、后续和单次标记均须保留。',gap='原记录可核对本次联合配置的紧凑性退化；单次并非自动不准留档，也不需补因果证明，但不能升级为已重复或旋转单因子规则。',critical_unknown='联合条件是否能形成不混同选箱/位置/朝向的可观察规则、其适用边界尚未可信审核；跨支撑身份无已注册专用谓词。',mechanism='究竟箱体、支撑位置还是旋转主导结果未确定；只要诚实表达联合变化，不要求分离因果贡献。',direction='一次B−A体积/件数/质量为0，高度+40mm且包络利用率降低，保持PROVISIONAL_CASE和退化标签。',disposition='ARCHIVE_SINGLE_NEGATIVE_AND_PENDING_SCOPE_REVIEW',reject='拒绝“旋转导致退化”或“换箱导致退化”的孤立因果断言，拒绝伪装重复证据。',delete='删支撑位置、yaw或单次限制，会将多因素单次比较误作同位置旋转对照或重复规律，须判信息不足。',attrs=['length_mm','width_mm','height_mm','mass_kg','yaw_deg','x_over_length','y_over_width'],conditions=['placed_count','placed_top_level_count'],raw='A3记录A在placed_5顶高、B在placed_4顶高，底高均290mm；相交不等于受力证明。'),
 dict(tradeoff='同箱地板平移x+5/y−30mm；两次体积/质量提高，件数与垛高不变，时长差方向不同。',necessary='保留box_2身份/属性、地板底高、相邻三层箱垛几何、x/y位移以及完整体积/质量/件数/高度/成本向量。',gap='原记录可核对局部历史装入组成变化；要说“释放可用空间”缺已注册可用空隙指标，不能以简单墙距或承载和代替。',critical_unknown='跨状态的空间适用条件未可信审核；从当前可观察几何能否约束比较方向尚未确认，未来箱不准补入谓词。',mechanism='具体空间释放机制未证明；承认这两次体积差不依赖证明该机制，更不能读取私有未来箱反推公开条件。',direction='两次体积+33190500mm³、质量增加，件数/垛高不变；不声称装入件数更多或成本更低。',disposition='ARCHIVE_AND_PENDING_SCOPE_REVIEW',reject='拒绝“必然释放空间/装更多件/耗时更低”及将历史箱体序号当当前选择。',delete='删相邻结构或只留体积不留件数/时延重复值，会误导为空间普遍收益或全面改进，须拒绝该表达。',attrs=['x_over_length','y_over_width','base_over_height','stackable'],conditions=['placed_count','placed_max_top_mm'],raw='A3记录已有三层箱垛、右墙距10/5mm；连接自由空间、可用面与未来可装量仍NOT_IMPLEMENTED。')]

def main():
 head=git('rev-parse','HEAD');assert head=='82b82563153dd58199e6aa8d275a0a571f402380'
 parents=[]
 for folder in [QA,FIX,A3,A2]:
  for x in read(folder/'delivery_manifest.json')['files']:
   p=ROOT/x['path']
   if p.stat().st_size!=x['bytes'] or sha(p)!=x['sha256']:
    assert folder==A2 and x['path'] in ['semantic_pallet_planner/src/semantic_pallet_planner/jev_select/contracts.py','semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_versions.py']
    p=BASE/'JEV_JM2_B1_LIMITED_20261115_01/entry_source_bytes'/p.name
   assert p.stat().st_size==x['bytes'] and sha(p)==x['sha256']
  parents.append(dict(manifest=ref(folder/'delivery_manifest.json'),entries=len(read(folder/'delivery_manifest.json')['files'])))
 source=read(FIX/'source_manifest.json')
 for n,d in source.items():assert sha(ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'/n)==d
 # Required materials read as saved JSON, never execute their original test/build scripts.
 inputs=[QA/'quality_review.json',QA/'next_stage_admission.json',QA/'handoff.json',QA/'probe_results.json',FIX/'handoff.json',FIX/'compatibility_receipt.json',FIX/'experience_generation_readiness.json',A3/'review_source.json',A3/'handoff.json',A2/'field_and_claim_evidence.json',A2/'handoff.json']
 for p in inputs:read(p);ref(p)
 cards=read(A2/'case_snapshot_candidate.json')['cards'];reviews=read(A3/'projection_sufficiency_review.json')['cards'];private=read(A2/'private_audit_index.json')['cards'];spec=read(A1/'scenario_feature_spec.json')
 matrix=[];checked_pairs=0;checked_branches=0
 for i,(c,r,idx,s) in enumerate(zip(cards,reviews,private,SPEC)):
  cr=lambda ptr:ref(A2/'case_snapshot_candidate.json','/cards/'+str(i)+ptr)
  rr=ref(A3/'projection_sufficiency_review.json','/cards/'+str(i))
  assert resolve(r['card_ref'])==c and r['disposition']=='ARCHIVE_ONLY' and r['trusted_content_approval']=='PENDING'
  state=resolve(idx['public_prefix']);pool=resolve(idx['full_pool']);assert len(pool)==c['features']['candidate_count']['value']
  for group,prefix in [('buffer','box_'),('placed_objects','placed_')]:
   expected=[]
   for j,o in enumerate(state[group]):
    o=copy.deepcopy(o);o.pop('item_id');o['box_role']=prefix+str(j+1);expected.append(o)
   assert expected==c['structure'][group]
  pairs=[]
  for obs,pair in zip(c['observations'],idx['pairs']):
   comp=resolve(pair['comparison']);assert comp['evaluation']['label_v2']==obs['label']
   for role in ['A','B']:
    b=resolve(pair['branches'][role]);ex=resolve(pair['executions'][role])
    for k,v in obs[role].items():assert b['metrics'][k]==v
    assert ex['config']['runtime_identity']['strategy_identity']==c['continuation']['identity'];checked_branches+=1
   pairs.append(ref(ROOT/pair['comparison']['path']));checked_pairs+=1
  changed={k:v for k,v in c['attribute_directions'].items() if v!='EQUAL'};unchanged=[k for k,v in c['attribute_directions'].items() if v=='EQUAL']
  bindings=[]
  for k in s['attrs']:
   assert k in spec['role_binding']['role_attributes']
   bindings.append(dict(condition=k,status='REGISTERED_OBSERVABLE_A_B_ATTRIBUTE',fields=['actions.A.'+k,'actions.B.'+k],current_values={role:c['actions'][role]['attributes'][k] for role in ['A','B']},evidence=[cr('/actions/'+role+'/attributes/'+k) for role in ['A','B']],boundary='保存值是描述，不是从本卡收益拟合或冻结阈值。'))
  for k in s['conditions']:
   assert k in spec['features'];bindings.append(dict(condition=k,status='REGISTERED_SCENARIO_FEATURE',value=c['features'][k],evidence=[cr('/features/'+k),ref(A1/'scenario_feature_spec.json','/features/'+k)],boundary='有限标量不是完整结构指纹，不以相等断言经验适用。'))
  bindings.extend([dict(condition='局部墙距/支撑身份及邻接几何',status='SAVED_RAW_OBSERVABLE_BUT_NO_REGISTERED_GENERATION_PREDICATE',evidence=[cr('/structure'),cr('/actions'),rr],boundary='已有材料可供人工内容审阅；本轮不注册谓词或新增几何特征。'),dict(condition='连续空隙/可用顶面/承载路径/未来可装量',status='NOT_IMPLEMENTED_EXCLUDED_FROM_CONDITIONS',evidence=[ref(A1/'scenario_feature_spec.json','/not_implemented')],boundary='未实现不自动说明每卡均缺必要事实；若声明依赖这些量，则当前不支持该声明。'),dict(condition='未来箱/后续选择/PCT诊断',status='PRIVATE_OR_FUTURE_FORBIDDEN_AS_PUBLIC_PREDICATE',evidence=[ref(A2/'projection_contract.json','/private')],boundary='不要求把未来补入片段；也不使用测试成绩或私有反力解释。')])
  evidence=[cr('/structure'),cr('/actions'),cr('/observations'),cr('/continuation'),rr,ref(ROOT/idx['public_prefix']['path']),ref(ROOT/idx['full_pool']['path'])]+pairs
  matrix.append(dict(card_index=i,point_id=idx['point_id'],scope='PRIVATE_SUPPLEMENTAL_AUDIT_NOT_GENERATION_INPUT',tradeoff=dict(description=s['tradeoff'],changed=changed,unchanged_attributes=unchanged,multiple_factors_changed=len(changed)>1,box_property_and_pose_cochange=c['intervention']=='CROSS_BOX_SELECTION',intervention=c['intervention'],evidence=[cr('/actions'),cr('/attribute_directions')]),necessary_observable_conditions=dict(statement=s['necessary'],evidence=[cr('/structure'),cr('/actions')],bindings=bindings),retained_support_space_structure=dict(saved='完整观察到的箱体几何、缓冲属性和面积账本标量保留；不是仅保留特征均值。',specific=s['raw'],archived_A3_descriptive_geometry=r['dimensions'][0]['descriptive_geometry'],evidence=[cr('/structure'),rr],actual_new_geometry_computation='NOT_RUN_NOT_NEEDED'),unknowns=dict(direction_relevant_scope_gap=s['critical_unknown'],mechanism_only_not_additional_prerequisite=s['mechanism'],existing_records_gap=s['gap'],evidence=evidence),existing_public_record_answer=dict(action_identity_attributes_geometry='SUFFICIENT_FOR_THIS_SAVED_COMPARISON',outcomes_costs_continuation='SUFFICIENT_WITH_MONETARY_COST_UNKNOWN_DISCLOSED',registered_computable_condition_scope='PARTIAL',trusted_condition_and_direction_content='PENDING',claim_boundary=s['direction'],evidence=evidence),result_and_counterevidence=dict(observations=c['observations'],continuation=c['continuation'],evidence_grade=c['evidence_grade'],repeat_conflict=c['repeat_conflict'],evidence=[cr('/observations'),cr('/continuation'),cr('/evidence_grade'),cr('/repeat_conflict')]+pairs),deletion_rationale=dict(hypothetical_only=True,reason=s['delete'],expected='INSUFFICIENT_FOR_SAME_COMPARISON_OR_REJECT_OVERCLAIM',actual_deletion_test='NOT_RUN_CONTENT_REASONING_ONLY',evidence=[cr('/structure'),cr('/actions'),cr('/observations')]),disposition=dict(recommendation=s['disposition'],current='ARCHIVE_ONLY',trusted_content_approval='PENDING',generation_input_eligible=False,execution_eligible=False,necessary_followup='受信来源逐卡审核可观察条件、比较方向和声明范围；可保留/拒绝，无需所有卡通过，也不要求证明单因果。',reject_overclaim=s['reject'],no_new_collection_authorized=True,evidence=[rr,ref(A3/'review_source.json')]),analysis_source='DEVELOPER_AGENT_NOT_HUMAN_OR_TRUSTED_INDEPENDENT_APPROVAL'))
 assert len(matrix)==5 and checked_pairs==9 and checked_branches==18
 ch=read(C1/'handoff.json');assert len(ch['coverage_gaps'])==7 and len(ch['selected_point_class_gaps'])==5
 inherited=dict(C2=read(C2/'full_denominators.json'),source_support=read(C2/'source_and_start_support.json'),original_stage_gaps=ch['coverage_gaps'],original_class_gaps=ch['selected_point_class_gaps'],evidence=[ref(C2/'full_denominators.json'),ref(C2/'source_and_start_support.json'),ref(C1/'handoff.json','/coverage_gaps'),ref(C1/'handoff.json','/selected_point_class_gaps')],boundaries='synthetic packaging; feasibility UNKNOWN; predicted static instability only; historical57 requests/75 commits are not current operations')
 write('inherited_boundaries.json',inherited)
 write('review_source.json',dict(version='jm2_b1_content_check_review_source_v1',actual_author='Codex current development session',role='DEVELOPER_ANALYSIS_NOT_TRUSTED_CONTENT_APPROVAL',human_signature=None,independent_reviewer=None,verifiable_trusted_authorization=None,status='PENDING',prior_source=ref(A3/'review_source.json'),method='saved evidence audit and explicit noncausal scope reasoning; no external model calls',not_an_approval=True))
 write('per_card_supplement_matrix.json',dict(version='jm2_b1_content_supplement_v1',cards=matrix,conclusion='Facts and many observable distinctions are already saved; mechanism proof is not an added prerequisite. Trusted scoped content approval and computable predicate coverage are not established.',qualified_real_inputs=0,content_status='NOT_READY',source=ref(OUT/'review_source.json')))
 write('evidence_index.json',dict(version='jm2_b1_content_evidence_index_v1',references=list(REFS.values()),parent_manifests=parents,production_source_files_exact=len(source),checked_saved_pairs=checked_pairs,checked_saved_branches=checked_branches,checks='path/SHA256/JSON pointer; exact saved values; no tolerance or digest exemption'))
 write('experience_generation_readiness.json',dict(version='jm2_b1_content_check_readiness_v1',engineering_status='COMPLETE_SCOPED_SUPPLEMENT_PENDING_QA',evidence_readiness='SAVED_FACTS_AUDITED_TRUSTED_SCOPE_REVIEW_PENDING',research_result='NOT_ESTABLISHED',admission='NOT_READY',next_stage_admission='NOT_READY',B2_C='NOT_READY',qualified_real_cards=0,archive_only=5,trusted_content_approval='PENDING_5',M21_07='PARTIAL_CONTENT',M22_03='PARTIAL_CONTENT',M22_07='PARTIAL_REAL_CONTENT_NOT_RUN',full_B1_exit='NOT_CLOSED',qualified_generation_input=False,execution_eligible=False,mechanism_proof_required=False,missing_material_policy='UNKNOWN_NOT_RUN_NOT_FAKE_ZERO',actual_operations={k:0 for k in ['credentials_read','model_calls','orders','forks','candidate_reconstruction','prefix_replay','stability_solves','subagents']}))
 write('source_identity.json',dict(version='jm2_b1_content_check_identity_v1',actual_head=head,production_changes=0,production_source_manifest=ref(FIX/'source_manifest.json'),production_source_identity=ref(FIX/'source_identity.json'),historical_identity_resigned=False,audit_tool=entry(OUT/'build_supplement.py'),python=sys.version,platform=platform.platform(),dependencies='stdlib only; no installs or production imports'))
 write('entry_identity.json',dict(root=str(ROOT),branch=git('branch','--show-current'),upstream=git('rev-parse','--abbrev-ref','--symbolic-full-name','@{upstream}'),actual_head=head,reviewed_development='4b8bc0f77e453394ce960e8023caef42e9e98a0d',before_pull='4b8bc0f77e453394ce960e8023caef42e9e98a0d',initial_workspace='CLEAN',pull='fast-forward; first sandbox FETCH_HEAD read-only, authorized escalation succeeded',stash_reset_force_push=False,commit_push='NOT_PERFORMED',SKILL='EXCLUDED_ENTIRE_TREE'))
 write('check_attempts.json',dict(version='jm2_b1_content_check_attempts_v1',current='saved fact/reference audit only; no behavior or historical execution rerun',historical_QA_probe_results=ref(QA/'probe_results.json'),historical_tests='archived51 and QA24 remain historical; not claimed as local reruns',not_run=['trusted human/independent approval','generation','candidate or geometric feature reconstruction','hypothetical deletion execution','model/order/fork/replay/LP'],unexpected_failures=[dict(attempt='saved_attempt_01.log',error='parent manifest exact-byte assertion',cause='A2 two registry source entries predate later B1 implementation; live code differs by already documented historical changes',correction='compare A2 original registry bytes from existing B1 entry_source_bytes; current517 verified independently against FIX source manifest; no source or digest changed'),dict(attempt='delivery_attempt_01.log',error='own stdout log changed after manifest capture',cause='shell redirected builder stdout to a file captured before its final print',correction='finish logs, then finalize manifest without redirecting stdout into a captured file; no parent files affected')]))
 write('handoff.json',dict(version='jm2_b1_content_check_handoff_v1',date='2026-11-16',actual_head=head,unit='B1 real-content prerequisite supplemental audit only',parent_QA=ref(QA/'handoff.json'),report=REPORT,matrix='per_card_supplement_matrix.json',evidence='evidence_index.json',review_source='review_source.json',boundaries='inherited_boundaries.json',readiness='experience_generation_readiness.json',source='source_identity.json',checks='check_attempts.json',manifest='delivery_manifest.json',engineering_status='COMPLETE_SCOPED_SUPPLEMENT_PENDING_QA',evidence_readiness='SAVED_FACTS_AUDITED_TRUSTED_SCOPE_REVIEW_PENDING',research_result='NOT_ESTABLISHED',admission='NOT_READY',next_stage_admission='NOT_READY',B2_C='NOT_READY',qualified_real_cards=0,stop=True,return_to='INDEPENDENT_QA',stop_reason='补核完成交回独立质检；不生成、不推进B2/C、不编写下一任务提示词'))
 paths=[p for p in OUT.iterdir() if p.is_file() and p.name!='delivery_manifest.json']+[ROOT/REPORT]
 write('delivery_manifest.json',dict(version='jm2_b1_content_check_manifest_v1',self_hash_excluded=True,excluded=['SKILL/ entire tree','shared navigation README','__pycache__'],files=[entry(p) for p in sorted(paths)]))
 print('PASS_SAVED_SUPPLEMENT_5_CARDS_9_PAIRS_18_BRANCHES; PRODUCTION_UNCHANGED_517; CONTENT_NOT_READY')
if __name__=='__main__':main()

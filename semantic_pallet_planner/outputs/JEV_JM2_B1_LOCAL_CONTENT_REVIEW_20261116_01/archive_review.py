"""Archive actual user-designated local content judgments; stdlib saved checks only.
Writes own new directory; read-only Git metadata subprocesses; no production imports.
"""
import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent;BASE=ROOT/'semantic_pallet_planner/outputs'
A2=BASE/'JEV_JM2_A2_20261115_01';A3=BASE/'JEV_JM2_A3_20261115_01';SUP=BASE/'JEV_JM2_B1_CONTENT_CHECK_20261116_01';QA=BASE/'JEV_JM2_B1_CONTENT_QA_20261116_01';FIX=BASE/'JEV_JM2_B1_FIX_20261115_01'
REPORT='docs/03_阶段产出分析/Jev/Jev_JM2-B1用户指定本地五卡内容审核_20261116_01.md'
def read(p):return json.loads(p.read_text())
def write(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p,ptr=''):return dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p),pointer=ptr)
def entry(p):return dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p),bytes=p.stat().st_size)
def git(*a):return subprocess.check_output(['git',*a],cwd=ROOT,text=True).strip()
JUDGMENTS=[
 dict(accepted='本点两次B装入体积更多，件数更多，但垛高方向冲突且请求和时长增加；事实必须整体保留。',rejected='贴墙必然改善、B总降低垛高或全面无代价改善。',rationale='有具体位置差和重复结果，足以陈述局部事实；目前没有可观察条件把垛高相反的两次结果分开。未定义可迁移位置偏好所需局部结构范围，不能仅用y方向或墙距赋予统一优选方向。',expression='y_over_width/base_over_height/yaw等已注册；墙距及邻接几何可人工核对，尚不是注册生成谓词。',critical='如要声明垛高优势，冲突直接反驳；如仅陈述体积局部差，机制UNKNOWN不妨碍事实。生成方向的上下文边界尚未确定。'),
 dict(accepted='在保存的联合配置比较中，B较矮且容量参数更高，但两次装入体积更少；同时高度和时长较低。',rejected='容量更大必更好、更矮必装更多，或容量/尺寸某一项单因果解释。',rationale='两次局部负向事实可以保留，不要求隔离单属性因果；但现有内容没有确定哪些共同公开结构足以界定联合负向偏好的适用范围。只写容量或平均尺寸会丢掉支撑位置/姿态和多属性取舍。',expression='尺寸/质量/容量/x与底高可绑定现有属性；placed_3局部承接关系保留在原几何，但缺专用注册谓词。',critical='单因果机制未知不是拒绝理由；联合配置的可计算适用范围尚未审定，故不签发可生成方向经验的充分输入资格。'),
 dict(accepted='两次注册主要指标中性，两个位置不同；box_2和同属性box_3仍是不同箱体。',rejected='布局、位置或同属性箱普遍等价。',rationale='中性事实完整且有保存支撑几何，无需先解释为何中性；它没有提供某角色优于另一角色的方向。若要表述安全等价范围，现有材料未给出足够的可观察边界。',expression='stackable/y/base与阶段量可注册表达；细小支撑边距和布局等价未实现为规则谓词。',critical='未知中性成因不影响承认指标中性；不得把中性自动升级为替代动作可互换。'),
 dict(accepted='单次联合换箱/支撑位置/朝向比较，装入量相同而B高40mm、包络利用率降低。',rejected='旋转或换箱单独导致退化，或声称局部重复支持。',rationale='单次不是自动禁止留档或审核的理由，也无需证明旋转因果；但输入尚不能把联合配置的空间条件界定为可计算的比较范围，且必须维持单次等级。',expression='yaw/尺寸/质量/x/y及底高可表达；两处支撑箱身份及局部结构关系没有专用注册生成谓词。',critical='多因素贡献UNKNOWN可作为假设保留；不能删掉支撑/朝向差异后宣称同类干预，当前只适合完整联合事实档案。'),
 dict(accepted='同箱地板平移，两次体积增加33190500mm³且质量增加，件数/垛高不变，时长差方向不同。',rejected='必然释放可用空间、装更多件或耗时更低。',rationale='重复的局部装入组成差可以记录，无需证明空间释放机制；如果方向依赖相邻三层垛和局部空隙，现有注册特征还不能界定该范围，不能以墙距或总体包络替代。',expression='x/y/base/stackable及总体结构特征已注册；连接空隙/可用面未实现。',critical='机制UNKNOWN不否定历史体积事实；未来箱不得补作条件，当前没有经内容审定的可计算迁移边界。')]
def main():
 head=git('rev-parse','HEAD');assert head=='860da9f9684f07d30c29f1a1139f7b9424509b29'
 for folder in [QA,SUP]:
  for e in read(folder/'delivery_manifest.json')['files']:
   p=ROOT/e['path'];assert sha(p)==e['sha256'] and p.stat().st_size==e['bytes']
 source=read(FIX/'source_manifest.json')
 for n,d in source.items():assert sha(ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'/n)==d
 write('authorization_and_source.json',dict(version='jm2_b1_user_designated_local_review_source_v1',date='2026-11-16',actual_reviewer='Codex in current conversation',authorization_source='USER_MESSAGE_IN_CURRENT_CONVERSATION',authorization_quote='指定当前质检窗口承担五卡独立内容审核，按既有方案逐卡给出结论并归档；仅限本地审核，真实模型 API 调用为 0，不进入 B2/C。',message_id='NOT_AVAILABLE',authorized_role='USER_DESIGNATED_LOCAL_CONTENT_REVIEWER',scope='five saved T cards: observable preconditions, comparison direction, claim scope, cost/counterevidence, registered expression, UNKNOWN disposition',prior_participation='Same Codex conversation previously participated in development and supplemental analysis.',independence_disclosure='User designated review role; not a separate person, external reviewer, isolated session or blind review. Independent organizational separation is NOT_ESTABLISHED.',human_signature=None,external_model=None,review_performed=True,permission_to_modify_old_gate=False,permission_for_B2_C=False))
 cards=read(A2/'case_snapshot_candidate.json')['cards'];supp=read(SUP/'per_card_supplement_matrix.json')['cards'];private=read(A2/'private_audit_index.json')['cards'];reviews=[]
 for i,(c,s,j,idx) in enumerate(zip(cards,supp,JUDGMENTS,private)):
  cr=lambda p:ref(A2/'case_snapshot_candidate.json','/cards/'+str(i)+p)
  evidence=[cr('/actions'),cr('/structure'),cr('/observations'),cr('/continuation'),cr('/attribute_directions'),ref(SUP/'per_card_supplement_matrix.json','/cards/'+str(i)),ref(A3/'projection_sufficiency_review.json','/cards/'+str(i))]
  for pair,obs in zip(idx['pairs'],c['observations']):
   comp=read(ROOT/pair['comparison']['path']);assert comp['evaluation']['label_v2']==obs['label'];evidence.append(pair['comparison'])
   for role in ['A','B']:
    b=read(ROOT/pair['branches'][role]['path']);assert all(b['metrics'][k]==v for k,v in obs[role].items());evidence.append(pair['branches'][role])
  reviews.append(dict(card_index=i,point_id=s['point_id'],card_ref=cr(''),review_status='COMPLETED_LOCAL_CONTENT_REVIEW',decision='ARCHIVE_ONLY',generation_input_decision='NOT_QUALIFIED_FOR_DIRECTIONAL_GENERATION',factual_content_assessment='ACCEPT_WITH_STATED_SCOPE_AND_COUNTEREVIDENCE',accepted_factual_scope=j['accepted'],rejected_claims=j['rejected'],observable_preconditions=s['necessary_observable_conditions'],comparison_direction=dict(local=s['existing_public_record_answer']['claim_boundary'],generalized_preference='NOT_APPROVED'),claim_scope_review=j['rationale'],cost_and_counterevidence=dict(status='RETAINED',monetary_cost='UNKNOWN',observations=c['observations'],grade=c['evidence_grade'],repeat_conflict=c['repeat_conflict'],continuation=c['continuation']),registered_condition_expression=j['expression'],unknown_effect_on_disposition=j['critical'],causal_proof_required=False,source=ref(OUT/'authorization_and_source.json'),evidence=evidence,qualified_generation_input=False,execution_eligible=False))
 write('per_card_content_review.json',dict(version='jm2_b1_actual_local_content_review_v1',date='2026-11-16',object='five saved T cards as directional E-generation prerequisites; no generated E card exists for review',source=ref(OUT/'authorization_and_source.json'),cards=reviews,summary=dict(reviewed=5,archive_only=5,qualified_real_generation_inputs=0,local_review_completed=5,approved_generalized_directions=0),independence='Designated role with disclosed same-session prior involvement; not claimed to be a separate blind/organizational reviewer.'))
 boundary=read(SUP/'inherited_boundaries.json');write('inherited_boundaries.json',boundary)
 write('experience_generation_readiness.json',dict(version='jm2_b1_local_review_readiness_v1',engineering_status='COMPLETE_AUTHORIZED_LOCAL_REVIEW_PENDING_QA',evidence_readiness='LOCAL_CONTENT_DECISIONS_RECORDED_SCOPE_LIMITS_REMAIN',research_result='NOT_ESTABLISHED',next_stage_admission='NOT_READY',B2_C='NOT_READY',full_B1_exit='NOT_CLOSED',review_authorization='PRESENT_USER_DESIGNATED_LOCAL',review_execution='COMPLETED_5',organizational_independence='NOT_ESTABLISHED_SAME_SESSION_DISCLOSED',qualified_real_cards=0,archive_only=5,generated_E_content_review='NOT_RUN_NO_GENERATED_E_OBJECT',M21_07='LOCAL_REVIEW_RECORDED_OVERALL_NOT_UPGRADED',M22_03='PARTIAL',M22_07='PARTIAL_NO_QUALIFIED_REAL_DIRECTIONAL_CONTENT',old_card_status_changed=False,old_gate_changed=False,qualified_generation_input=False,execution_eligible=False,actual_operations={k:0 for k in ['credentials_read','model_API_calls','orders','forks','candidate_reconstruction','prefix_replay','stability_solves','subagents']}))
 write('source_identity.json',dict(version='jm2_b1_local_review_identity_v1',actual_head=head,production_changes=0,production_manifest=ref(FIX/'source_manifest.json'),production_files_checked=len(source),python=sys.version,audit_script=entry(OUT/'archive_review.py'),historical_identity_resigned=False))
 write('handoff.json',dict(version='jm2_b1_local_content_review_handoff_v1',date='2026-11-16',actual_head=head,report=REPORT,authorization='authorization_and_source.json',review='per_card_content_review.json',readiness='experience_generation_readiness.json',boundaries='inherited_boundaries.json',source='source_identity.json',manifest='delivery_manifest.json',next_stage_admission='NOT_READY',return_to='INDEPENDENT_QA',qualified_real_cards=0,stop=True,limits='No old gate/card changes, no generation/B2/C; same-session prior involvement disclosed.'))
 files=[p for p in OUT.iterdir() if p.is_file() and p.name!='delivery_manifest.json']+[ROOT/REPORT]
 write('delivery_manifest.json',dict(version='jm2_b1_local_review_manifest_v1',self_hash_excluded=True,excluded=['SKILL/ entire tree','shared navigation README','__pycache__'],files=[entry(p) for p in sorted(files)]))
 print('ARCHIVED_LOCAL_CONTENT_DECISIONS_5; ARCHIVE_ONLY_5; QUALIFIED0; API0; SOURCE517_UNCHANGED')
if __name__=='__main__':main()

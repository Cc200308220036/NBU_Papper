"""Assemble A1 engineering receipts and report, without runtime/credential imports."""
import ast,base64,hashlib,importlib.metadata,json,os,subprocess,sys
from pathlib import Path
from semantic_pallet_planner.jev_select import packaging_scenario_features as m

ROOT=Path.cwd();OUT=Path(__file__).resolve().parent
PACKAGE=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
BASE=ROOT/'semantic_pallet_planner/outputs'
C2=BASE/'JEV_JM1_C2_REAL_SUFFIXES_20261113_01'
B2=BASE/'JEV_JM1_B2_FREEZE_CLOSURE_20261112_01'
QA=BASE/'JEV_JM_C2_REAL_QA_20261113_01'
def read(p):return json.loads(Path(p).read_text())
def write(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')
def rel(p):return Path(p).resolve().relative_to(ROOT).as_posix()
def ref(p):
    p=Path(p);return dict(path=rel(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def source(suffixes):
    return {p.relative_to(PACKAGE).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(PACKAGE.rglob('*')) if p.is_file() and p.suffix in suffixes and
            not {'tests','__pycache__'}.intersection(p.relative_to(PACKAGE).parts)}

entry=read(OUT/'entry_identity.json');saved=read(OUT/'saved_public_validation.json')
assert saved['status']=='PASS' and len(saved['points'])==5
assert '\nOK\n' in (OUT/'tests_final.stderr').read_text()
# unittest's failing subTest line contains a trailing space. Preserve exact raw
# stderr with SHA/base64, and keep a whitespace-clean text display for Git.
failed_log=OUT/'tests_attempt_01.stderr';raw_archive=OUT/'tests_attempt_01.stderr.raw.json'
if not raw_archive.exists():
    raw=failed_log.read_bytes()
    write(raw_archive,dict(version='jm2_a1_raw_test_log_v1',encoding='base64',
          bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),raw_base64=base64.b64encode(raw).decode(),
          text_display='tests_attempt_01.stderr; only trailing line whitespace removed'))
raw=base64.b64decode(read(raw_archive)['raw_base64']);assert hashlib.sha256(raw).hexdigest()==read(raw_archive)['sha256']
failed_log.write_text('\n'.join(line.rstrip() for line in raw.decode().splitlines())+'\n')
frozen=read(B2/'source_manifest.json');runtime=source(('.py','.json'))
changed={k:dict(before=v,after=runtime.get(k)) for k,v in frozen.items() if runtime.get(k)!=v}
assert set(changed)=={'jev_select/contracts.py','jev_select/packaging_versions.py'},changed
assert not set(frozen)-set(runtime)
new_files=sorted(set(runtime)-set(frozen))
assert set(new_files)=={'jev_select/packaging_scenario_features.py',
       'jev_select/schemas/jm_scenario_input_v1.schema.json',
       'jev_select/schemas/jm_scenario_signature_v1.schema.json',
       'jev_select/schemas/jm_action_contrast_v1.schema.json'},new_files
for file in ('contracts.py','packaging_versions.py'):
    assert hashlib.sha256((OUT/'entry_source_bytes'/file).read_bytes()).hexdigest()==frozen['jev_select/'+file]
write(OUT/'source_manifest.json',runtime)
old_schemas=[k for k in frozen if '/schemas/' in k or '/configs/' in k]
assert all(runtime[k]==frozen[k] for k in old_schemas)
write(OUT/'source_identity.json',dict(version='jm2_a1_source_identity_v1',date='2026-11-15',entry_head=entry['head'],
      entry_python=sys.executable,python=sys.version,platform=sys.platform,uname=list(os.uname()),
      dependencies={n:importlib.metadata.version(n) for n in ('jsonschema','numpy','scipy','pytest')},
      dependencies_imported_for_features=False,manifest=ref(OUT/'source_manifest.json'),source_digest=m.digest(runtime),
      previous_frozen_source_digest=m.digest(frozen),changed_existing_files=changed,added_files=new_files,
      old_schema_config_files_unchanged=len(old_schemas),old_freeze_identity=read(B2/'formal_freeze.json')['receipt_digest'],
      historical_identity_resigned=False,new_engineering_identity=True,
      recovery='Old v13 source identity is expected to differ. Do not use new source to resume old frozen executions; no historical validator was bypassed or old digest rewritten.'))
imports=[]
for path in (PACKAGE/'jev_select/packaging_scenario_features.py',PACKAGE/'jev_select/packaging_jev_sampling.py',PACKAGE/'jev_select/packaging_versions.py'):
    tree=ast.parse(path.read_text());rows=[n.module if isinstance(n,ast.ImportFrom) else ','.join(a.name for a in n.names) for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom))]
    imports.append(dict(file=ref(path),top_level_imports=rows))
write(OUT/'import_and_side_effect_review.json',dict(version='jm2_a1_import_review_v1',files=imports,
      feature_module='stdlib + existing stdlib-only sampling helpers and version constants',
      static_schema_reads='only package-local closed schema JSON; no dynamic execution at import',
      verification='tests install meta-path import blocker and audit hook before importing A1 module',
      forbidden_operations=saved['side_effect_audit'],blocked_imports=saved['imports_blocked'],
      actual_credentials_read=0,actual_model_calls=0,actual_orders=0,actual_candidate_generation=0,actual_LP=0))
write(OUT/'check_attempts.json',dict(version='jm2_a1_check_attempts_v1',attempts=[
      dict(name='tests_attempt_01',status='FAIL',exit_code=1,tests=13,failures=1,
           reason='P03 historical/current area remaining capacity mismatch: current effective permission is zero for nonstackable boxes',
           correction='A1 adapter now derives area remaining from observed max_top_load_kg-current_top_load_kg; added targeted test; originals untouched'),
      dict(name='tests_attempt_02',status='PASS',exit_code=0,tests=14),
      dict(name='saved_public_attempt_01',status='FAIL',exit_code=1,
           reason='B2 manifest pins old packaging_versions.py; authorized A1 additive registration changes live source',
           correction='verify historical binding against entry Git blob with exact saved SHA; explicitly record new source identity, never re-sign old freeze'),
      dict(name='tests_final',status='PASS',exit_code=0,tests=14),
      dict(name='saved_public',status='PASS',exit_code=0,real_saved_points=5)],
      retained_logs=True,initial_stderr_raw_archive='tests_attempt_01.stderr.raw.json',
      text_log_normalization='trailing line whitespace only; exact original raw bytes/SHA/base64 retained',
      model_or_order_failures_from_these_checks=0))
write(OUT/'test_receipt.json',dict(version='jm2_a1_test_receipt_v1',engineering_tests=14,final_status='PASS',
      unit_command='PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src python3 -m unittest discover -s semantic_pallet_planner/tests/unit -p test_packaging_scenario_features.py -v',
      public_command='PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src python3 '+rel(OUT/'verify_saved_public.py'),
      final_stdout=ref(OUT/'tests_final.stdout'),final_stderr=ref(OUT/'tests_final.stderr'),
      saved_public=ref(OUT/'saved_public_validation.json'),
      scope='14 targeted pure-local tests; 5 saved nonempty historical/current inputs; no full historical suite or runtime validator',
      legacy_regression='actual historical_fragment still refuses nonempty histories; all old schema/config bytes unchanged',
      failure_records='check_attempts.json',historical_orders_or_fault_injection='NOT_RUN',models=0,LP=0))
write(OUT/'interface_receipt.json',dict(version='jm2_a1_interface_receipt_v1',module='semantic_pallet_planner.jev_select.packaging_scenario_features',
      protocols=m.JM_SCENARIO_SCHEMAS,registry='packaging_versions.JM_SCENARIO_PROTOCOLS / JM_SCENARIO_SCHEMAS; contracts.schema_validator whitelist additive only',
      functions=['make_input(state,pool,expected_pool_count=...,expected_pool_digest=...)',
        'from_saved_public(state,pool,expected_pool_count=...,expected_raw_pool_digest=...)',
        'from_current_public(model_state,criteria,expected_candidate_labels=...)',
        'build_signature(public_input)','bind_contrast(history,a_id,b_id,current=None)','feature_spec()','validate(value)'],
      validation='validate checks closed schema and output seal; validate_input additionally checks pool attestation, identity uniqueness and orientation consistency; consumers must recompute from bound input to authenticate feature semantics',
      completeness_boundary='Count/digest come from a trusted complete producer. Function cannot infer actual upstream completeness from a self-declared two-action subset. Evidence audit checks original SHA, full saved projection mapping and all rows.',
      current_normalization='area remaining=max_top_load_kg-current_top_load_kg, not effective remaining permission',
      roles='A/B are reference/alternative diagnostic roles, not best/worst; different local item IDs are never merged by equal attributes',
      old_historical_fragment='UNCHANGED_NONEMPTY_REFUSAL',T_snapshot='NOT_IMPLEMENTED_A2_OUT_OF_SCOPE',retrieval='NOT_IMPLEMENTED_JM3_OUT_OF_SCOPE',execution_eligibility=False))
acceptance=[dict(id='M21-02',status='PASS_A1_ENGINEERING',evidence='14 targeted tests + saved_public_validation: 5 nonempty points, same function and all full-pool features equal; missing vs empty distinct'),
            dict(id='M21-05',status='PASS_A1_ENGINEERING_ONLY',evidence='equal-buffer/different structure; translation/rotation/cross-box noninterchangeability; deleted context refusal; identical-attribute boxes retain distinct roles'),
            dict(id='M21-01/03/04/06/07',status='NOT_RUN_OUTSIDE_A1',evidence='No A2 T projection/snapshot or A3 per-card sufficiency review'),
            dict(id='EXPERIENCE_APPLICABILITY_BENEFIT_EXECUTION',status='NOT_ASSESSED_NOT_GRANTED',evidence='A1 computability and diagnostic correspondence are not applicability, transfer, policy benefit or execution qualification'),
            dict(id='INHERITED_C2_COVERAGE',status='PARTIAL_PRESERVED',evidence='opening0/6, nonempty5/6, 7 stage +5 category gaps, independent unseen0, cross-start support per family0; P01 conflict/P04 single retained')]
write(OUT/'acceptance.json',dict(version='jm2_a1_acceptance_v1',items=acceptance,
      engineering_status='COMPLETE_A1_DECLARED_SCOPE_PENDING_INDEPENDENT_QA',evidence_readiness='SAVED_PUBLIC_AND_CONSTRUCTED_ENGINEERING_CHECKS_PASS',
      research_result='NOT_ASSESSED_NO_NEW_EXPERIENCE_OR_BENEFIT_CLAIM',next_stage_admission='INDEPENDENT_QA_ONLY',stop=True))
inherited=read(C2/'evidence_levels_and_conflicts.json')
write(OUT/'inherited_evidence_boundary.json',dict(version='jm2_a1_inherited_boundary_v1',
      parent=ref(C2/'evidence_levels_and_conflicts.json'),points=[{k:p[k] for k in ('point_id','labels','evidence_grade','repeat_conflict','repeat_registered')} for p in inherited['points']],
      preservation='No family regrouping/positive resampling or grade upgrade; used to describe boundaries only, not passed to feature functions',
      C2_original_labels=read(C2/'full_denominators.json')['pair_labels'],cross_start_support=0,independent_unseen_sources=0,coverage='PARTIAL'))
report=ROOT/'docs/03_阶段产出分析/Jev/Jev_JM2-A1共同场景特征与动作关系工程验收_20261115_01.md'
lines=['# JM2-A1共同场景特征与动作关系工程验收','',
       '日期2026-11-15；JM-plan-v2。本单元仅实现共同公开特征与动作关系诊断，完成后交回独立质检。**M21-02及M21-05属于A1的工程要求通过；不关闭A2/A3内容验收，不生成T快照，不授予适用性或执行资格。**','',
       '## 基线、同步和输入','',
       '已有根目录`NBU_Papper`，分支`dev/jev-select`、upstream `origin/dev/jev-select`，入口工作区和暂存区干净。先执行git pull --ff-only：两次SSH22连接超时，随后仅本次命令使用SSH443并严格验证已有主机密钥成功；没有修改remote/Git配置、stash/reset或强推。实际入口HEAD `'+entry['head']+'`，包含QA提交3fbb0169。根AGENTS适用，无子目录AGENTS。','',
       '读取主方案4.2、7.1/7.1.1，C2独立质检报告及QA四件、C2 handoff/manifest/dataset/分支/比较/起点/证据等级/材料准入，并沿C1交接定位真实公开prefix、完整pool、public投影及已存当前context。未读取凭证，没有模型调用、订单/分叉执行、候选重建、前缀重放或稳定性求解；没有安装依赖、启动子代理。','',
       '## 实现与复用','',
       '新增`jev_select/packaging_scenario_features.py`，复用现有标准库采点模块的canonical digest和封闭Schema校验子集，不导入订单、候选器、transport或稳定性模块。新增三个独立v1协议：scenario input、scenario signature、action contrast；对应三个封闭Draft202012 Schema。集中在packaging_versions登记模块/Schema路由，contracts仅增加三个Schema白名单项；旧Schema和旧historical_fragment非空拒绝保护保持。实际函数签名见interface_receipt.json，未将方案拟议名称冒称旧接口。','',
       '历史公开prefix/完整保存pool与当前公开model_state/criteria经适配器规范为相同输入，再由同一个build_signature计算。候选统计以完整池一候选一票，同一箱多个位置各计一次；缓冲均值以全部缓冲箱一箱一票。完整性由上游完整池count/digest绑定，真实验证另核对源文件SHA、原public映射和全部候选；函数不能从自声明的两个动作子集自行证明上游完整性。缺池为MISSING，真实空池计数为0且均值NA，二者分开。','',
       '首版'+str(len(m.feature_spec()['features']))+'个有限特征覆盖缓冲尺寸/质量/包装承载/stackable分布、已放体积/高度/投影联合/包络跨度与中心位置、精确面接触数量、顶面层数、未扣遮挡的可堆叠毛面面积、公开面积剩余承载合计及完整候选池统计。坐标为容器底面中心、XY箱中心、z为箱底、0/90度轴对齐；投影联合和精确面接触只描述保存几何，不调用物理检查或PCT、不代表可装空间或稳定性。各字段单位、总体、公式、缺失/空总体/边界/不截断及计算成本见scenario_feature_spec.json。','',
       '连续空隙、可用外露顶面、承载路径、未来可装体积及PCT反力特征明确NOT_IMPLEMENTED，并排除出绑定条件。面积账本承载合计不是未来可用空间或可装箱数。没有用删除旧保护、放宽旧Schema或修改候选器/物理容差/承载参数/监测算法接入新协议。','',
       '## 动作角色与有限诊断边界','',
       'A/B绑定记录两个精确动作、匿名箱角色、变化/不变属性、结构和容器不变条件、属性方向、当前全部有序对应对与两侧候选集合、无法对应条件及歧义。按真实本地箱ID区分角色，不按属性相同合并箱体；区分同箱平移、旋转、平移加旋转、跨箱与相同行为。','',
       'v1只采用精确结构条件相等、同干预类别及逐属性方向一致的保守诊断；无学习阈值，没有检索排序、优选动作或经验准入。缺关键条件/角色字段则拒绝对应；多个匹配全部保留为AMBIGUOUS_DIAGNOSTIC。五个真实起点均存在多个对应，这不是唯一动作推荐，更不代表经验适用或有效。','',
       '## 本机验证和失败记录','',
       '执行前检查导入：核心为标准库及现有无派发采点工具；测试在导入A1前安装meta-path阻断器和审计钩子，禁止o4/planner/episode/transport/selector/execution/stability/numpy/scipy导入、凭证文件读取、网络连接和子进程派发。验证只读保存JSON与构造数据，不运行模型、订单或LP。','',
       '最终14项定向unittest通过；覆盖同函数同总体、完整池不能用两动作替代、均值相同但支撑/投影结构不同、同箱与跨箱不可互换、旋转类别、删关键条件、缺池与空池、同属性不同箱体、别名不变性、多对应不暗选、非法数值/坐标/Schema、中央路由及旧非空拒绝。未运行整套历史行为测试、订单或生产恢复validator；不将历史测试声明为本次通过。','',
       '首轮13项中1项失败：P03不可堆叠箱的当前remaining_top_load_kg是有效许可口径，历史area_remaining_top_load_kg为原包装承载减已承载量。仅修正新A1适配器，用公开max_top_load_kg-current_top_load_kg对齐，并增加定向测试；不读取未来或PCT，不改原记录。随后14项通过。保存审计首轮另因B2清单固定旧packaging_versions字节中止，改为核对入口Git blob并显式记录本次新源码差异，不重签旧摘要。全部失败日志及修正保存在check_attempts.json。','',
       '| 真实保存起点 | 完整池数 | 历史/当前全部特征 | 实际动作对应 |','|---|---:|---|---|']
for p in saved['points']:lines.append('| '+p['point_id']+' | '+str(p['pool_count'])+' | 一致 | '+p['binding_status']+'；'+str(p['pair_count'])+'对 |')
lines+=['', '共5个真实非空起点、220个池内候选观察，3点同箱/2点跨箱。字段来源、完整总体、源路径/SHA及JSON指针保存在field_origin_index.json；输出留在saved_public_checks/，构造反例另标CONSTRUCTED_ONLY，不冒充真实研究证据。','',
        '## 身份与原件保护','',
        '新运行源码集合为'+str(len(runtime))+'文件，原冻结505文件中仅contracts.py和packaging_versions.py因新增Schema/版本登记发生预期差异，其余503字节不变；新增纯特征模块和三Schema。旧Schema/config共'+str(len(old_schemas))+'文件字节未变。新source_manifest/source_identity独立记录本次源码、依赖及入口身份。旧B2/C1/C2收据、manifest及冻结身份不回写。','',
        'B2交付清单中旧packaging_versions.py绑定通过入口提交Git blob原字节与原SHA验证；活动文件已属于新工程身份，不能声称旧生产validator在新源码上仍通过。旧v13源码身份预期拒绝该差异，不使用新源码恢复旧冻结执行，不绕过保护、不重签历史摘要。其余交付原件核对结果见saved_public_validation.json。','',
        '## 验收、限制和停止','', '| ID | 状态 | 范围 |','|---|---|---|']
for a in acceptance:lines.append('| '+a['id']+' | '+a['status']+' | '+a['evidence']+' |')
lines+=['', '继承C2的P01指标冲突、P04单次、全部退化/中性和M13-05覆盖PARTIAL；每族跨起点支持0、独立未见来源0不因特征可计算而升级。几何属性和承载仍受合成属性、均匀刚性箱、轴对齐及准静态研究范围限制；本阶段没有新增稳定性或因果证据。','',
        '本单元只关闭A1的工程要求。A2非空T投影/快照、A3摘要审核、B审核生成工程、C真实提炼、JM3检索及后续执行均NOT_RUN；实际14项测试不替代这些验收。下一准入仅INDEPENDENT_QA_ONLY，不自行决定下一阶段。','',
        '实际命令：','', '```sh',
        'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src python3 -m unittest discover -s semantic_pallet_planner/tests/unit -p test_packaging_scenario_features.py -v',
        'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src python3 '+rel(OUT/'verify_saved_public.py'),
        'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src python3 '+rel(OUT/'verify_delivery.py'),
        'git diff --check','```','',
        '交付入口：`'+rel(OUT)+'/`，包含scenario_feature_spec、逐字段来源、真实公开检查/构造反例、导入副作用审查、测试及失败记录、接口、源码身份、逐项验收、handoff与delivery_manifest。整个SKILL/不归档；没有生成A2的T快照或下一任务提示词。完成本单元后停止交回独立质检。']
report.write_text('\n'.join(lines)+'\n')
idx=report.with_name('README.md');text=idx.read_text();line='\n- [JM2-A1共同场景特征与动作关系工程验收]('+report.name+')：独立公开特征/动作诊断协议，14项纯本地验证与5个真实非空状态同口径检查；仅A1工程，待独立质检，未进入A2/A3。\n'
if report.name not in text:idx.write_text(text+line)
write(OUT/'handoff.json',dict(version='jm2_a1_handoff_v1',date='2026-11-15',plan='JM-plan-v2',unit='JM2-A1 only',entry_head=entry['head'],
      parent_qa=ref(QA/'handoff.json'),parent_admission=ref(QA/'next_stage_admission.json'),parent_C2=ref(C2/'handoff.json'),
      module='semantic_pallet_planner.jev_select.packaging_scenario_features',interfaces='interface_receipt.json',feature_spec='scenario_feature_spec.json',
      evidence='field_origin_index.json',saved_validation='saved_public_validation.json',constructed='constructed_counterexamples.json',
      tests='test_receipt.json',failures='check_attempts.json',source='source_identity.json',source_manifest='source_manifest.json',
      inherited_boundaries='inherited_evidence_boundary.json',acceptance='acceptance.json',manifest='delivery_manifest.json',report=rel(report),
      engineering_status='COMPLETE_A1_DECLARED_SCOPE_PENDING_INDEPENDENT_QA',evidence_readiness='SAVED_PUBLIC_AND_CONSTRUCTED_ENGINEERING_CHECKS_PASS',
      research_result='NOT_ASSESSED_NO_NEW_EXPERIENCE_OR_BENEFIT_CLAIM',next_stage_admission='INDEPENDENT_QA_ONLY',
      remaining=['A2/A3 not implemented or admitted','all 5 real role correspondences ambiguous, diagnostic only','continuous space/exposed usable faces/load paths/future packing/PCT features NOT_IMPLEMENTED','C2 coverage PARTIAL, all families cross-start support0','legacy frozen execution cannot resume under new source identity'],
      actual_operations=dict(credentials_read=0,model_calls=0,orders=0,forks=0,candidate_reconstruction=0,prefix_replay=0,LP=0,subagents=0),
      real_calls_authorized=0,stop=True,stop_reason='A1实现验证交付后停止交回独立质检，不进入后续阶段，不编写下一任务提示词'))
changed_files=[PACKAGE/k for k in changed]+[PACKAGE/k for k in new_files]+[ROOT/'semantic_pallet_planner/tests/unit/test_packaging_scenario_features.py']
files=sorted(set([p for p in OUT.rglob('*') if p.is_file() and p.name!='delivery_manifest.json' and '__pycache__' not in p.parts]+changed_files+[report]))
assert not any('SKILL' in p.parts for p in files)
write(OUT/'delivery_manifest.json',dict(version='jm2_a1_delivery_manifest_v1',self_hash_excluded=True,shared_navigation_excluded=True,
      excluded=['SKILL/ entire tree','shared README navigation','__pycache__'],
      files=[dict(path=rel(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files]))
print(json.dumps(dict(status='DELIVERED_PENDING_QA',feature_count=len(m.feature_spec()['features']),files=len(files),new_source_files=len(runtime),historical_changed_paths=list(changed),test_count=14,real_calls=0),ensure_ascii=False))

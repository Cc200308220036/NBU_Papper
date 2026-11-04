"""Derive JN2-A delivery from saved suffixes; never dispatch an episode."""
from pathlib import Path
import datetime
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from semantic_pallet_planner.jev_select import packaging_counterfactual as f
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.stability.runtime import environment
r=Path('semantic_pallet_planner/outputs/JEV_JN2_20261104_01')
p=read(r/'branch_plan.json');s=read(r/'fork_snapshot.json');results=read(r/'mechanism_results.json')
assert f.source_manifest()==p['source_manifest']
assert read(r/'saved_record_validation.json')['status']=='PASS'
protected=read(r/'tests/protected_before.json')
after={n:f.sha(n) for n in protected}
assert protected==after
write(r/'protected_before_after.json',{'status':'PASS','files':len(protected),'before':protected,'after':after,'scope':'parent JN1-B package, dataset files and historical Jev reports; navigation indexes intentionally excluded'})
write(r/'source_manifest.json',p['source_manifest'])
algorithm=p['config']['stability_monitor']['algorithm_identity']['files_sha256']
for name,h in algorithm.items():
    origin=Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select/stability')/name
    assert f.sha(origin)==h
    target=r/'algorithm_snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(origin,target)
write(r/'algorithm_snapshot_manifest.json',algorithm)
parent=read('semantic_pallet_planner/outputs/JEV_JN1_20261103_03/source_manifest.json')
write(r/'source_change_review.json',{'parent_digest':digest(parent),'current_digest':digest(p['source_manifest']),'current_files':len(p['source_manifest']),
    'changed':[n for n in parent if n in p['source_manifest'] and parent[n]!=p['source_manifest'][n]],
    'added':sorted(set(p['source_manifest'])-set(parent)),'removed':sorted(set(parent)-set(p['source_manifest'])),
    'snapshot_matches_current':all(f.sha(r/'code_snapshot'/n)==h for n,h in p['source_manifest'].items()),
    'parent_vs_current_rule':'archived bytes are verified independently; do not re-sign historical runtime identities'})
write(r/'environment.json',{'python':sys.version,'platform':platform.platform(),'execution_environment':environment(),
    'implementation_start_HEAD':'e47c8d34','git_HEAD':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
    'production_source_digest':digest(p['source_manifest']),'config_digest':digest(p['config']),'physical_manifest_digest':digest(p['physical_manifest']),
    'credential_read':False,'model_calls':0})
interfaces={'version':f.VERSION,'execution':'jev_packaging_monitored_v5 unchanged; new fork orchestration v1 and new branch metrics v1',
    'restore_training_fork':'restore_training_fork(parent, decision_id) -> sealed ForkSnapshot JSON dict; archived byte and saved transition checks only',
    'forced_first':'bootstrap(binding, task, config, job_id) -> fresh SELECTED v5 checkpoint; saved exact candidates unchanged, v6->v5 envelope adapter, new local binding/selection; no old checkpoint re-signing',
    'continuation_factory':'continuation_factory() -> LocalPackagingDouble(local_geometry_test_double); current public context only',
    'common_episode':'run_episode(..., training_fork=binding, resume=checkpoint); one common candidate/monitor/commit loop',
    'checkpoint_validation':'validate_branch_checkpoint(..., binding) + common.validate_saved_checkpoint(..., fork_origin=snapshot); no execution dispatch',
    'plan_run_validate':'python -m semantic_pallet_planner.jev_select.packaging_counterfactual {prepare,run,validate}',
    'budget':'one parent registration; resume same branch progress; A 3 slots included in B total 12, never +12',
    'schemas':['packaging_fork_snapshot_v1','packaging_fork_binding_v1','packaging_fork_plan_v1','packaging_branch_receipt_v1'],
    'metrics':'jev_training_branch_metrics_v1: common full-task denominators plus prefix/final/suffix_increment; suffix-only monitor coverage',
    'reuse_conditions':['identical parent receipt/fork/source/config/algorithm/environment/continuation identities','reuse saved receipts; do not rerun completed branches','any future identity change requires explicit registration and cumulative accounting; no historical re-signing'],
    'deferred':['ComparisonRecord derivation and causal validity/benefit labels','JN2-B other decisions','T/E construction and all model calls']}
write(r/'interface_contract.json',interfaces)
tests=[]
for name in ['regression','mechanism','final_metrics']:
    x=ET.parse(r/'tests'/f'{name}.xml').getroot();suites=list(x.iter('testsuite'))
    row={'name':name,'tests':sum(int(x.attrib['tests']) for x in suites),'failures':sum(int(x.attrib.get('failures',0)) for x in suites),
         'errors':sum(int(x.attrib.get('errors',0)) for x in suites),'skipped':sum(int(x.attrib.get('skipped',0)) for x in suites)}
    assert row['failures']==row['errors']==0;tests.append(row)
write(r/'test_verification.json',{'status':'PASS','runs':tests,'overlap':'do not add counts; final_metrics retests 7 affected cases after branch metric version explicitization',
    'constructed_only':True,'real_parent_test':'read-only restore at D0001; not a suffix run','historical_116':'ARCHIVED_ONLY_NOT_THIS_RUN'})
assert results['started_suffixes']==3 and all(b['category'] not in f.common.STOP_CATEGORIES for b in results['branches'])
criteria={
'F01':('PASS','saved fork/pool/task/source/cursor evidence + constructed tamper/non-train rejection'),
'F02':('PASS','3 independent saved-prefix branches; exact registered first selection once; stages retained'),
'F03':('PASS','common deterministic geometry continuation, regenerated public suffix pools, natural monitored stops'),
'F04':('PASS','same-box and cross-box registered and observed; native maps, provider rank gap, digest ties/dedup retained'),
'F05':('PASS','stage and batch restart/no-double-execution, error/instability/range/watchdog/NOT_RUN tests; actual saved-record audit'),
'F06':('PASS','367-file source snapshot, interfaces/schemas/config/metrics, all 3 suffix receipts and handoff')}
write(r/'engineering_acceptance.json',{'stage':'JN2-A','version':f.VERSION,'criteria':{k:{'status':v[0],'basis':v[1]} for k,v in criteria.items()},
    'new_model_calls':0,'real_training_decisions':1,'actual_suffixes':3,'complete_JN2':False,'N08_N09':'PARTIAL_PENDING_JN2_B','research_benefit':'NOT_ESTABLISHED'})
write(r/'fork_engine_readiness.json',{'version':'jev_fork_engine_readiness_v1','stage':'JN2-A','F01_F06':{k:v[0] for k,v in criteria.items()},
    'status':'READY_IN_DECLARED_SCOPE','JN2_B_admitted':True,'JN2_B_executed':False,'JN3_admitted':False,
    'parent_identity':p['parent_identity'],'fork_digest':p['fork_digest'],'source_manifest_digest':digest(p['source_manifest']),
    'actual_suffixes':3,'new_model_calls':0,'registered_A_slots':3,'B_total_max_including_A':12,'remaining_B_slots_if_reused':9,
    'receipt_paths':[f'branches/{j}/branch_receipt.json' for j in p['branch_order']], 'reuse_conditions':interfaces['reuse_conditions'],
    'limits':['single exposed training source, one decision; UNKNOWN task feasibility and synthetic capacities',
              'scope termination is not predicted instability or causal benefit','deterministic local continuation, not Jev continuation',
              'no global optimum, unseen validation or memory effectiveness claim','full ComparisonRecord and labels deferred to JN2-B']})
write(r/'handoff.json',{'version':f.VERSION,'stage':'JN2-A-complete','entry':'fork_engine_readiness.json','interfaces':'interface_contract.json',
    'plan':'branch_plan.json','snapshot':'fork_snapshot.json','results':'mechanism_results.json','receipts':[f'branches/{j}/branch_receipt.json' for j in p['branch_order']],
    'budget':{'A_actual':3,'B_inclusive_max':12,'remaining_if_all_A_reused':9},'next':'JN2-B only after separate authorization; no further suffix/model/memory work in this delivery',
    'stop':'JN2-A F01-F06 complete; no automatic commit/push'})
write(r/'commands.json',{'cwd':'repository root','environment':'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src',
    'verification_inputs':['semantic_pallet_planner/tests/unit/test_packaging_counterfactual.py','semantic_pallet_planner/tests/unit/test_packaging_orders.py','semantic_pallet_planner/tests/unit/test_packaging_full_order.py','semantic_pallet_planner/tests/unit/test_packaging_remote.py','semantic_pallet_planner/tests/unit/test_stability_monitor.py','semantic_pallet_planner/src/semantic_pallet_planner/jev_select/tests/unit/test_packaging_runtime.py','semantic_pallet_planner/tests/unit/test_stability_balance.py'],
    'test_command':'python -m pytest <verification_inputs in listed order> -q --disable-warnings; exact temporary JUnit log destinations are retained in tests/*.log',
    'operations':[
      'python -m semantic_pallet_planner.jev_select.packaging_counterfactual prepare --parent semantic_pallet_planner/outputs/JEV_JN1_20261103_03 --output '+r.as_posix(),
      'python '+(r/'guarded.py').as_posix()+' '+(r/'run_guard.json').as_posix()+' semantic_pallet_planner.jev_select.packaging_counterfactual run --output '+r.as_posix(),
      'python '+(r/'guarded.py').as_posix()+' '+(r/'audit_guard.json').as_posix()+' script '+(r/'audit_saved.py').as_posix()+' '+r.as_posix()+' '+(r/'saved_record_validation.json').as_posix()],
    'note':'prepare also executed through guarded.py, staged before destination creation; all tests local/constructed, actual suffix budget only3; no API keys read'})
rows=[]
for b in results['branches']:
    m=b['metrics'];first=p['selection']['branches'][int(b['job_id'][1:])]
    rows.append(f"| {b['job_id']} | {first['intervention']} | {first['box']} | {b['category']} | {m['loading']['placed_items']}/{m['loading']['planned_items']} | {m['loading']['placed_volume_ratio']:.2%} | {m['loading']['placed_mass_ratio']:.2%} | {m['fixed_container_utilization']:.2%} | {m['actual_height_mm']} | {m['envelope_utilization']:.2%} | {m['failure_location']['active_wall_s']:.3f} |")
report=Path('docs/03_阶段产出分析/Jev/Jev_JN2-A分叉引擎与单决策验收_20261104.md')
report.write_text(f'''# Jev JN2-A分叉引擎与单决策验收

日期：2026-11-04。**F01—F06在声明范围PASS；1个保存的真实训练决策，3个本地确定性后缀均已收尾，新增API调用0。JN2-B工程准入，不代表完整JN2或N08—N09全部完成。研究收益NOT_ESTABLISHED。**

产物包：[JEV_JN2_20261104_01](../../../{r.as_posix()}/handoff.json)。依据[主规范7.1—7.4](../../02_阶段实施方案/Jev/Jev新数据完整订单与经验增强分阶段开发规范_20261103.md)，父交付为`JEV_JN1_20261103_03`。本次不执行7.5、经验提炼或未见验证。

## 1. 基线、原件与身份

现场HEAD为`e47c8d34`，工作区起始干净；前一已知`5298d274`之后为汇报提交。根AGENTS.md是唯一适用规则。历史报告声明JN1-B B01—B06通过、55条决策与17次真实多候选；本次另以父清单、源码副本、索引、任务、动作及阶段记录验证输入，不把历史116项当本次结果，不重跑JN1订单。

父数据身份：`{p['parent_identity']['data_identity']}`；父生产源码清单摘要：`{p['parent_identity']['source_manifest_digest']}`。历史模型为`jev-1.14.0`，本次无模型请求。父包全部归档清单字节与物理身份核验见`parent_verification.json`；当前源码与历史源码独立归档，不为新增代码重签历史身份。父包、数据及旧验收报告共{len(protected)}文件前后摘要一致，见`protected_before_after.json`；只更新授权导航索引。

当前367文件生产源码清单摘要：`{digest(p['source_manifest'])}`。新增`packaging_counterfactual.py`和4份封闭Schema，修改`contracts.py`、`episode.py`、`packaging_experiment.py`。全部当前生产Python/JSON源码副本在`code_snapshot/`，逐文件核对与本机一致；监测身份所需文档、许可证与补丁另在`algorithm_snapshot/`完整保存；测试源码另存`tests/`。原候选器、原物理约束、PCT算法、数据、包装承载、容差及提示未修改。

## 2. 实际实现与恢复字段

新编排版本`jev_training_fork_v1`，BranchReceipt为`jev_branch_receipt_v1`，指标为`jev_training_branch_metrics_v1`；执行复用封闭的`jev_packaging_monitored_v5`，不放宽旧v5/v6 Schema。ForkSnapshot和BranchReceipt是有Schema的JSON字典接口，实际签名见`interface_contract.json`。

`restore_training_fork`绑定决策前状态、原池及label映射、完整私有task摘要、来源、数据/配置/源码、原请求收据及父包清单。核对SELECTED阶段与DecisionRecord/action/最终checkpoint的对应关系；读取保存记录，不调用selector、候选生成、commit或PCT重放前缀。旧`candidate_branch.py`已审计，其同箱限制、旧食品清洁品规则及奖励解释均未复用。

`arrival_cursor`是已接收箱数，也是下一箱在完整task.items中的索引，不是决策数或含EOS的事件号。校验它等于`arrival_count`、SELECTED.cursor、前置WAIT_RECEIVE数量，且`arrived_ids == task.items[:cursor]`，缓冲arrival_index由公共invariant复核；EOS不增加计数。每字段证据在`fork_snapshot.json/field_evidence`。父索引的record_digest是完整记录摘要，DecisionRecord内置record_digest排除自身；两种语义分别验证。

显式新分支binding绑定父收据、fork、计划和新配置；bootstrap只适配保存池的v6→v5信封，候选对象及原映射不变，创建新SELECTED选择凭据，不改旧检查点。首动作无需重新生成池或重新选择，随后仍经过公共独立监测与原`commit_physical`。首动作之后各分支由公共run_episode生成自己的新候选，统一工厂只接受当前公开context；私有任务仅供到货与评价。保存选择/监测不覆盖，恢复不重复提交。

监测继续显式`balance_adapter`的`pct_contact_network_v2` / `pct_stability_result_v2`。STABLE只提交一次；UNSTABLE不移失败箱、不增加装入量并停分支；UNASSESSABLE/ERROR独立分类。无预过滤、失稳改选、反力回写面积账本或旧算法回退。

## 3. 事前注册与实际范围

构造测试先完成，再冻结`branch_plan.json`、`registration_receipt.json`及`preregistration.json`，随后才执行后缀。按父计划真实Jev job顺序、决策序号升序，首个合格为`{p['decision_id']}`，来源`{p['source_group']}`、任务`{read(r/'task.private.json')['task_id']}`。fork时到货{s['cursor']}箱、已装{s['state']['placed_count']}箱；没有看替代监测或收益换决策。

fork摘要：`{p['fork_digest']}`。保存原生概率完整；原动作0.29、同箱替代0.10、跨箱替代0.08。每类按概率降序、相同概率按精确动作规范摘要排序，排除原动作与重复pick/pose/oriented-size；类别缺失则留缺口、不补池。本次两类均覆盖。概率仅是程序派生取样依据，显式服务端排名不可得、服务端并列规则UNKNOWN；不是模型第二/第三偏好或物理置信度。

| 分支 | 精确候选ID | 首动作箱体 | 位置(x,y,z,yaw)，mm/deg |
|---|---|---|---|
'''+''.join(f"| B{i:02d} | `{b['candidate']['candidate_id']}` | {b['box']} | ({b['pose']['x_mm']}, {b['pose']['y_mm']}, {b['pose']['z_base_mm']}, {b['pose']['yaw_deg']}) |\n" for i,b in enumerate(p['selection']['branches']))+f'''
顺序固定原动作参考→同箱替代→跨箱替代。后续均`local_geometry_test_double`，展示种子20261102、无附加随机源，新源码/配置/监测身份相同。不是原Jev整轨迹与本地替代轨迹直接归因。每分支看门狗10000个后缀事件、累计活跃600秒，仅在持久化阶段检查，不抢占候选生成或LP；本次未触发，无8事件smoke截断。

本轮最多且实际3后缀；无重试、换决策或新API。换窗口重复A注册拒绝，完成后resume只读返回。JN2-B的总12后缀包括本轮3个，身份完全相同时可复用、余9槽；本次不执行余槽，身份变化须另行显式注册累计额度，不改签历史。

## 4. 全部结果与指标

| 分支 | 干预 | 箱体 | 终态 | 已放/完整计划 | 体积装入 | 质量装入 | 固定容器利用 | 高度mm | 包络利用 | 活跃秒 |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
'''+ '\n'.join(rows)+'''

3次EMPTY_POOL仅表示冻结TopK采样池在当时缓冲下为空，不证明全局无解。三分支分别已到货13、13、15箱，完整任务分母仍为15箱，未来未到货保留分母；失败尝试不算装入。33次后缀选择均STABLE并提交，覆盖33/33；无UNSTABLE、UNASSESSABLE、ERROR、技术限制或NOT_RUN。未观察到预测静态失稳不等于真实坍塌风险为0。fork前缀为0箱、0体积、0质量，因此本次后缀新增量等于最终量；非空前缀的差量语义另有构造测试。`branch_receipt.json/metrics.branch_metrics`同时保存prefix/final/suffix_increment，公共件数比例、质量、容量分布、监测覆盖/原因、时延分布及最终布局均保留。监测覆盖只统计后缀，父前缀证据独立保留；原面积承载剩余量不是未来可装箱数。

完整结果见`mechanism_results.json`及全部`branches/Bxx/branch_receipt.json`，无收益、退化、范围停止或技术失败不会被筛掉。范围停止不能标有效因果收益；本轮不派生完整ComparisonRecord、winner或经验标签。跨箱分支相对参考增加3箱、装入体积比例约18.19个百分点、装入质量27.52kg，同时垛高增加10mm；这是注册动作与固定后续下的观察差异。单个已暴露训练决策与本地后续不足以证明一般策略收益、全局最优或泛化；低高度/高包络利用也不能脱离装入量解释。监测只称预测静态失稳，不称真实坍塌。

## 5. 本次复验与逐项验收

本次联合回归182项通过；专项28项通过；将分支指标显式版本化后对受影响指标/批次/非空前缀路径再验7项通过。各组重叠，不相加。JUnit与实际日志在`tests/`，历史116项不是本次结果。构造任务及fake transport只作机制测试，不代替本次真实训练决策后缀。

覆盖输入篡改/错配/非训练拒绝、精确首动作与状态独立、概率缺失/并列/去重/类别缺口、后续重新生成、首动作与后续的UNSTABLE/UNASSESSABLE/ERROR立即停单、阶段和批次中断恢复、看门狗/取消/技术错误与NOT_RUN分母。构造非空前缀验证cursor与新增装入量；真实D0001另只读恢复，不运行其后缀。

网络、凭证读取及父包写入设阻断；专项、计划及实际运行计数均0。`audit_saved.py`禁止episode/selector/候选生成/commit/监测/PCT/LP后，标准保存记录校验及完成后resume通过，派发计数0，产物字节不变；重复A注册拒绝。见`saved_record_validation.json`、`audit_guard.json`与`run_guard.json`。保存状态校验只计算独立几何/面积事实，不重放物理提交或LP。

| 验收 | 状态 | 实际证据 |
|---|---|---|
'''+''.join(f'| {k} | {v[0]} | {v[1]} |\n' for k,v in criteria.items())+f'''
逐项机器收据为`engineering_acceptance.json`；准入为`fork_engine_readiness.json`。F01—F06只关闭JN2-A；N08—N09与完整JN2保留PARTIAL，等待JN2-B有限对比材料验收。研究收益NOT_ESTABLISHED，不要求替代分支获胜。

## 6. 复核与交接

根目录运行，使用现有`python`解释器，设置`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src`。已执行的正式操作与测试输入见`commands.json`。标准只读复核：

```bash
python -m semantic_pallet_planner.jev_select.packaging_counterfactual validate \\
  --output {r.as_posix()}
```

后续消费`handoff.json`、冻结计划、fork、BranchReceipt和源码副本；复用要求父输入、配置、源码、算法、环境、后续策略身份完全一致，已完成分支不得重派发。没有经验库或LLM提炼材料，JN3不准入。

本次完成JN2-A后停止；未执行JN2-B、JN3、历史全量回放、模型连通性探测或新增模型调用，未读取API密钥，未启动子代理，未自动commit/push，未扩大.gitignore例外。原件和冻结身份保持原字节。
''',encoding='utf-8')
# New navigation entries; older rows retain their historical scope.
for path,line in [
 (Path('docs/03_阶段产出分析/Jev/README.md'),'| [JN2-A分叉引擎与单决策](Jev_JN2-A分叉引擎与单决策验收_20261104.md) | F01—F06声明范围通过；1真实训练决策、3本地后缀，API 0；JN2-B工程准入，完整JN2未完成，研究收益未建立。 |'),
 (Path('docs/02_阶段实施方案/Jev/README.md'),'| [JN2-A实际验收与JN2-B交接](../../03_阶段产出分析/Jev/Jev_JN2-A分叉引擎与单决策验收_20261104.md) | F01—F06通过；3个注册本地后缀计入后续总12额度，API 0；JN2-B未实施。 |')]:
    text=path.read_text();marker='|---|---|';assert marker in text
    if line not in text:path.write_text(text.replace(marker,marker+'\n'+line,1))
# Do not rewrite historical reports, even where their time-scoped status differs.
write(r/'report_reference.json',{'report':report.as_posix(),'sha256':f.sha(report)})
print('derived delivery and report; final seal still required')

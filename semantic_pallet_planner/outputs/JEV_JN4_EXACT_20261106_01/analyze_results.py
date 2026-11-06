"""Read-only trajectory analysis; never calls a selector, monitor or transport."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.packaging_reanalysis import evaluate,metric_view,RULE_VERSION

OUT=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text())
def write(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

p=read(OUT/'plan/plan.json');run=Path(p['run_location'])
old=read(Path(p['parent']['plan'])/'plan.json');oldrun=Path(p['parent']['run'])
newjobs={j['job_id']:j for j in p['jobs']};rows=[];views={};sequences=[];coverage=[]
for archived in old['jobs']:
    current=archived['job_id'] in newjobs;j=newjobs.get(archived['job_id'],archived)
    root=(run if current else oldrun)/'jobs'/j['job_id'];status=read(root/'status.json')
    m=read(root/'metrics.json') if (root/'metrics.json').exists() else None
    row={k:j[k] for k in ('job_id','task_id','method_id')}
    row.update(record_origin='v3_supplement' if current else 'v2_historical',
        protocol=j['config']['version'],algorithm=j['config']['stability_monitor']['algorithm'],
        source_digest=digest((p if current else old)['source_manifest']),status=status,
        metrics=m if m else 'NOT_RUN' if status['state']=='NOT_RUN' else 'UNKNOWN_TECHNICAL_FAILURE',
        evidence_root=str(root))
    rows.append(row)
    if m:
        views[j['task_id'],j['method_id']]=(row['algorithm'],metric_view({'metrics':m,'status':status},read(root/'task.snapshot.json'),p['data']['data_identity']))
        mem=m['memory_metrics'];ds=mem['decisions']
        coverage.append({**{k:row[k] for k in ('job_id','task_id','method_id','record_origin')},
            'decisions':mem['decision_count'],'retrieval_nonempty':sum(d['qualified_retrieval_nonempty'] for d in ds),
            'view_nonempty':mem['view_nonempty_count'],'body_nonempty':mem['body_nonempty_count'],
            'actually_sent_nonempty':mem['actually_sent_nonempty_count'],
            'singleton_decisions':sum(d['route']=='SINGLETON_BYPASS' for d in ds),
            'singleton_nonempty_view':mem['singleton_nonempty_view_count']})
        sequences.append({'job_id':j['job_id'],'record_origin':row['record_origin'],
            'decisions':[{k:d[k] for k in ('decision_id','selected_candidate_id','selected_box','selected_pose')} for d in ds]})
    else:coverage.append({'job_id':j['job_id'],'coverage':'NOT_RUN' if status['state']=='NOT_RUN' else 'UNKNOWN'})
write('all_36_slots.json',rows);write('coverage_summary.json',coverage);write('behavior_observations.json',sequences)
fields=['job_id','task_id','method_id','record_origin','algorithm','category','placed_items','planned_items','placed_item_ratio','placed_volume_ratio','placed_mass_ratio','fixed_container_utilization','actual_height_mm','envelope_utilization','monitor_statuses','monitor_reasons','memory_metrics','latency_s','cost']
with (OUT/'all_36_slots.csv').open('w') as f:
    writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
    for r in rows:
        d={k:r[k] for k in fields[:5]};d['category']=r['status']['category'];m=r['metrics']
        for k in fields[6:]:
            v=m.get('loading',{}).get(k,m.get(k,'UNKNOWN')) if isinstance(m,dict) else m
            d[k]=json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v
        writer.writerow(d)
pairs=[]
for task in old['task_ids']:
    for alt,ref,label in [('jev_with_trajectory','jev_no_memory','T/none'),('jev_with_contrast_experience','jev_no_memory','E/none'),('jev_with_contrast_experience','jev_with_trajectory','E/T'),('jev_with_contrast_experience','jev_with_unrelated_E_control','E/unrelated_E')]:
        a=views.get((task,ref));b=views.get((task,alt))
        result=evaluate(a[1],b[1],rule_version=RULE_VERSION) if a and b and a[0]==b[0] else {'comparison_valid':False,'label_v2':'NOT_RUN' if not a or not b else 'INVALID_CROSS_VERSION'}
        pairs.append({'task_id':task,'comparison':label,'algorithm':a[0] if a else 'NOT_RUN','historical':task=='SYN_COMBO_01','evaluation':result})
write('paired_comparisons_v2.json',pairs)
summary=read(run/'summary.json');stats=summary['request_statistics'];prior=read(oldrun/'summary.json')['request_statistics']
technical=read(run/'technical_failure.json') if (run/'technical_failure.json').exists() else None
transport_stop=read(OUT/'timeout_diagnosis.json') if (OUT/'timeout_diagnosis.json').exists() else None
newrows=[r for r in rows if r['record_origin']=='v3_supplement'];closed=sum(r['status']['state']=='FINISHED' for r in newrows)
known=stats['known_real_model_calls']+prior['known_real_model_calls'];unknown=stats['unknown_real_send_count']+prior['unknown_real_send_count']
combined={'send_reservations':prior['send_reservations']+stats['send_reservations'],
 'network_attempts':prior['network_attempts']+stats['network_attempts'],'known_real_model_calls':known,
 'unknown_real_send_count':unknown,'actual_model_api_calls':'UNKNOWN' if unknown else known,
 'failed_requests':prior['failed_requests']+stats['failed_requests'],'global_cap':656,'model_cost_usd':'UNKNOWN',
 'real_model_call_interval':{'minimum':known,'maximum':known+unknown},
 'remaining_reservations':656-prior['send_reservations']-stats['send_reservations'],
 'known_input_tokens':prior['usage']['input_tokens']+stats['usage']['input_tokens'],
 'known_output_tokens':prior['usage']['output_tokens']+stats['usage']['output_tokens'],
 'missing_usage_requests':prior['usage']['missing_request_count']+stats['usage']['missing_request_count']}
write('descriptive_summary.json',{'supplement_planned':29,'supplement_closed':closed,'supplement_categories':summary['categories'],
 'all36_categories':dict(Counter(r['status']['category'] for r in rows)),
 'historical_requests':prior,'supplement_requests':stats,'combined_requests':combined,
 'v3_paired_labels':dict(Counter(x['evaluation']['label_v2'] for x in pairs if not x['historical'])),
 'research_benefit':'NOT_ESTABLISHED','scope':'synthetic familiar prototypes, single observation, explicit v2/v3 split; no causal or unseen-source claim'})
receipt={'version':'jev_exact_supplement_evaluation_receipt_v1','head_at_entry':'dae7ab0d','plan':str(OUT/'plan'),
 'run':str(run),'parent':p['parent'],'supplement_planned':29,'supplement_closed':closed,
 'supplement_not_run':sum(r['status']['state']=='NOT_RUN' for r in newrows),'categories':summary['categories'],
 'stop_reason':'STOP_TECHNICAL' if summary['status']=='ERROR' else 'AUTHORIZED29_COMPLETED' if closed==29 else 'INCOMPLETE',
 'technical_failure':technical,'transport_stop_diagnosis':transport_stop,'request_statistics':stats,'combined_requests':combined,
 'algorithm':'pct_exact_pose_network_v3','research_benefit':'NOT_ESTABLISHED','JN4_B_admitted':False,
 'criteria':{'V01':'PASS_AUTHORIZED29' if closed==29 and summary['status']!='ERROR' else 'PARTIAL_WITH_STOP',
 'V02':'PASS_EXPLICIT_V2_V3_SPLIT_FROZEN_STRATEGIES','V03':'PASS_SAVED_FACTS_IN_EXECUTED_SCOPE' if summary['status']!='ERROR' else 'PARTIAL_TECHNICAL_STOP',
 'V04':'PASS_ALL36_DENOMINATOR_RETAINED','V05':'PASS_SAME_VERSION_PAIRS' if all(x['evaluation']['comparison_valid'] for x in pairs if not x['historical']) else 'PARTIAL_UNRUN_OR_INVALID_PAIRS','V06':'PASS_DESCRIPTIVE_DELIVERY_NO_REQUIRED_GAIN'},
 'run_summary_sha256':sha(run/'summary.json'),'run_manifest_sha256':sha(run/'delivery_manifest.json'),
 'repeated_parent_jobs':0,'new_experience_generated':False,'stop':True}
write('evaluation_receipt.json',receipt)
report=Path('docs/03_阶段产出分析/Jev/Jev_JN4精确位置稳定性修复与29项补充实验验收_20261106.md')
prefix='../../../'+str(OUT.relative_to(Path.cwd()))
text=['# Jev JN4精确位置稳定性修复与29项补充实验验收','',
 '日期：2026-11-06；进入HEAD `dae7ab0d`。用户授权修复方案B，并确认只执行原29个NOT_RUN槽位、不重跑旧7项、剩余592预约上限、分版本报告。未commit/push或启动子代理。', '',
 f'补充已收尾 **{closed}/29**，停止原因 `{receipt["stop_reason"]}`，批次状态 `{summary["status"]}`。原首批PASS仍为旧v2事实，不伪称新v3的首批门槛。', '',
 f'[执行收据]({prefix}/evaluation_receipt.json) · [全36项JSON]({prefix}/all_36_slots.json) · [CSV]({prefix}/all_36_slots.csv) · [配对比较]({prefix}/paired_comparisons_v2.json) · [覆盖]({prefix}/coverage_summary.json) · [handoff]({prefix}/handoff.json)', '',
 '## 修复与验证', '',
 '新入口 `stability.exact_adapter.assess_candidate`，算法 `pct_exact_pose_network_v3`、结果v3，运行协议v12。直接按精确最终位置构建接触网络；不再用垂直下落重定位。只按高度匹配且面积为正的接触建边，上方间隙不作为支撑。私有求解节点按高度排序，原状态与提交顺序不改。', '',
 '复用原全局平衡求解器、数值容差、PCT凸包及10%收缩，保留严格内部反力和保守边界。旧v2入口/Schema/反例保留，无回退。原候选、物理/包装检查、提示、模型、T/E/对照、记忆范围和排除不变。此模型不评价机械臂路径可达、摩擦滑移、变形或真实坍塌。', '',
 '旧J0006只做单状态适配核对：动作不变，v3为STABLE、高度差0；原v2不可评价记录保留。冻结版本核对见frozen_height_case_v3.json，开发版本证据另存不重签。该检查没有重跑旧订单，也不能证明该订单能够完整装入。本机最终离线61项通过（failures/errors/skipped均0，网络与凭证访问保护计数均0）；源码/算法身份见 `tests_final.xml`、`tests_final.log`、`offline_guards.json` 和 `freeze_receipt.json`；测试批次有重叠，不相加。中间两项恢复测试读错公共返回字段state，修正为final_state后重验；保留partial日志，不伪作算法失败。', '',
 '## 计划、预算与真实运行', '',
 f'计划 `{OUT.relative_to(Path.cwd())}/plan`，run `{run}`；只包含原J0007—J0035，9本地/20远程。逐job预算继承原完整箱数，本地0。旧预约64+补充预约{stats["send_reservations"]}={combined["send_reservations"]}，总上限656；补充上限592。唯一owner绑定父run与新plan，不能换目录复制重试。', '',
 '实际命令、环境、官方文档访问日期见 `commands.json`、`official_api_review.json`。固定jev-1.14.0及原System One Choice；当日核对[System One](https://docs.typesafe.ai/api/system-one)、[模型](https://docs.typesafe.ai/models)、[Choice](https://docs.typesafe.ai/primitives/choice)、[错误合同](https://docs.typesafe.ai/api/errors)。30秒超时、零重试，无服务探测。凭证通过既有credential加载器注入子进程环境，未写入产物。公共_run_plan/run_episode保存请求、选择、监测、提交、检查点与最终校验。自然终止不代选；技术/未知发送/未登记范围按合同停批。', '',
 '## 全36原槽位', '',
 '前7项为历史v2，其余为本次v3（包括未运行项的计划版本）。第二单几何为旧v2，不能与该单其余五项冒充同算法六方法对照。下表所有装入比例以完整订单为分母；完整指标另含监测原因、预测失稳进度、singleton、检索/真实注入和n/p50/p95时延。', '',
 '| 任务 | 方法 | 版本 | 状态 | 件数 | 件数比 | 体积比 | 质量比 | 容器利用率 | 高度mm | 包络 | 非空真实注入 |',
 '|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
names=dict(zip(old['method_ids'],['几何','固定顺序','无经验','T','E','无关E']))
def fmt(v):return f'{v:.6f}' if isinstance(v,float) else str(v)
for r in rows:
    m=r['metrics'];values=[r['task_id'],names[r['method_id']],'v2历史' if r['record_origin']=='v2_historical' else 'v3补充',r['status']['category']]
    if isinstance(m,dict):
        l=m['loading'];values += [f'{l["placed_items"]}/{l["planned_items"]}',l['placed_item_ratio'],l['placed_volume_ratio'],l['placed_mass_ratio'],m['fixed_container_utilization'],m['actual_height_mm'],m['envelope_utilization'],m['memory_metrics']['actually_sent_nonempty_count']]
    else:values += [m]*8
    text.append('| '+' | '.join(map(fmt,values))+' |')
text += ['', '## 同版本配对比较', '', '| 任务 | 比较 | 监测版本 | v2评价结果 | 决定层 |','|---|---|---|---|---|']
for x in pairs:text.append(f'| {x["task_id"]} | {x["comparison"]} | {x["algorithm"]} | {x["evaluation"]["label_v2"]} | {x["evaluation"].get("decisive_level","NOT_RUN")} |')
text += ['', '装入量优先评价v2按稳定完整完成、体积、件数/质量及同装入量下紧凑性排序；不可评价或技术失败不强行排名。EMPTY_POOL只表示冻结采样候选池为空，不证明全局无解。旧首单配对只作历史引用，其余配对限本次v3。仅原第3—6单具备本次同版本六方法完整矩阵的计划范围。', '',
 '选箱与位置序列保存在behavior_observations.json；不同状态轨迹不当作同池反事实。公共零违规不当作策略收益，预测静态失稳不称真实坍塌；相同订单全部装入时，固定容器利用率不能证明布局更优。合成包装属性与熟悉原型的新组合性质保留，单次小样本不证明独立来源泛化或稳定因果收益。研究收益NOT_ESTABLISHED。', '',
 '## 请求、技术状态与验收', '',f'补充请求账目：`{json.dumps(stats,ensure_ascii=False)}`。', '',f'分批相加账目：`{json.dumps(combined,ensure_ascii=False)}`。费用UNKNOWN不填0；两次运行的attempt ID以各自run为作用域，不声称跨run全局ID唯一。', '',
 f'技术停止记录：`{json.dumps(technical,ensure_ascii=False)}`。完整36状态分母：`{dict(Counter(r["status"]["category"] for r in rows))}`。', '',
 '| 条目 | 实际状态 |','|---|---|']
for k,v in receipt['criteria'].items():text.append(f'| {k} | {v} |')
if transport_stop:
    text += ['', '本次停止来自第二单无关E的A000057/J0011_D0006：在connection_and_headers阶段等待约30秒超时，无HTTP响应，账本UNKNOWN_SEND。已收到56个新响应，另1次服务端处理及费用UNKNOWN，不重发、不退款；后24项未派发。失败动作未提交、状态前后相同。不是PCT失稳、经验无效或无关E策略劣势；E/无关E对照因技术停止不能排名。见timeout_diagnosis.json。没有批次级technical_failure.json不代表没有技术停止，SELECTION_FAILURE及请求账本共同记录此事。']
text += ['', '工程修复、真实经验注入、观察到的行为差异与研究收益分别记录，不用总PASS掩盖部分完成。旧真实来源JN4_B_admitted=false仍不改变。', '',
 f'停止于 `{receipt["stop_reason"]}`。未追加重复、训练、经验生成、阈值调整或JN5开发；后续只读复核，不自动重试或续加实验。','']
report.write_text('\n'.join(text))
for index,entry in [(report.parent/'README.md',f'| [精确位置稳定性修复与29项补充实验]({report.name}) | v3/v12；补充{closed}/29收尾，预约{stats["send_reservations"]}/592，{receipt["stop_reason"]}；旧7项v2保留，分版本描述，研究收益未建立。 |\n'),(Path('docs/02_阶段实施方案/Jev/README.md'),f'| [精确位置稳定性与29项补充执行方案](Jev_JN4精确位置稳定性与29项补充执行方案_20261106.md) | 用户确认只补29项、592预约；新v3/v12与旧v2分开报告，实际结果见新验收。 |\n')]:
    text=index.read_text()
    if entry.split('](')[1].split(')')[0] not in text:index.write_text(text.replace('|---|---|\n','|---|---|\n'+entry,1))
write('handoff.json',{'version':'jev_exact_supplement_handoff_v1','report':str(report),'receipt':'evaluation_receipt.json','plan':str(OUT/'plan'),'run':str(run),'stop':True,'stop_reason':receipt['stop_reason'],'next':'read-only review; no automatic new experiment','old_jobs_repeated':0})
print(json.dumps({'closed':closed,'status':summary['status'],'stop':receipt['stop_reason'],'supplement_sends':stats['send_reservations'],'total_sends':combined['send_reservations']},ensure_ascii=False))

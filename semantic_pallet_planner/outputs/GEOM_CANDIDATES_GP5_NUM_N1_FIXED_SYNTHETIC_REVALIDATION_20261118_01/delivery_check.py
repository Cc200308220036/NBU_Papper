import json,hashlib,re,subprocess,sys
from pathlib import Path
p=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_NUM_N1_FIXED_SYNTHETIC_REVALIDATION_20261118_01');report=Path('docs/03_阶段产出分析/几何规划模块/几何候选器GP5-NUM-N1固定合成复验交付_20261118_01.md');i=p.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R6_20261118_01'
read=lambda f:json.loads(f.read_bytes())
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
def write(f,v):f.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
a=read(p/'R_recovery/J01_COMMITTED/jobs/J01/accounting.json')['invocations'][-1]
cp=read(p/'R_recovery/J01_COMMITTED/jobs/J01/checkpoint.json')
nulls=[{'decision_id':e.get('decision_id'),'null_timing_keys':[k for k,v in e.get('timings',{}).items() if v is None]} for e in cp['events'] if any(v is None for v in e.get('timings',{}).values())]
write(p/'failure_analysis.json',{'issue':'GP5_NUM_N1_FIXED_R_COMMITTED_NULL_TIMING','case':'R/J01/COMMITTED','status':'FAIL_STOP_NO_RETRY','original_error':read(p/'validation_stop.json'),'observed_recovery_phase':cp['phase'],'observed_reason':cp['reason'],'failed_invocation':a,'null_timings':nulls,'production_site':'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/geometry_order_execution.py:232','producer_site':'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/episode.py:429','analysis':'Saved COMMITTED recovery produces a null decision_wall_s; order_metrics includes that key from the preceding numeric event and sums None. This explains the observed exception; no fix or rerun performed.','new_monitor_commit_on_failed_resume':[0,0],'expected_zero_increments_do_not_imply_case_pass':True})
s=report.read_text();s=s[:s.index('本轮原始停点：')]+'''首次非预期失败为 `R/J01/COMMITTED`，原始异常 `TypeError: unsupported operand type(s) for +: 'float' and 'NoneType'`，完整 traceback 保留在 validation_stop.json、stop.json 和失败 harness 收据；无归档二次异常。指标汇总 `geometry_order_execution.py:232` 对事件 timing 求和；只读检查发现恢复后的最后事件 `decision_wall_s=null`，前一事件该字段为 float。`episode.py:429` 的 COMMITTED 恢复路径允许该空值，汇总未跳过它。这是根据本轮异常与保存件作出的原因分析，未经修复验证。

失败恢复账本为 ERROR，新增选择/单候选执行/监测/复用/提交均为 0；恢复保存的 checkpoint 已是 TERMINATED / ALL_ITEMS_PLACED，但汇总抛错，因此该项必须 FAIL，不能以已放完或零增量宣称通过。J03 三相位均未运行。X/H/admin 15 项全部未运行，其预期拒绝、兼容性及管理员进入真实循环前拒绝边界仅为待验收合同，本轮未获得这些检查的运行结论。

逐项状态如下；原 35 项分母完整保留，PASS 16、FAIL 1、NOT_RUN 18。所有已派发项仅 1 次尝试。

| 项目 | 状态 | 尝试 |
|---|---|---:|
'''
r=read(p/'case_results.json')
s+='\n'.join(f"| {v['id']} | {v['status']} | {v['attempts']} |" for v in r['rows'])+'\n'
s=s.replace('R 只使用本轮 J01/J03 整数 local_first 最后一箱的相位一致副本，父前缀未改、保存副本未改；不以完成账本嫁接早期 checkpoint。恢复增量见下表，生成/发布/选择均由零调用保护约束。','R 的计划来源为本轮 J01/J03 整数 local_first 最后一箱的六份相位一致副本。实际仅尝试 J01 三相位；下表列已通过的两项。父前缀及保存副本摘要保持不变，不以完成账本嫁接早期 checkpoint；生成/发布/选择受零调用保护约束。')
s=s.replace('X/H/admin 保留原 15 项：预期异常必须精确匹配异常类型和错误码；旧 v16 整数订单原技术失败作为预期保护保留；终态/强完成项属于保存件或纯合同验证。管理员项只允许读适配摘要，在真实 episode 循环前拒绝，不能解释为真实订单执行许可。逐项子检查和实测计数见 X_H_admin_results.json、case_results.json。','X/H/admin 原 15 项全部 NOT_RUN，因 R 首次失败未进入该组；X_H_admin_results.json 未生成。预期异常精确匹配、旧 v16 失败保护、终态/强完成兼容和管理员在真实循环前拒绝均未在本轮复验，不能沿用历史 PASS。')
report.write_text(s)
sys.path.insert(0,str(i.resolve()));from validation_entrypoint import check_frozen
check_frozen(i)
for folder,expected in read(p/'sealed_input_identity.json').items():
 actual={str(f.relative_to(Path(folder))):sha(f) for f in Path(folder).rglob('*') if f.is_file()}
 assert actual==expected,folder
provenance=read(p/'R_snapshot_provenance.json')
for v in provenance:
 base=Path(v['root']);assert {str(f.relative_to(base)):sha(f) for f in base.rglob('*') if f.is_file()}==v['files']
assert len(r['rows'])==35 and sum(x['status']=='PASS' for x in r['rows'])==16 and sum(x['status']=='FAIL' for x in r['rows'])==1
assert len(read(p/'E_f0_pairs.json'))==4
for target in re.findall(r'\]\(([^)]+)\)',report.read_text()):
 if target.endswith('delivery_manifest.json'):continue
 assert (report.parent/target).exists(),target
for f in p.rglob('*.json'):read(f)
res=subprocess.run(['git','diff','--check'],capture_output=True,text=True);assert res.returncode==0,res.stdout+res.stderr
write(p/'delivery_verification.json',{'status':'PASS_ARCHIVE_AND_DELIVERY_CHECK_ONLY','business_replay':False,'source_and_frozen_archive_bytes':'UNCHANGED','saved_phase_copies':len(provenance),'case_count':35,'pass':16,'fail':1,'not_run':18,'json_parse':'PASS','report_links':'PASS','git_diff_check':'PASS','run_exit_code':1})
commands=read(p/'command_receipts.json');commands['delivery_verification']={'script':str(p/'delivery_check.py'),'command':f'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src:semantic_pallet_planner/tests/unit "$REGISTERED_PYTHON" {p}/delivery_check.py','original_script_location':'/tmp/gp5_fixed_finalize.py','scope':'read-only archive verification and delivery metadata; no suite replay'};write(p/'command_receipts.json',commands)
# Self-excluding digest inventory covers every retained runtime artifact and both docs.
files=[f for f in p.rglob('*') if f.is_file() and f.name!='delivery_manifest.json']+[report,report.parent/'README.md']
write(p/'delivery_manifest.json',{'schema':'gp5_num_n1_fixed_revalidation_manifest_v1','self_hash_excluded':True,'status':'FIRST_UNEXPECTED_FAILURE_STOPPED','files':[{'path':str(f),'sha256':sha(f),'size_bytes':f.stat().st_size} for f in sorted(files)]})
m=read(p/'delivery_manifest.json')
for v in m['files']:
 f=Path(v['path']);assert f.stat().st_size==v['size_bytes'] and sha(f)==v['sha256']
print('Delivery verified:',len(m['files']),'files; 16 PASS, 1 FAIL, 18 NOT_RUN; no replay')

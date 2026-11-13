"""C2 read-only frozen identity admission, then new authorization/permits. No sends/LP."""
import hashlib,json,sys,subprocess
from pathlib import Path
from semantic_pallet_planner.jev_select import packaging_jev_v13 as v,packaging_jev_training_freeze as f
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.ledger import read,write
OUT=Path(__file__).resolve().parent
C1=Path('semantic_pallet_planner/outputs/JEV_JM1_C1_REAL_BASELINES_20261112_01')
B2=Path('semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01')
QA=Path('semantic_pallet_planner/outputs/JEV_JM_C1_REAL_QA_20261113_01')
assert sys.executable=='/home/cyw/anaconda3/bin/python'
assert not (OUT/'authorization_receipt.json').exists(),'DO_NOT_REISSUE_AUTHORIZATION'
assert source_manifest()==read(B2/'source_manifest.json')
manifest_checks=[]
for base in (C1,B2,QA):
 m=read(base/'delivery_manifest.json')
 for e in m['files']:
  b=Path(e['path']).read_bytes();assert hashlib.sha256(b).hexdigest()==e['sha256'] and len(b)==e['bytes'],e['path']
 manifest_checks.append(dict(path=str(base/'delivery_manifest.json'),files=len(m['files']),status='PASS'))
freeze=read(B2/'formal_freeze.json');check=f.validate_frozen_plan(freeze,root=Path.cwd())
plan=read(C1/'fork_plan.json');budget=read(C1/'concrete_budget_receipt.json')
assert read(QA/'next_stage_admission.json')['status']=='READY'
assert len(plan['points'])==5 and len(plan['jobs'])==18
assert (budget['initial_jobs'],budget['repeat_jobs'],budget['initial_send_upper'],budget['repeat_send_upper'],budget['suffix_send_upper'])==(10,8,130,112,242)
jobs=[]
for j in plan['jobs']:
 ex=v.load_ref(j['execution_ref']);v.validate_execution(ex)
 assert ex['job_id']==j['job_id'] and ex['allocation_id']==j['allocation_id'] and ex['storage_root']==j['storage_root']
 assert ex['max_sends']==j['max_sends'] and ex['forced_label']==j['forced_label'] and ex['repeat_slot']==j['repeat_slot']
 assert not Path(ex['storage_root']).exists(),'PREEXISTING_RUN_STOP'
 _,_,event=v.validate_start(ex['start'])
 candidate=next(c for c in event['bundle']['selectable_candidates'] if c['candidate_id']==j['candidate_id'])
 assert candidate==j['frozen_candidate'] and digest(candidate)==j['candidate_digest']
 assert event['context']['display_mapping'][ex['forced_label']]['candidate_id']==j['candidate_id']
 assert ex['config']['memory_mode']=='none' and ex['config']['max_retries']==0
 jobs.append(dict(job_id=ex['job_id'],execution_digest=digest(ex),allocation_id=ex['allocation_id'],max_sends=ex['max_sends'],repeat_slot=ex['repeat_slot'],storage_root=ex['storage_root'],execution_ref=j['execution_ref']))
assert sum(j['max_sends'] for j in jobs if j['repeat_slot']=='r0')==130
assert sum(j['max_sends'] for j in jobs if j['repeat_slot']=='r1')==112
write(OUT/'official_protocol_receipt.json',dict(version='jm_c2_official_protocol_check_v1',access_date='2026-11-13',official_sources=['https://docs.typesafe.ai/api/system-one','https://docs.typesafe.ai/primitives/choice.md','https://docs.typesafe.ai/models'],method='Official documentation accessed via web tool; no authenticated probes',verified=dict(endpoint='POST https://api.typesafe.ai/v1/systemone',authentication='Bearer token; application/json',body=['model','state','questions'],choice=['type=choice','instructions','criteria'],response=['model','answers.<question>.choice','probabilities','confidence','usage'],model='jev-1.14.0'),frozen_transport='existing JevTransport; max_retries=0; timeout_s=30',cost='UNKNOWN unless actual accounting available'))
write(OUT/'presend_identity_receipt.json',dict(version='jm_c2_presend_identity_v1',head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),entry=sys.executable,identity=v.identity(),frozen_source_files=len(source_manifest()),manifest_checks=manifest_checks,formal_freeze_validation=check,formal_freeze=v.ref(B2/'formal_freeze.json'),fork_plan=v.ref(C1/'fork_plan.json'),jobs=jobs,actual_execution_validation='PASS_ALL_18',LP='NOT_RUN',credentials='NOT_READ_BY_THIS_SCRIPT'))
statement='我明确授权执行既定JM1-C2真实实验：仅限已冻结的5个起点、18个job，其中初次10个job发送上界130，重复8个job发送上界112，后缀累计发送上界242，不得扩大范围或转移额度。允许使用现有凭证加载方式读取所需API凭证，完成发送前身份及协议核验，保存逐execution外部许可，随后严格按照上一份C2完整开发指令执行。保留全部失败、UNKNOWN_SEND、重复冲突和未运行记录，不隐式重试、不补点、不重跑C1、不修改冻结身份。完成C2比较、证据等级和经验输入准入交付后停止，不进入JM2，交回独立质检。'
write(OUT/'authorization_receipt.json',dict(version='jm_c2_user_authorization_v1',date='2026-11-13',authority='USER_EXPLICIT_CURRENT_TURN',user_statement=statement,points=5,initial_jobs=10,repeat_jobs=8,initial_send_upper=130,repeat_send_upper=112,suffix_send_upper=242,unused='NONTRANSFERABLE_NO_REFILL',historical_C1_authorization_reused=False,execution_bindings=jobs,protocol=v.ref(OUT/'official_protocol_receipt.json'),identity=v.ref(OUT/'presend_identity_receipt.json'),stop='C2 full comparison and evidence readiness; independent QA; no JM2'))
for j in jobs:
 ex=v.load_ref(j['execution_ref']);p=OUT/'permits'/(ex['job_id']+'.json')
 assert not p.exists()
 write(p,dict(version='jev_jm_v13_send_permit_v1',execution_digest=digest(ex),allocation_id=ex['allocation_id'],max_sends=ex['max_sends'],authorized=True))
 v.validate_send_permit(ex,v.ref(p))
write(OUT/'execution_order.json',dict(version='jm_c2_order_v1',policy='all initial jobs in frozen plan order, then all registered repeats in frozen plan order; technical gate only',jobs=[j for slot in ('r0','r1') for j in jobs if j['repeat_slot']==slot]))
print(json.dumps(dict(status='PASS',jobs=len(jobs),source_files=len(source_manifest()),send_upper=242,permits=18,real_sends=0)))

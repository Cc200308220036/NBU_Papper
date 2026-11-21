import json,hashlib,subprocess
from pathlib import Path
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.geometry_jev_kernel_bridge import source_delta
out=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_F0_KERNEL_BRIDGE_FIX_20261121_01')
def save(name,doc):(out/name).write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
oldroot=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01')
hist=json.loads((oldroot/'source_manifest.json').read_bytes())
files=source_manifest()
save('new_source_identity.json',{'entry_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_identity':digest(files),'files':files,'historical_source_identity':hist['source_identity'],'historical_source_untouched':True})
delta=source_delta(hist['files'],files)
save('source_delta_review_NOT_APPROVED.json',{'status':'NOT_APPROVED','purpose':'供独立QA逐项审查，非桥接凭证，不能启动GP6','historical_source_identity':hist['source_identity'],'target_source_identity':digest(files),'diff_digest':digest(delta),'changes':[{**r,'applicability':'PENDING_INDEPENDENT_QA'} for r in delta],'limitation':'监测算法相同不足以批准继承；完整调用链、准入、计量、恢复与新增桥接代码均须审查。'})
receiptpath=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_FORMAL_ORDER_APPROVED_QA_20261120_01/real_kernel_receipt.json')
seen={};errors=[]
def walk(doc):
 if isinstance(doc,dict):
  if set(doc)=={'path','sha256'}:
   path=doc['path']
   if path in seen:return
   try:
    raw=Path(path).read_bytes();actual=hashlib.sha256(raw).hexdigest()
    seen[path]={'expected':doc['sha256'],'actual':actual,'matches':actual==doc['sha256']}
    if actual!=doc['sha256']:errors.append({'path':path,'error':'BYTE_SHA256_MISMATCH'})
    try:walk(json.loads(raw))
    except (ValueError,UnicodeDecodeError):pass
   except OSError as e:errors.append({'path':path,'error':type(e).__name__})
  else:
   for v in doc.values():walk(v)
 elif isinstance(doc,list):
  for v in doc:walk(v)
receipt=json.loads(receiptpath.read_bytes());walk(receipt)
save('historical_readonly_audit.json',{'scope':'仅原归档引用字节与摘要检查，不执行历史4+6，不签发，不批准GP6继承','receipt_path':str(receiptpath),'receipt_sha256':hashlib.sha256(receiptpath.read_bytes()).hexdigest(),'runtime_version':receipt['runtime_version'],'source_identity':receipt['source_identity'],'records':len(receipt['records']),'recoveries':len(receipt['recovery']),'archived_counts':receipt['counts'],'reference_checks':seen,'gaps':errors,'production_bridge':'NOT_ISSUED','gp5_evidence_approved_for_gp6':'NOT_APPROVED_PENDING_INDEPENDENT_QA'})
print('source',digest(files),'delta',len(delta),'refs',len(seen),'gaps',len(errors))

"""One EMS job; explicit, frozen wire-instruction transform over unchanged v19 engine.
The internal v2 contract retains two backend slots, but this entry permits G01 only.
Actual sent bodies are saved separately from the engine's original context bodies.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO/'semantic_pallet_planner/src'))
from semantic_pallet_planner.jev_select.contracts import digest, canonical
from semantic_pallet_planner.jev_select.ledger import write
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.geometry_jev_protocol import validate_jev_plan, validate_jev_admission
from semantic_pallet_planner.jev_select.geometry_jev_kernel_bridge import target_binding, source_delta
from semantic_pallet_planner.jev_select.geometry_jev_execution import GeometryJevRequestLedger, load_jev_config, validate_jev_request_ledger_binding, run_jev_job
from semantic_pallet_planner.jev_select.geometry_order_execution import validate_monitor_snapshot
from semantic_pallet_planner.jev_select.geometry_order_meter import CallBudget
from semantic_pallet_planner.jev_select.transport import JevTransport

ROOT=Path(__file__).parent
BASE=Path('semantic_pallet_planner/outputs')
CONTROL=BASE/'GEOM_CANDIDATES_GP6_TOP_LOAD_DISABLED_RUN_20261122_01/jobs/G01'
PRIOR=BASE/'GEOM_CANDIDATES_GP6_TOP_LOAD_AUTHORIZED_20261122_01'
SNAP=BASE/'GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01/monitor_snapshot.json'
RUN=ROOT/'run'
INSTRUCTION='Build the stack outward from the pallet corner at the minimum x and minimum y boundaries. On an empty pallet, prefer a floor-level candidate that touches both edges of that corner. For later boxes, extend the stack from that same corner by placing boxes alongside it or on its supported top surfaces. Keep the remaining floor space in large, contiguous areas and avoid narrow gaps. If no candidate follows this preference, choose the best available legal candidate. Return exactly one of the provided Cxx labels.'

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ref(p):return {'path':str(p.relative_to(REPO) if p.is_absolute() else p),'sha256':sha(p)}
def save(name,value):
 p=ROOT/name
 assert not p.exists(),f'NO_OVERWRITE:{name}'
 write(p,value)
 return p

def transform(body):
 wire=copy.deepcopy(body)
 q=wire['questions']['next_action']
 assert q['type']=='choice' and isinstance(q['instructions'],str)
 q['instructions'] += '\n\n'+INSTRUCTION
 assert wire['state']==body['state'] and q['criteria']==body['questions']['next_action']['criteria']
 return wire

class CornerTransport(JevTransport):
 def complete(self,body):
  spec=read(ROOT/'single_experiment_plan_FROZEN.json')
  assert spec['driver_sha256']==sha(__file__) and spec['placement_instruction']==INSTRUCTION
  rows=read(ROOT/'ledgers/requests/requests.json')['requests']
  assert 1<=len(rows)<=19 and all(r['job_id']=='G01' for r in rows)
  wire=transform(body)
  encoded=super().encode(wire)
  idx=len(rows)
  p=RUN/'sent_requests'/f'{idx:02d}.json'
  assert not p.exists(),'REFUSE_REPEAT_SEND'
  p.parent.mkdir(parents=True,exist_ok=True)
  # Persist the exact canonical bytes passed to the unchanged native transport.
  p.write_bytes(encoded)
  (p.with_suffix('.instructions.txt')).write_text(wire['questions']['next_action']['instructions'])
  write(p.with_suffix('.binding.json'),{'version':'gp6_corner_wire_binding_v1','experiment_plan_digest':digest(spec),'runtime_plan_digest':spec['runtime_plan_digest'],'decision_id':rows[-1]['decision_id'],'base_context_body_digest':digest(body),'actual_wire_body_sha256':sha(p),'transform':'append_choice_instructions_only_v1'})
  return super().complete(wire)

def prepare():
 assert not (ROOT/'single_experiment_plan_FROZEN.json').exists(),'ALREADY_PREPARED'
 plan=read(PRIOR/'gp6_top_load_plan_FROZEN.json')
 # Preserve engine matrix/schema; a separate explicit envelope restricts dispatch to EMS.
 plan.update(shared_max_sends=19,model_calls_max=19,
  request_ledger_path=str((ROOT/'ledgers/requests/requests.json').relative_to(REPO)),
  call_ledger_path=str((ROOT/'ledgers/calls/calls.json').relative_to(REPO)))
 assert plan['source_identity']==digest(source_manifest())
 validate_jev_plan(plan)
 pp=save('runtime_plan_FROZEN.json',plan)
 prior_bridge=read(PRIOR/'kernel_bridge_APPROVED.json')
 target=target_binding(plan,read(SNAP))
 review=read(PRIOR/'kernel_applicability_review_APPROVED.json')
 review.update(target=target,reviewer='Execution binding under explicit current user authorization; NOT a new independent review',conclusion='One EMS corner-prompt job only, unchanged physical pipeline',limitations='REFERENCE_BINDINGS_ONLY_NO_HISTORICAL_EXECUTION; single exposed-source run; no generalized gain claim')
 rp=save('kernel_applicability_review_BOUND.json',review)
 bridge={**prior_bridge,'target':target,'applicability_review':ref(rp)}
 bp=save('kernel_bridge_BOUND.json',bridge)
 spec={'version':'gp6_corner_single_experiment_plan_v1','status':'FROZEN','date':'2026-11-23','head':__import__('subprocess').check_output(['git','rev-parse','HEAD'],text=True).strip(),
  'jobs':[{'job_id':'G01','backend':'ems_surface_hybrid_v1','task_id':'NEW_00100027_controlled_base'}],
  'model':'jev-1.14.0','endpoint':'https://api.typesafe.ai/v1/systemone','per_job_max_sends':19,'shared_max_sends':19,'single_execution':True,'max_retries':0,
  'runtime_plan':ref(pp),'runtime_plan_digest':digest(plan),'internal_unused_slot':'G00 exists only to satisfy unchanged v2 matrix schema and MUST NOT be dispatched',
  'placement_instruction':INSTRUCTION,'wire_transform':'append_choice_instructions_only_v1','driver_sha256':sha(__file__),
  'baseline':str(CONTROL),'packaging_top_load_limit_enabled':False,'kernel_bridge':ref(bp),'monitor_snapshot':ref(SNAP),'run_root':str(RUN.relative_to(REPO))}
 save('single_experiment_plan_FROZEN.json',spec)
 authorization={'scope':plan['scope'],'plan_digest':digest(plan),'status':'APPROVED','experiment_plan_digest':digest(spec),'authority':'explicit user message 2026-11-23','allowed_jobs':['G01'],'endpoint':spec['endpoint'],'allowed_payload':'current observable state and candidate actions only','user_acknowledges_data_leaves_host':True,'per_job_max_sends':19,'shared_max_sends':19,'single_run':True,'no_implicit_retry':True}
 ap=save('user_authorization.json',authorization)
 sr=save('scope_binding.json',{**authorization,'new_independent_review':False,'basis':'Current explicit user instruction, unchanged production source and archived exact monitor; no additional independent QA claimed'})
 api=save('api_spec_check_VERIFIED.json',{'status':'VERIFIED','date':'2026-11-23','model':spec['model'],'endpoint':spec['endpoint'],'official_sources':['https://docs.typesafe.ai/models','https://docs.typesafe.ai/api/system-one','https://docs.typesafe.ai/primitives/choice'],'model_calls':0})
 admission=read(PRIOR/'order_admission_APPROVED.json')
 admission.update(plan_digest=digest(plan),authorization=ref(ap),review=ref(sr),api_spec_check=ref(api))
 save('order_admission_BOUND.json',admission)
 assert validate_jev_admission(plan,read(SNAP),admission,bridge)
 assert not RUN.exists() and not Path(plan['request_ledger_path']).exists() and not Path(plan['call_ledger_path']).exists()
 GeometryJevRequestLedger(Path(plan['request_ledger_path']).parent,plan_digest=digest(plan),per_job_max_sends=19,shared_max_sends=19,allow_real_transport=True,runtime_version=plan['runtime_version'])
 CallBudget(plan['call_ledger_path'],plan,evidence='REAL_KERNEL',job_id='INITIALIZATION_ONLY')
 # Offline transformation check against an archived control request: only text changes.
 control=read(CONTROL/'record.json')
 first=next(e for e in control['checkpoint']['events'] if e.get('context',{}).get('request_body'))
 original=first['context']['request_body'];wire=transform(original)
 stripped=copy.deepcopy(wire);stripped['questions']['next_action']['instructions']=original['questions']['next_action']['instructions']
 assert stripped==original and wire['questions']['next_action']['instructions'].endswith(INSTRUCTION)
 (ROOT/'final_selection_instructions.txt').write_text(wire['questions']['next_action']['instructions'])
 save('preparation_receipt.json',{'runtime_plan_digest':digest(plan),'experiment_plan_digest':digest(spec),'offline_transform_only_text':True,'network_calls':0,'dispatches':0,'source_unchanged':True,'internal_unused_job':'G00','actual_dispatch_allowlist':['G01']})
 print(canonical({'status':'PREPARED','runtime_plan_digest':digest(plan),'experiment_plan_digest':digest(spec)}),flush=True)

def execute():
 started=time.time();preflight=False;dispatched=False
 try:
  spec=read(ROOT/'single_experiment_plan_FROZEN.json');plan=read(ROOT/'runtime_plan_FROZEN.json')
  assert spec['driver_sha256']==sha(__file__) and digest(plan)==spec['runtime_plan_digest']
  assert spec['jobs']==[{'job_id':'G01','backend':'ems_surface_hybrid_v1','task_id':'NEW_00100027_controlled_base'}]
  for k in ('runtime_plan','kernel_bridge','monitor_snapshot'): assert sha(spec[k]['path'])==spec[k]['sha256']
  assert not RUN.exists(),'RUN_ALREADY_EXISTS'
  snap=read(SNAP);validate_monitor_snapshot(snap)
  bridge=read(ROOT/'kernel_bridge_BOUND.json');admission=read(ROOT/'order_admission_BOUND.json')
  assert validate_jev_admission(plan,snap,admission,bridge)
  dp=BASE/'GEOM_CANDIDATES_GP6_TOP_LOAD_SWITCH_20261122_01/formal_jev_driver.py'
  ms=importlib.util.spec_from_file_location('original_driver_helpers',dp);mod=importlib.util.module_from_spec(ms);ms.loader.exec_module(mod)
  mod.EXPECTED_SHARED_MAX_SENDS=19
  mod.check_ledger_run_root_separation(plan,RUN)
  _,req_before=mod.check_initial_request_ledger_readonly(plan);_,call_before=mod.check_initial_call_ledger_readonly(plan)
  adapted=mod.load_adapted_tasks(plan)['NEW_00100027_controlled_base']
  cfg=load_jev_config(plan,'G01',monitor_snapshot=snap,admission=admission,kernel_receipt=bridge)
  prior_cfg=read(CONTROL/'config.json')
  # Original display seed, candidate limits, publication, physical and monitor settings.
  for k in ('candidate_backend','display_seed','top_k','candidate_limits','stability_monitor','packaging_top_load_limit_enabled'):
   if k in prior_cfg: assert cfg[k]==prior_cfg[k],f'CONTROL_DRIFT:{k}'
  assert cfg['candidate_backend']=='ems_surface_hybrid_v1' and cfg['packaging_top_load_limit_enabled'] is False and cfg['max_retries']==0
  assert mod.check_initial_request_ledger_readonly(plan)[1]==req_before and mod.check_initial_call_ledger_readonly(plan)[1]==call_before
  preflight=True
  RUN.mkdir()
  write(RUN/'preflight_receipt.json',{'status':'PASS','job':'G01','source_identity':plan['source_identity'],'initial_request_ledger_sha256':req_before,'initial_call_ledger_sha256':call_before,'runtime_plan_digest':digest(plan),'experiment_plan_digest':digest(spec)})
  ledger=GeometryJevRequestLedger(Path(plan['request_ledger_path']).parent,plan_digest=digest(plan),per_job_max_sends=19,shared_max_sends=19,allow_real_transport=True,runtime_version=plan['runtime_version'])
  transport=CornerTransport(cfg,api_key_file=Path('typesafe_api_key.md'))
  validate_jev_request_ledger_binding(plan,cfg,ledger,transport,real_authorized=True)
  def checkpoint(cp):
   p=RUN/'jobs/G01/checkpoint.json';p.parent.mkdir(parents=True,exist_ok=True);write(p,cp)
   placed=cp.get('state',{}).get('placed_items',[])
   print(canonical({'job':'G01','phase':cp.get('phase'),'placed_items':len(placed),'reason':cp.get('reason')}),flush=True)
  dispatched=True
  ep=run_jev_job(plan,'G01',adapted,monitor_snapshot=snap,admission=admission,root=RUN,transport=transport,ledger=ledger,kernel_receipt=bridge,on_checkpoint=checkpoint)
  summary=ep['summary']
  receipt={'version':'gp6_corner_single_driver_receipt_v1','status':'FINISHED','preflight':'PASS','dispatched_jobs':['G01'],'runtime_plan_digest':digest(plan),'experiment_plan_digest':digest(spec),'summary':summary,'requests':ledger.statistics('G01'),'duration_s':time.time()-started,'no_implicit_retry':True}
  write(RUN/'driver_receipt.json',receipt)
  print(canonical(receipt),flush=True)
  return 0 if summary['termination_class'] in ('COMPLETE','NO_CANDIDATE','PREDICTED_STATIC_INSTABILITY','UNASSESSABLE') else 1
 except BaseException as exc:
  # No credential/provider strings are included; retain stage + exception class/code.
  receipt={'version':'gp6_corner_single_failure_v1','preflight_passed':preflight,'dispatched':dispatched,'job':'G01','type':type(exc).__name__,'code':getattr(exc,'code',None),'assertion':str(exc) if isinstance(exc,AssertionError) else None,'no_retry':True}
  write(ROOT/'startup_or_execution_failure.json',receipt)
  print(canonical(receipt),flush=True)
  return 1

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');parser.add_argument('--execute',action='store_true');args=parser.parse_args()
 assert args.prepare != args.execute,'SELECT_ONE_MODE'
 if args.prepare:prepare()
 else:sys.exit(execute())

"""P1 delivery-only draft, not launch/admission issuance. No freezer or loop."""
import copy,json,socket
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.contracts import digest,canonical
from semantic_pallet_planner.jev_select.stability import monitor,exact_adapter,balance_adapter,balance_network

OUT=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P1_20261117_01/p2_draft');OUT.mkdir(exist_ok=True)
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
with ExitStack() as stack:
 def no(*a,**kw):raise AssertionError('PREPARATION_REAL_CALL_FORBIDDEN')
 for obj,name in [(monitor,'exact_freeze'),(monitor,'freeze'),(exact_adapter,'assess_candidate'),(balance_adapter,'assess_candidate'),(balance_network,'solve_network'),(balance_network,'linprog'),(socket.socket,'connect')]:stack.enter_context(patch.object(obj,name,side_effect=no))
 tasks=[]
 for case in ('K01','K02'):
  raw=canonical(p.synthetic_task(case)).encode();(OUT/(case+'_task.json')).write_bytes(raw)
  t=p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=p.sha(raw));tasks.append(t)
  save(case+'_identity.json',t['identity'])
 plan=p.prepare_order_plan(tasks,data_identity=digest('GP5_P2_SYNTHETIC_FIXED_V1'),scope=p.ACCEPTANCE)
 save('acceptance_plan_DRAFT.json',plan)
 metadata=json.loads(Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N3_20261117_01/cases/ems_surface_hybrid_v1_stable/config.json').read_bytes())['stability_monitor']
 save('launch_binding_TEMPLATE_NOT_A_RECEIPT.json',{'document_type':'P2_LAUNCH_TEMPLATE_NOT_EXECUTABLE','launch_version_proposed':'geometry_kernel_launch_v1','plan_draft_digest':digest(plan),
   'source_identity':plan['source_identity'],'environment_digest':plan['environment_digest'],'monitor_metadata_digest':digest(metadata),
   'actual_freeze':'NOT_RUN','external_authorization_reference':None,'P1_independent_QA_reference':None,
   'launch_status':'NOT_ISSUED','requires_new_FROZEN_plan_digest_and_shared_counter_path':True,
   'final_kernel_receipt_required_to_launch':False,'final_kernel_receipt_required_for_formal_orders':True})
 save('cases_and_bounds.json',{'status':'DRAFT_NOT_PERMISSION','public_jobs':plan['jobs'],'public_case_count':4,
   'expected_public_assessment_entries':6,'assessment_entries_hard_max':12,'actual_solver_calls_hard_max':512,
   'counts_authorized_now':{'assessment_entries':0,'solver_calls':0},'extra_seeds':0,
   'K01':{'items':1,'container_mm':[600,400,500],'box_mm':[100.0,80.0,60.0],'mass_kg':1,'synthetic_capacity_kg':10,'evidence_required':'REAL_SELECTED_MONITOR_COMMIT'},
   'K02':{'items':2,'container_mm':[100,80,180],'box_mm':[100.0,80.0,60.0],'target_pose':[0,0,60,0],'initial_pool':2,'second_pool':1,'selector':'local_first_test_double','acceptance_specific_selector':'NOT_NEEDED','P1_evidence':'final_evidence/test_two_backends_two_methods_complete_and_k02_exact_target/K02_reachability.json'},
   'K03_adapter_only':{'container_mm':[1000,800,1000],'placed':[{'id':'ground','size_mm':[60,200,100],'mass_kg':1,'pose':[0,0,0]}, {'id':'shelf','size_mm':[200,200,100],'mass_kg':1,'pose':[0,0,100]}],'candidate':{'id':'top','size_mm':[100,100,100],'mass_kg':10,'pose':[60,0,200]},'expected_status_reference':'UNSTABLE analytic upper COM600/11 outside [-30,30]','scope':'REAL_KERNEL_ADAPTER_ONLY_NOT_PUBLIC_E2E','max_extra_assessment_entries':2,'included_in_total_12':True,'P1_execution':'NOT_RUN'},
   'K03_floating_boundary':{'target_pose':[0,0,60.0004,0],'original_physics_rejection_means_kernel_calls':0,'P1_execution':'NOT_RUN'},
   'recovery':'one saved prefix per case; SELECTED pending assessment counts toward12; MONITORED/COMMITTED no new assessments; no full historical replay',
   'stop':['unreachable target','identity drift','unexpected numerical/technical error','budget exhaustion','UNKNOWN_CALL','missing/corrupt durable evidence','test double in real scope'],
   'integer_multistep_issue':'GP5-P1-NUM-01 OPEN; real order readiness blocked; float synthetic success not a repair',
   'formal_8job_bounds_DRAFT_ONLY':{'assessment_entries':152,'solver_calls':8192,'jobs':8,'source_families':1}})
print('P2_DRAFT_ONLY; FREEZE/KERNEL/LP/ORDERS=0')

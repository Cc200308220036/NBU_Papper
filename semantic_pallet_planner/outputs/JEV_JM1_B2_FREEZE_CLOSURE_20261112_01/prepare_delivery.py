"""Offline-only B2 closure package assembly; existing materials are never replaced."""
import json
from pathlib import Path
import subprocess
from semantic_pallet_planner.jev_select import packaging_jev_training_freeze as f
from semantic_pallet_planner.jev_select import packaging_jev_training_plan as p
from semantic_pallet_planner.jev_select import packaging_jev_v13 as v13
from semantic_pallet_planner.jev_select.experiment import source_manifest

root=Path.cwd();out=Path(__file__).resolve().parent;relative=out.relative_to(root)
def save(name,value):
 (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
ready=f.freeze_readiness(root=root)
if ready['missing']:
 save('freeze_readiness.json',ready)
 raise SystemExit('DEFER: required QA unavailable; no plan/freeze/permit issued')
value=p.prepare_plan(root=root,output=relative/'materials',catalog_path=p.BASE+'JEV_JM1_B2_20261111_01/task_source_candidates.json',inputs=p.REQUIRED_INPUTS)
reference=p.ref((relative/'materials/training_plan.json').as_posix(),root=root)
receipt=f.freeze_plan(reference,root=root)
save('formal_freeze.json',receipt)
save('freeze_validation.json',f.validate_frozen_plan(receipt,root=root))
save('preparation_validation.json',p.validate_plan(value,root=root))
save('source_manifest.json',source_manifest())
save('source_identity.json',{'version':'jm_b2_closure_source_identity_v1',
 'specified_base':'c21d6b511e4c33e5ff0acfd4a51931c896edb60d',
 'actual_entry_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
 'entry_difference':'90bd018d adds independent B2 QA/report/index only; no runtime/test change from specified base',
 'runtime_identity':v13.identity(),'source_manifest':'source_manifest.json',
 'operation_root':receipt['operation_root'],'runtime_root':receipt['runtime_root'],
 'freeze_identity':receipt['receipt_digest'],'preparation_identity':value['plan_digest'],
 'why_new_identity':receipt['identity_change_reason'],
 'dirty_tree_policy':'Actual package file bytes are pinned; HEAD alone is provenance. No commit created.',
 'unchanged_study':{'tasks_order_sources_sampling_repeats':'VERIFIED_SAME_AS_HISTORICAL',
 'budget':[103,564,210,774,877],'data_physical_monitor_algorithm':'UNCHANGED'},
 'historical_identity':'PRESERVED_NOT_RESIGNED'})
save('budget_receipt.json',{'version':'jm_b2_closure_budget_v1','freeze_digest':receipt['receipt_digest'],
 'budget':receipt['budget'],'jobs':receipt['jobs'],'execution_authorized':False,
 'actual_model_calls':0,'actual_baselines':0,'actual_suffixes':0,
 'concrete_suffix_jobs':p.DEFER,'cost':'NOT_RUN',
 'repeat_allocation':'Stage capacity envelope only; concrete point selection by existing repeat_priority before results. No reuse of unused sends.'})
save('interface_receipt.json',{'version':'jm_b2_closure_interface_v1',
 'module':'semantic_pallet_planner.jev_select.packaging_jev_training_freeze',
 'protocol':f.JM_TRAINING_FREEZE_VERSION,'schema':'schemas/jm_training_freeze_v1.schema.json',
 'registry':'packaging_versions.JM_TRAINING_FREEZE_PROTOCOLS',
 'interfaces':['freeze_readiness(root=...)','freeze_plan(plan_ref,root=...)','validate_frozen_plan(receipt,root=...)','require_send_authorization(receipt,root=...,stage=...,permit=None)'],
 'CLI':'PYTHONPATH=semantic_pallet_planner/src python -m semantic_pallet_planner.jev_select.packaging_jev_training_freeze {validate|baseline-gate|suffix-gate} INPUT --root .',
 'preparation_protocol':'Unchanged jev_jm_training_plan_v1; inner formal_frozen=false is required by old schema. New upper receipt formal_frozen=true is the final offline plan identity.',
 'formal_scope':'B2 task/config/source/runtime/storage/budget/QA freezing only; independent review of this delivery PENDING',
 'QA-JMB2P-01':'Inventory inconsistency is an actual removal regardless of host file visibility; complete-QA and explicit missing-QA DEFER positive cases added; original18 archive unchanged.',
 'reuse':['v1 prepare_plan/validate_plan, v13 frozen config/execution/schedule identity','unchanged B1 sampling policy and B2 repeat_priority'],
 'no_calls':['episode','transport','credential','candidate rebuild','sampling','LP'],
 'schema_boundary':'Independent closed Draft202012 schema; original B2 template/plan schemas unchanged',
 'send_gates':receipt['gates'],'permit_issuance':'NONE; both gates always refuse even a fake authorized permit',
 'C1_contract':'Separately authorized baseline uses frozen v13 jobs. Only then closed public projections may materialize epsilon/points/full frozen pools/exact actions/concrete repeats and budgets. C1 can stop before any suffix.',
 'C2_contract':'Consumes only a separately frozen concrete C1 fork plan plus independent C2 authorization, never this B2 receipt as a sending permit.'})
save('qa_evidence_index.json',{'version':'jm_b2_closure_qa_inputs_v1','qa_refs':receipt['qa_refs'],
 'qa_audit':receipt['qa_audit'],'historical_plan':receipt['historical_plan_ref'],
 'historical_manifest':receipt['historical_manifest_ref'],
 'archived_tests':'Original18 preserved; not rerun as historical evidence. This delivery has its own test artifacts.',
 'source_audit':value['audit_ref'],'source_exposure_note':'Existing exposed train only,4 source labels/3 conservative components; no unseen/feasibility claim.',
 'materialization':receipt['materialization']})
save('operations.json',{'execution_authorized':False,'actual':dict.fromkeys([
 'real_model_calls','credential_reads','network','episodes','baselines','suffixes','candidate_rebuilds','sampling','LP','new_training_evaluation_data','epsilon_materialization','installs','downloads','third_party_updates','subagents','git_add','commit','push'],0),
 'real_service':'NOT_RUN','real_LP':'NOT_RUN','research_result':'NOT_RUN'})
print(json.dumps({'freeze_identity':receipt['receipt_digest'],'plan_identity':value['plan_digest'],'qa_refs':len(receipt['qa_refs']),'validation':'PASS_OFFLINE','execution_authorized':False},ensure_ascii=False))

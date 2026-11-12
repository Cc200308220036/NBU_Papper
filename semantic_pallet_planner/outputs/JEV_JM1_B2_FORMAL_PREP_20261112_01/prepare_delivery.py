"""Explicit offline artifact preparation; fails if material output already exists."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess

from semantic_pallet_planner.jev_select import packaging_jev_training_plan as p
from semantic_pallet_planner.jev_select import packaging_jev_v13 as v13
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.packaging_runtime import INSTRUCTION, QUESTION, OBJECTIVE, physical_manifest

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
REL = OUT.relative_to(ROOT)

def save(name, value):
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n')

value = p.prepare_plan(root=ROOT, output=REL/'materials',
    catalog_path='semantic_pallet_planner/outputs/JEV_JM1_B2_20261111_01/task_source_candidates.json',
    inputs=p.REQUIRED_INPUTS, count=6)
checked = p.validate_plan(value, root=ROOT)
save('saved_validation.json', checked)
save('source_manifest.json', source_manifest())
save('source_identity.json', {'entry_head':'92c024097111b700b859b5081c2adcb4467803ae',
    'actual_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
    'identity':v13.identity(), 'historical_identity':'UNCHANGED_NOT_RESIGNED',
    'source_manifest':'source_manifest.json', 'python':platform.python_version(),
    'git_head_is_provenance_not_replacement_for_bytes':True})
ex = p.load(value['assignments'][0]['execution_ref'], root=ROOT)
save('runtime_declaration.json', {'model':value['model_declaration'],
    'instruction':INSTRUCTION, 'question':QUESTION, 'objective':OBJECTIVE,
    'prompt_identity':p.digest([INSTRUCTION, QUESTION, OBJECTIVE]),
    'full_prompt_code_identity':'source_manifest.json (including packaging_remote_protocol.py and context/body builders)',
    'candidate_physical_manifest':physical_manifest(),
    'monitor':ex['config']['stability_monitor'],
    'config_and_strategy':'materials/execution_1.json through execution_6.json',
    'actual_credentials':'NOT_READ', 'actual_service_and_solver':'NOT_RUN',
    'storage_binding':'v13 schedules/executions bind absolute storage roots; relocation requires a new plan before execution, never reseal historical executions'})
audit = p.load(value['audit_ref'], root=ROOT)
selected_components = {r['component'] for r in value['assignments']}
save('role_reservations.json', {'version':'jm_training_role_reservations_v1',
    'source_audit_ref':value['audit_ref'], 'selected_order':[r['task_id'] for r in value['assignments']],
    'components':[{'component':p.digest(c), 'members':c['tasks'],
        'reserved_role':'training' if p.digest(c) in selected_components else 'DEFER_NOT_ASSIGNED',
        'cross_role_use':'FORBIDDEN_UNTIL_NEW_AUDITED_DISJOINT_PLAN'} for c in audit['grouping']['material_components']],
    'selected_source_groups':len({r['relation']['source_group'] for r in value['assignments']}),
    'selected_conservative_components':len(selected_components),
    'independent_real_sources':'UNKNOWN_NOT_CERTIFIED', 'feasibility':'UNKNOWN',
    'synthetic_packaging_notice':'Packaging capacity is synthetic; physical measurement status unverified.',
    'historical_exposure':'Retained, not reset; source/variant/shared-SKU closure is reserved together.'})
save('interface_receipt.json', {'version':'jm_training_plan_interface_receipt_v1',
    'module':'semantic_pallet_planner.jev_select.packaging_jev_training_plan',
    'protocol':p.JM_TRAINING_PLAN_VERSION, 'schema':'jm_training_plan_v1.schema.json',
    'registry':'packaging_versions.JM_TRAINING_PLAN_PROTOCOLS (independent offline route)',
    'interfaces':['prepare_plan(root,output,catalog_path,inputs,count=6)', 'validate_plan(plan,root)',
                  'require_send_authorization(plan,root,stage,permit=None)', 'budgets(assignments)', 'select_tasks(audit,count)'],
    'schema_validation':'Existing jsonschema Draft202012Validator; closed nested plan fields; separate from old B2 stdlib subset schema',
    'reuse':['v13.load_config/preflight/identity/freeze_execution/validate_execution/freeze_schedule/validate_schedule',
            'packaging_runtime.runtime_task (saved input conversion only)',
            'B2.read_saved/relation_components/repeat_priority', 'B1 policy identity and closed public projection protocol'],
    'no_calls':['run_episode', 'run_execution', 'run_scheduled', 'sample', 'capture_start', 'candidate generation', 'monitor assessment', 'LP', 'transport', 'credentials'],
    'baseline_gate':'Always refuses in this offline protocol; separate execution admission required.',
    'suffix_gate':'Always refuses; C1 concrete fork plan remains unmaterialized and C2 is separate.',
    'materialization_contract':{'C1':'Only real saved baseline public projection may materialize real epsilon/points/actions; full private task counts only budget side; freeze complete pools/actions/repeats and per-job integer sends before C2; C1 may stop.',
      'C2':'Must consume separately frozen concrete plan and v13 execution-specific permits. Cannot consume this prepared plan or old template as authorization.'},
    'repeat_rule':'B2.repeat_priority alternating OPENING/NONEMPTY, unseen conservative component first then task order/decision digest; all existing branches at <=4 selected points repeat once; freeze before any suffix result.',
    'epsilon_rule':'B1 pinned policy SHA; nearest-rank Q25 smallest positive relative native gaps, capped at 1/10; no imputation; NOT_MATERIALIZED_DEFER_C1',
    'budget_bound':'Initial: 3*(N-1) OPENING + 3*max(0,N-2) NONEMPTY per task. Repeats: sum four largest per-stage 3*remaining caps; concrete C1 budgets must be <= reserved envelope. No refill/transfer.'})
save('commands_and_scope.json', {'commands':[
 'PYTHONPATH=semantic_pallet_planner/src python -m pytest semantic_pallet_planner/tests/unit/test_packaging_jev_training_plan.py -q --junitxml=semantic_pallet_planner/outputs/JEV_JM1_B2_FORMAL_PREP_20261112_01/constructed_junit.xml',
 'PYTHONPATH=semantic_pallet_planner/src python semantic_pallet_planner/outputs/JEV_JM1_B2_FORMAL_PREP_20261112_01/prepare_delivery.py',
 'PYTHONPATH=semantic_pallet_planner/src python semantic_pallet_planner/outputs/JEV_JM1_B2_FORMAL_PREP_20261112_01/verify_delivery.py'],
 'actual_operations':dict.fromkeys(['real_model_calls','credential_reads','network','orders','suffixes','candidate_rebuilds','LP','new_training_evaluation_data','epsilon_materialization','installs','downloads','third_party_updates','subagents','git_add','commit','push'],0),
 'test_scope':'Offline actual saved task conversion/config/schedule construction and refusal tests only; traps forbid execution and solver.'})
print(json.dumps(checked,ensure_ascii=False))

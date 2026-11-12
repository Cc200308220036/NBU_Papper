"""JM1-B2 actual offline preparation. No dispatch, credential or solver entry.

This protocol is separate from the constructed B2 template. Private task counts
are used only for budgets. No probabilities, real points or permits are created.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from . import packaging_jev_training_template as template
from . import packaging_jev_sampling as sampling
from .packaging_versions import JM_TRAINING_PLAN_VERSION

require = sampling.require
digest = sampling.digest
QA_ROOT = 'semantic_pallet_planner/outputs/JEV_JM_V13_FIX_QA_20261112_01/'
QA_REPORT = 'docs/03_阶段产出分析/Jev/Jev_JM1-v13整改独立复核与B2正式计划准备限定准入_20261112_01.md'
QA_REQUIRED = [QA_REPORT] + [QA_ROOT+n+'.json' for n in
                            ('quality_review', 'next_stage_admission', 'handoff', 'delivery_manifest')]
RULE = 'CONSERVATIVE_COMPONENT_DIGEST_THEN_TASK_BYTE_DIGEST_ROUND_ROBIN_TRAIN_ONLY_V1'
DEFER = 'NOT_MATERIALIZED_DEFER_C1'
BASE = 'semantic_pallet_planner/outputs/'
REQUIRED_INPUTS = [
    'docs/02_阶段实施方案/Jev/Jev经验构建检索与无经验Jev分叉改进分阶段开发方案_20261109.md',
    *[BASE+'JEV_JM0_B_20261111_01/'+n+'.json' for n in
      ('research_contract', 'data_admission_plan', 'exposure_register', 'sampling_policy',
       'parameter_register', 'budget_and_stop_contract', 'admission_policy', 'analysis_contract',
       'method_design', 'handoff', 'delivery_manifest')],
    *[BASE+d+'/'+n+'.json' for d in ('JEV_JM1_V13_FIX_20261112_01',
       'JEV_JM1_V13_ENGINEERING_20261112_01', 'JEV_JM1_B1_20261111_01', 'JEV_JM1_B2_20261111_01')
      for n in ('handoff', 'delivery_manifest', 'interface_receipt', 'source_identity')],
    *[BASE+'DATA_JEV_PACKAGING_LOAD_20261102_02/'+n+'.json' for n in
      ('manifest', 'handoff', 'source_manifest', 'split_manifest')]]


def ref(path, *, root):
    return template.saved_ref(path, root=root)


def load(saved, *, root):
    return template.read_saved(saved, root=root)


def _sources(catalog, *, root):
    """Audit every candidate byte, including excluded familiar synthetic tasks."""
    require(catalog.get('version') == 'jm1_b2_material_source_candidates_v1', 'PLAN_CATALOG_VERSION')
    rows = catalog['candidates']
    require(len({r['existing_id'] for r in rows}) == len(rows), 'PLAN_DUPLICATE_CANDIDATE')
    grouping = template.relation_components([r['relation'] for r in rows])
    components = {t:digest(c) for c in grouping['material_components'] for t in c['tasks']}
    audit = []
    for row in rows:
        task = load(row['material_ref'], root=root)
        source = load(row['source_register_ref'], root=root)
        require(task['task_id'] == row['existing_id'] == row['relation']['task_id'], 'PLAN_SOURCE_TASK')
        require(len(task['items']) == row['audit_full_item_count'] > 0, 'PLAN_ITEM_COUNT')
        require(task['arrival_order'] == [x['item_id'] for x in task['items']], 'PLAN_ARRIVAL_ORDER')
        require(task.get('source_group_id', task.get('source_group')) == row['relation']['source_group'],
                'PLAN_SOURCE_GROUP')
        require(source['id'] == task['task_id'] and source['file_sha256'] == row['material_ref']['sha256'] and
                source['data_path'] == row['material_ref']['path'] and source['data_identity'] == row['data_identity'] and
                source.get('source_group', source.get('source_group_label')) == row['relation']['source_group'] and
                source['history'] == row['history'] and
                row['exposure']['strict_unseen_eligible'] is False,
                'PLAN_EXPOSURE_REQUIRED')
        audit.append({'task_id':task['task_id'], 'task_ref':row['material_ref'],
                      'source_register_ref':row['source_register_ref'],
                      'component':components[task['task_id']], 'relation':row['relation'],
                      'exposure':row['exposure'], 'history':row['history'],
                      'data_identity':row['data_identity'], 'full_items':len(task['items']),
                      'partition':task['partition'], 'variant':task.get('layer', 'NOT_DECLARED'),
                      'feasibility':'UNKNOWN', 'train_eligible':task['partition'] == 'train'})
    return audit, grouping


def _data_admission(assignments, refs, *, root):
    inputs = {r['path']:r for r in refs}
    data_root = BASE+'DATA_JEV_PACKAGING_LOAD_20261102_02/'
    manifest = load(inputs[data_root+'manifest.json'], root=root)
    split = load(inputs[data_root+'split_manifest.json'], root=root)
    groups = {g['source_group_id']:g for g in split['groups']}
    for row in assignments:
        task = load(row['task_ref'], root=root)
        require(row['data_identity'] == manifest['data_identity'], 'PLAN_DATA_IDENTITY')
        group = groups.get(row['relation']['source_group'])
        require(group is not None and group['partition'] == 'train' and
                task['scenario_id'] in group['scenario_ids'], 'PLAN_GROUP_SPLIT')


def select_tasks(audit, count):
    require(type(count) is int and 1 <= count <= 6, 'PLAN_TASK_CAP')
    queues = {}
    for row in audit:
        if row['train_eligible']:
            queues.setdefault(row['component'], []).append(row)
    for queue in queues.values():
        queue.sort(key=lambda r:(r['task_ref']['sha256'], r['task_id']))
    result = []
    while any(queues.values()) and len(result) < count:
        for key in sorted(queues):
            if queues[key] and len(result) < count:
                result.append(queues[key].pop(0))
    require(len(result) == count, 'PLAN_INSUFFICIENT_TRAIN_TASKS')
    return result


def budgets(assignments):
    """Capacity reservations only, not real point/branch/repeat identities."""
    capacities = []
    for row in assignments:
        n = row['full_items']
        for stage, placed_min in [('OPENING', 0), ('NONEMPTY', 1)]:
            capacities.append({'task_id':row['task_id'], 'stage':stage,
                               'branch_capacity':3, 'placed_min':placed_min,
                               'per_branch_send_upper':max(0, n-placed_min-1)})
    initial = sum(3*r['per_branch_send_upper'] for r in capacities)
    # Safe maximum over any <=4 stage slots. Exact priority/repeats materialize C1.
    repeated = sum(sorted((3*r['per_branch_send_upper'] for r in capacities), reverse=True)[:4])
    baseline = sum(r['full_items'] for r in assignments)
    return {'baseline_jobs':[{'task_id':r['task_id'], 'job_id':r['job_id'],
                              'send_upper':r['full_items']} for r in assignments],
            'baseline_send_upper':baseline, 'point_capacities':capacities,
            'point_cap':len(capacities), 'initial_suffix_cap':3*len(capacities),
            'repeat_point_cap':min(4, len(capacities)), 'repeat_suffix_cap':3*min(4, len(capacities)),
            'total_suffix_cap':3*len(capacities)+3*min(4, len(capacities)),
            'initial_suffix_send_upper':initial, 'repeat_suffix_send_upper':repeated,
            'suffix_send_upper':initial+repeated, 'global_send_upper':baseline+initial+repeated,
            'concrete_suffix_jobs':DEFER, 'unused_budget':'NONTRANSFERABLE_NO_REFILL'}


def prepare_plan(*, root, output, catalog_path, inputs, count=6):
    """Creates new saved configs/executions/schedule; never initializes an episode."""
    from . import packaging_jev_v13 as v13
    from .packaging_runtime import runtime_task
    root = Path(root).resolve(); output = Path(output)
    target = (root/output).resolve()
    require(not output.is_absolute() and target.is_relative_to(root), 'PLAN_OUTPUT_SCOPE')
    require(not target.exists(), 'PLAN_OUTPUT_EXISTS')
    catalog_ref = ref(catalog_path, root=root)
    audit, grouping = _sources(load(catalog_ref, root=root), root=root)
    selected = select_tasks(audit, count)
    # Missing QA is preserved as DEFER; no invented digest for absent material.
    present = [ref(p, root=root) for p in QA_REQUIRED if (root/p).is_file()]
    missing = [p for p in QA_REQUIRED if not (root/p).is_file()]
    require(set(inputs) == set(REQUIRED_INPUTS) and len(inputs) == len(REQUIRED_INPUTS), 'PLAN_REQUIRED_INPUTS')
    input_refs = [ref(p, root=root) for p in inputs]
    _data_admission(selected, input_refs, root=root)
    target.mkdir(parents=True)
    def save(name, value):
        (target/name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n')
        return ref((output/name).as_posix(), root=root)
    assignments = []; executions = []
    for i, row in enumerate(selected):
        task = runtime_task(load(row['task_ref'], root=root))
        config = v13.load_config(data_identity=row['data_identity'], task_digest=digest(task), mode='REMOTE_INJECTED')
        ex = v13.freeze_execution(task, config, job_id='JM1_C1_'+row['task_id'],
                                  root=target/'future_runs'/f'baseline_{i+1}')
        executions.append(ex)
        assignments.append({**copy.deepcopy(row), 'ordinal':i+1, 'wave':1+i//3,
                            'slot_id':f'W{1+i//3}S{1+i%3}', 'role':'training',
                            'job_id':ex['job_id'], 'arrival_digest':digest(task['items']),
                            'runtime_task_digest':digest(task),
                            'execution_ref':save(f'execution_{i+1}.json', ex)})
    schedule = v13.freeze_schedule(executions, root=target/'future_runs',
                                   global_max_sends=sum(r['full_items'] for r in assignments))
    plan = {'version':JM_TRAINING_PLAN_VERSION, 'state':'PREPARED_OFFLINE',
            'execution_authorized':False, 'formal_frozen':False, 'selection_rule':RULE,
            'requested_count':count, 'smaller_scope_reason':'NONE' if count == 6 else 'EXPLICIT_SMALLER_OFFLINE_SCOPE_NO_REFILL',
            'catalog_ref':catalog_ref, 'input_refs':input_refs, 'qa_refs':present, 'missing_qa':missing,
            'audit_ref':save('source_exposure_audit.json', {'rows':audit, 'grouping':grouping}),
            'assignments':assignments, 'schedule_ref':save('baseline_schedule.json', schedule),
            'runtime_identity':v13.identity(), 'budget':budgets(assignments),
            'sampling':{'protocol':sampling.JM_SAMPLING_VERSION, 'policy_sha256':sampling.POLICY_SHA256,
                        'epsilon':DEFER, 'points':DEFER, 'exact_actions':DEFER,
                        'repeat_rule':'packaging_jev_training_template.repeat_priority',
                        'repeat_rule_digest':digest(Path(template.__file__).read_text()),
                        'input_boundary':'B1_CLOSED_PUBLIC_PROJECTION_ONLY_NO_TERMINAL_OR_MONITOR'},
            'gates':{'baseline':'SEPARATE_USER_AUTHORIZATION_AND_INDEPENDENT_QA_REQUIRED',
                     'suffix':'SEPARATELY_FROZEN_C1_FORK_PLAN_AND_SEPARATE_USER_AUTHORIZATION_REQUIRED',
                     'c1_stop':'STOP_AFTER_CONCRETE_PLAN_NO_SUFFIX_SENDS'},
            'model_declaration':{'requested_model':executions[0]['config']['model'],
                                 'served_model':'UNKNOWN_NOT_RUN', 'provider_seed':'UNKNOWN_NOT_RUN',
                                 'service_tie_rule':'UNKNOWN', 'real_service':'NOT_RUN', 'real_LP':'NOT_RUN'}}
    plan['plan_digest'] = digest(plan)
    save('training_plan.json', plan)
    return plan


def validate_plan(plan, *, root):
    """Saved bytes, schema and identity only. No sample/rebuild/run/LP calls."""
    from . import packaging_jev_v13 as v13
    from .packaging_runtime import runtime_task
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).with_name('schemas')/'jm_training_plan_v1.schema.json').read_text())
    require(Draft202012Validator(schema).is_valid(plan), 'PLAN_SCHEMA')
    require(plan['plan_digest'] == digest({k:v for k,v in plan.items() if k != 'plan_digest'}), 'PLAN_DIGEST')
    require(plan['runtime_identity'] == v13.identity(), 'PLAN_RUNTIME_DRIFT')
    require(plan['selection_rule'] == RULE, 'PLAN_SELECTION_RULE')
    require(plan['smaller_scope_reason'] == ('NONE' if plan['requested_count'] == 6 else
            'EXPLICIT_SMALLER_OFFLINE_SCOPE_NO_REFILL'), 'PLAN_SMALLER_SCOPE')
    require(len(plan['input_refs']) == len(REQUIRED_INPUTS) and
            {r['path'] for r in plan['input_refs']} == set(REQUIRED_INPUTS), 'PLAN_REQUIRED_INPUTS')
    for r in plan['input_refs'] + plan['qa_refs']:
        if r['path'].endswith('.md'):
            require(ref(r['path'], root=root) == r, 'PLAN_DOCUMENT_BYTES_CHANGED')
        else:
            load(r, root=root)
    require({r['path'] for r in plan['qa_refs']} | set(plan['missing_qa']) == set(QA_REQUIRED), 'PLAN_QA_INVENTORY')
    require(not ({r['path'] for r in plan['qa_refs']} & set(plan['missing_qa'])), 'PLAN_QA_OVERLAP')
    audit, grouping = _sources(load(plan['catalog_ref'], root=root), root=root)
    require(load(plan['audit_ref'], root=root) == {'rows':audit, 'grouping':grouping}, 'PLAN_SOURCE_AUDIT')
    expected = select_tasks(audit, plan['requested_count'])
    _data_admission(expected, plan['input_refs'], root=root)
    rows = plan['assignments']
    require(len(rows) == len(expected) and len({r['task_id'] for r in rows}) == len(rows), 'PLAN_DUPLICATE_TASK')
    require(len({r['slot_id'] for r in rows}) == len(rows), 'PLAN_DUPLICATE_SLOT')
    schedule = load(plan['schedule_ref'], root=root); v13.validate_schedule(schedule)
    executions = []
    for i, (row, original) in enumerate(zip(rows, expected)):
        require(all(row[k] == v for k,v in original.items()), 'PLAN_SOURCE_ASSIGNMENT_CHANGED')
        require(row['ordinal'] == i+1 and row['wave'] == 1+i//3 and
                row['slot_id'] == f'W{1+i//3}S{1+i%3}' and row['role'] == 'training', 'PLAN_SLOT_ORDER')
        ex = load(row['execution_ref'], root=root); v13.validate_execution(ex)
        task = runtime_task(load(row['task_ref'], root=root))
        require(ex['task'] == task and ex['kind'] == 'BASELINE' and ex['repeat_slot'] == 'r0' and
                ex['config']['jm_mode'] == 'REMOTE_INJECTED' and ex['job_id'] == row['job_id'] and
                ex['max_sends'] == row['full_items'], 'PLAN_EXECUTION_BINDING')
        require(row['runtime_task_digest'] == digest(task) and row['arrival_digest'] == digest(task['items']),
                'PLAN_ARRIVAL_DRIFT')
        executions.append(ex)
    require(schedule['executions'] == executions, 'PLAN_SCHEDULE_BINDING')
    require(plan['budget'] == budgets(rows), 'PLAN_BUDGET')
    require(plan['sampling'] == {'protocol':sampling.JM_SAMPLING_VERSION, 'policy_sha256':sampling.POLICY_SHA256,
            'epsilon':DEFER, 'points':DEFER, 'exact_actions':DEFER,
            'repeat_rule':'packaging_jev_training_template.repeat_priority',
            'repeat_rule_digest':digest(Path(template.__file__).read_text()),
            'input_boundary':'B1_CLOSED_PUBLIC_PROJECTION_ONLY_NO_TERMINAL_OR_MONITOR'}, 'PLAN_SAMPLING_DRIFT')
    require(any(r['sha256'] == sampling.POLICY_SHA256 for r in plan['input_refs']), 'PLAN_MISSING_SAMPLING_POLICY')
    require(plan['model_declaration']['requested_model'] == executions[0]['config']['model'], 'PLAN_MODEL_CHANGED')
    return {'version':'jev_jm_training_plan_check_v1', 'saved_facts':'PASS',
            'formal_freeze':'DEFER_MISSING_QA' if plan['missing_qa'] else 'DEFER_INDEPENDENT_PLAN_REVIEW',
            'missing_qa':plan['missing_qa'], 'execution_authorized':False,
            'baseline_send_upper':plan['budget']['baseline_send_upper'],
            'suffix_send_upper':plan['budget']['suffix_send_upper'],
            'dispatches':0, 'C1':'NOT_RUN', 'C2':'NOT_RUN'}


def require_send_authorization(plan, *, root, stage, permit=None):
    """Explicit refusal boundary. This preparation protocol issues no permissions."""
    validate_plan(plan, root=root)
    require(stage in ('BASELINE', 'SUFFIX'), 'PLAN_UNKNOWN_SEND_GATE')
    require(False, 'PLAN_SEND_NOT_AUTHORIZED_REQUIRES_SEPARATE_EXECUTION_ADMISSION')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['validate', 'baseline-gate', 'suffix-gate'])
    parser.add_argument('input'); parser.add_argument('--root', default='.')
    args = parser.parse_args()
    plan = sampling.strict_load(Path(args.input).read_bytes())
    if args.mode == 'validate':
        print(json.dumps(validate_plan(plan, root=args.root), ensure_ascii=False, indent=2))
    else:
        require_send_authorization(plan, root=args.root, stage='BASELINE' if args.mode == 'baseline-gate' else 'SUFFIX')


if __name__ == '__main__':
    main()

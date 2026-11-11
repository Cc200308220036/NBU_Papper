"""Static JM0-B contract audit, standard library only.
Reads this explicit contract bundle, inventoried inputs and local git blobs.
No business imports, networking, credentials, order/branch/candidate/solver calls.
Default stdout only. --output writes a NEW validation receipt (never overwrites).
"""
from pathlib import Path
import ast
import collections
import hashlib
import itertools
import json
import re
import subprocess
import sys
from urllib.parse import unquote

ROOT = Path.cwd().resolve()
OUT = Path(__file__).resolve().parent
if not (ROOT / 'AGENTS.md').is_file():
    raise SystemExit('run from repository root')
checks = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def load(p):
    return json.loads(p.read_text())


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def safe(name):
    p = (ROOT / name).resolve()
    check('safe inventory path: ' + name,
          p.is_relative_to(ROOT) and not any(x in name.lower() for x in
          ['.aws/', '.env', 'credentials', 'secrets.json', 'api_key']))
    return p


def pointer(obj, point):
    if not point:
        return obj
    if not point.startswith('/'):
        raise AssertionError(point)
    for bit in point[1:].split('/'):
        bit = bit.replace('~1', '/').replace('~0', '~')
        obj = obj[int(bit)] if isinstance(obj, list) else obj[bit]
    return obj


names = ['research_contract', 'data_admission_plan', 'exposure_register', 'method_design',
         'admission_policy', 'analysis_contract', 'sampling_policy', 'parameter_register',
         'budget_and_stop_contract', 'risk_and_assumptions']
contracts = {}
shapes = load(OUT / 'contract_shapes.json')
for name in names:
    doc = load(OUT / (name + '.json'))
    check(name + ': closed top-level fields', set(doc) == set(shapes['top_level_required']))
    check(name + ': closed payload fields', set(doc['payload']) == set(shapes['payload_required'][name]))
    check(name + ': version/task/plan/type',
          doc['version'] == 'jm0_b_' + name + '_v1' and doc['task'] == 'JM0-B'
          and doc['plan_version'] == 'JM-plan-v2'
          and doc['contract_type'] == 'STATIC_DESIGN_NOT_PRODUCTION_SCHEMA_OR_IMPLEMENTED_RUNTIME')
    check(name + ': execution denied', doc['execution_authorized'] is False)
    contracts[name] = doc['payload']

# Explicit references only; literature URLs are retained as offline metadata, never opened.
refs = []


def walk(x):
    if isinstance(x, dict):
        if 'path' in x and 'json_pointer' in x:
            refs.append(x)
        for value in x.values():
            walk(value)
    elif isinstance(x, list):
        for value in x:
            walk(value)


for name in names:
    walk(load(OUT / (name + '.json')))
for item in refs:
    p = safe(item['path'])
    check('reference exists: ' + item['path'], p.is_file())
    pointer(load(p), item['json_pointer'])

inputs = load(OUT / 'input_evidence_index.json')
missing = []
for e in inputs['files']:
    p = safe(e['path'])
    if not e['exists_at_design']:
        missing.append(e['path'])
        # A later-arriving missing parent requires a NEW review, no retroactive signature.
        check('recorded unavailable parent remains explicitly UNAVAILABLE: ' + e['path'],
              e['sha256_at_design'] == 'UNAVAILABLE')
        continue
    if 'verification_source' in e:
        v = e['verification_source']
        raw = subprocess.check_output(['git', 'show', v['commit'] + ':' + v['path']], cwd=ROOT)
        check('entry git blob: ' + e['path'], hashlib.sha256(raw).hexdigest() == e['sha256_at_design'])
    else:
        check('protected input unchanged: ' + e['path'], p.is_file() and sha(p) == e['sha256_at_design'])
    if p.suffix == '.json':
        obj = load(p)
        for point in e['pointers']:
            pointer(obj, point)

for e in contracts['research_contract']['actual_interfaces']:
    p = safe(e['path'])
    tree = ast.parse(p.read_text())
    check('actual source symbol: ' + e['symbol'], any(
        isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name == e['symbol'] and n.lineno == e['line']
        for n in ast.walk(tree)))
    check('source digest: ' + e['symbol'], sha(p) == e['sha256'])

rule = contracts['analysis_contract']['comparison_rule']
tree = ast.parse((ROOT / 'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_reanalysis.py').read_text())
rule_node = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'RULE' for t in n.targets))
for key in ['levels', 'tolerances']:
    value = next(v for k, v in zip(rule_node.keys, rule_node.values) if isinstance(k, ast.Constant) and k.value == key)
    check('v2 exact registered ' + key, ast.literal_eval(value) == rule[key])
check('v2 version', rule['version'] == 'jev_branch_comparison_rule_v2')

D = contracts['data_admission_plan']
check('all six roles pairwise isolated', {frozenset(x) for x in D['forbidden_overlap_pairs']}
      == {frozenset(x) for x in itertools.combinations(D['roles'], 2)})
check('no invented formal assignments', D['existing_materials']['formal_assignments'] == []
      and D['existing_materials']['formal_partition_status'] == 'DEFER')
E = contracts['exposure_register']
original = load(ROOT / 'semantic_pallet_planner/outputs/JEV_JM0_A_20261110_01/source_task_register.json')
check('all 27 inherited rows linked', len(E['rows']) == 27
      and [r['existing_id'] for r in E['rows']] == [r['id'] for r in original['source_rows']])
check('all inherited rows diagnostic, not new unseen', all(
    x['current_role'] == 'historical_diagnostic_only' and x['strict_unseen_eligible'] is False
    for x in E['rows']))

# Static role-assignment metadata validation, never a runtime memory/source admission route.
# Probe rows stay in memory, are explicitly artificial metadata, and are never experiment tasks.
keys = ['entity_identity_sha256', 'source_group_ids', 'near_duplicate_component_ids',
        'material_family_ids', 'prototype_ids', 'seed_family_ids']


def assignment_errors(rows):
    if not rows:
        return {'DEFER_NO_FORMAL_ASSIGNMENTS'}
    errors = set()
    for row in rows:
        if row.get('role') not in D['roles']:
            errors.add('UNKNOWN_ROLE')
        if any(k not in row or row[k] == 'UNKNOWN' for k in keys):
            errors.add('UNKNOWN_GROUP_RELATION')
    if errors:
        return errors
    for left, right in itertools.combinations(rows, 2):
        if frozenset([left['role'], right['role']]) not in {frozenset(x) for x in D['forbidden_overlap_pairs']}:
            continue
        for key in keys:
            a = left[key] if isinstance(left[key], list) else [left[key]]
            b = right[key] if isinstance(right[key], list) else [right[key]]
            if set(a) & set(b):
                errors.add('FORBIDDEN_OVERLAP:' + key)
        if left['entity_identity_sha256'] in right.get('parent_entity_ids', []) or right['entity_identity_sha256'] in left.get('parent_entity_ids', []):
            errors.add('FORBIDDEN_ANCESTOR_OVERLAP')
    return errors


check('empty assignments correctly DEFER', assignment_errors(D['existing_materials']['formal_assignments'])
      == {'DEFER_NO_FORMAL_ASSIGNMENTS'})
for token in keys:
    left = {k: ['left_' + k] for k in keys}
    right = {k: ['right_' + k] for k in keys}
    left['entity_identity_sha256'] = 'left_metadata_probe'
    right['entity_identity_sha256'] = 'right_metadata_probe'
    left['role'], right['role'] = 'training', 'evaluation'
    right[token] = left[token]
    check('static forbidden-overlap rejection: ' + token,
          'FORBIDDEN_OVERLAP:' + token in assignment_errors([left, right]))
check('static unknown-group rejection', assignment_errors([{'role': 'evaluation'}]) == {'UNKNOWN_GROUP_RELATION'})

check('documented unknown relation quarantined', 'quarantine' in D['grouping']['unknown_relation'])

M = contracts['method_design']
check('complete seven methods', [x['id'] for x in M['methods']] == ['N', 'T0', 'T1', 'E0', 'E1', 'U1', 'G1'])
check('complete five local conditions', [x['id'] for x in M['local_conditions']] == ['L-N', 'L-T', 'L-E', 'L-A', 'L-G'])
check('no runtime/embedding/online extra calls', all(
    M['third_party'][k] == 'NOT_ADOPTED' for k in ['runtime_integration', 'embedding', 'online_LLM_rerank_or_rewrite']))
check('unseen efficacy not preclaimed', M['pilot']['complete_experience_matrix_ready'] is False)
A = contracts['admission_policy']
check('three identities separate', set(A['lifecycle']) == {'FACT_CASE', 'CANDIDATE_MEMORY', 'EXECUTION_ELIGIBLE'})
check('cross-start and group floors', A['minimum_coverage']['training_distinct_starts_per_family'] >= 2
      and A['minimum_coverage']['training_source_groups_per_family'] >= 2
      and A['minimum_coverage']['development_non_near_duplicate_states_per_family'] >= 2
      and A['minimum_coverage']['development_source_groups_per_family'] >= 2)
check('independent review not fabricated', A['review']['current_roster'] == 'NOT_AVAILABLE_NO_APPROVAL_CLAIMED')
P = contracts['parameter_register']
check('all parameters have procedure/deadline/input/owner/failure', all(
    'freeze_by' in x and 'owner' in x and x['inputs'] and x['on_missing'] and
    ('procedure' in x or 'procedure_ref' in x) for x in P['parameters']))
S = contracts['sampling_policy']
check('no low-probability fallback', S['branches_and_repeats']['all_suffix_memories'] == []
      and S['near_top']['current_numeric_value'] == 'NOT_MATERIALIZED'
      and 'NO_ELIGIBLE_POINT' in S['reject_codes'])
check('parameter materialization not executed', all(
    x['status'] == 'PROCEDURE_FROZEN_VALUE_NOT_MATERIALIZED' for x in P['parameters']))

B = contracts['budget_and_stop_contract']
ids = [x['id'] for x in B['allocations']]
check('unique nonoverlapping allocations', len(ids) == len(set(ids)) == 9)
a = B['arithmetic']
check('training points cap', a['training_points']['orders'] * a['training_points']['points_each'] == 12)
check('initial+repeat within total 48', a['training_initial']['points'] * a['training_initial']['branches_each']
      + a['training_repeats']['points'] * a['training_repeats']['branches_each'] * a['training_repeats']['extra_repeat_each'] == a['training_total_suffixes'] == 48)
check('local 20 choices /24 suffixes', a['local_choices']['states'] * a['local_choices']['conditions_each'] == 20
      and a['local_suffixes']['states'] * a['local_suffixes']['actions_each'] * a['local_suffixes']['repeat_each'] == 24)
check('pilot42 not28+42', (a['pilot']['orders'] + a['pilot']['extra_repeat_orders']) * a['pilot']['methods'] == a['pilot']['total'] == 42)
check('whole/suffix arithmetic convention only', 10 - 3 - 1 == 6 and max(0, 1 - 0 - 1) == 0)
check('all actual operations zero', all(type(x) is int and x == 0 for x in B['current_authorized'].values()))
check('no implicit retry /unknown stop', B['accounting']['retries'] == 0 and 'UNKNOWN_SEND' in B['stop']['batch_technical'])
check('no invented evaluation budget', B['allocations'][-1]['max_units'] == 'NOT_MATERIALIZED_NO_SEND')

# Existing ignore policy must admit the new bundle; no git add, commit or push.
probe = subprocess.run(['git', 'check-ignore', '--no-index', str((OUT / 'research_contract.json').relative_to(ROOT))],
                       cwd=ROOT, capture_output=True, text=True)
check('JM Git admission already enabled', probe.returncode == 1)
acceptance = load(OUT / 'acceptance_receipt.json')
for cid, item in acceptance['criteria'].items():
    check('design acceptance scoped: ' + cid, item['status'] == 'PASS' and bool(item['scope']))
    for reference in item['evidence']:
        filename, point = reference.split('#', 1)
        pointer(load(OUT / filename), point)
handoff = load(OUT / 'handoff.json')
for item in handoff['contracts']:
    check('handoff contract digest: ' + item['path'], sha(safe(item['path'])) == item['sha256'])
check('handoff input identity index', sha(safe(handoff['parent_identity_index']['path'])) == handoff['parent_identity_index']['sha256'])
check('next stage not silently admitted', handoff['stop'] is True and handoff['next_stage_admission']['JM1-A1'] == 'DEFER')
report = ROOT / 'docs/03_阶段产出分析/Jev/Jev_JM0-B研究与准入合同设计_20261111_01.md'
for p in [report, ROOT / 'docs/03_阶段产出分析/Jev/README.md']:
    text = p.read_text()
    if p.name == 'README.md':
        text = '\n'.join(x for x in text.splitlines() if 'JM0-B' in x and '20261111_01' in x)
    for target in re.findall(r'\]\(([^)]+)\)', text):
        if re.match(r'https?://', target):
            continue
        target = unquote(target.split('#')[0])
        check('new document local link: ' + target, (p.parent / target).resolve().is_file())
if (OUT / 'delivery_manifest.json').is_file():
    manifest = load(OUT / 'delivery_manifest.json')
    for e in manifest['files']:
        p = safe(e['path'])
        check('delivery hash: ' + e['path'], sha(p) == e['sha256'])
    listed = {e['path'] for e in manifest['files']}
    check('complete delivery inventory', all(str(p.relative_to(ROOT)) in listed for p in OUT.iterdir()
          if p.is_file() and p.name != 'delivery_manifest.json'))
result = {'version': 'jm0_b_static_checks_v1', 'status': 'PASS_STATIC_CONTRACT_CHECKS',
          'checks': checks, 'check_count': len(checks), 'input_gaps': missing,
          'research_readiness': 'DEFER_NOT_RUNTIME_VALIDATION',
          'operations': B['current_authorized'],
          'not_run': ['business-module imports', 'models', 'candidate reconstruction', 'orders',
                      'forks', 'solver', 'old verify_static.py', 'network/literature primary verification'],
          'scope_note': 'contract shapes/references/identities, inherited-source roles, declarative isolation relation, set-algebra negative probes and budget arithmetic only; no production admission or sampling implementation'}
if '--output' in sys.argv:
    name = sys.argv[sys.argv.index('--output') + 1]
    dest = (OUT / name).resolve()
    assert dest.parent == OUT and not dest.exists(), 'output must stay new inside bundle'
    with dest.open('x') as f:
        f.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'status': result['status'], 'checks': len(checks), 'missing_parent_files': len(missing),
                  'research_readiness': result['research_readiness']}, ensure_ascii=False))

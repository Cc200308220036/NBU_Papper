"""Versioned, saved-evidence-only JN2 post hoc analysis. No execution route.

v1 remains owned by packaging_comparisons; this module never changes its rule.
All evaluation differences are alternative minus reference. Evidence failures
raise (provenance/recomputation) or produce invalid (unavailable metrics).
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import math
from pathlib import Path
import shutil

from .contracts import digest, validate_schema, JevSelectError
from .ledger import read, write
from .experiment import source_manifest, file_manifest
from . import packaging_comparisons as v1
from . import packaging_counterfactual as fork

REPO = Path(__file__).resolve().parents[4]
TYPE = 'POST_HOC_USER_REVISED_OBJECTIVE'
RULE_VERSION = 'jev_branch_comparison_rule_v2'
RULE = {
    'version': RULE_VERSION, 'delta_direction': 'alternative_minus_reference',
    'levels': ['STABLE_COMPLETION', 'LOADED_VOLUME', 'COUNT_MASS', 'COMPACTNESS'],
    'hierarchy': 'first unequal stable completion or volume decides; otherwise count/mass Pareto; only equal loading permits height/envelope Pareto',
    'tolerances': {'ratio': 1e-9, 'height_mm': 1e-6, 'mass_kg': 1e-9, 'items': 0},
    'valid_categories': list(v1.VALID_CATEGORIES),
    'compactness': 'height lower, envelope higher; both empty NOT_APPLICABLE; missing nonempty metrics invalidate compactness layer and reject experience',
    'secondary_regressions': ['placed_items', 'placed_mass_kg', 'actual_height_mm', 'envelope_utilization'],
    'excluded_diagnostics': ['fixed_container_utilization', 'remaining_capacity_sum', 'cost', 'latency_s'],
    'neutral': 'registered metric equivalence only; not action, box-set or layout identity',
}
ADMISSION = {
    'version': 'jev_experience_input_review_v2',
    'candidate': 'valid improved at STABLE_COMPLETION/LOADED_VOLUME/COUNT_MASS only',
    'required_checks': ['authorized_training', 'parent_verified', 'same_prefix_pool_task_follow',
                        'no_technical_or_range_confound', 'metrics_costs_complete',
                        'no_label_or_order_shortcut', 'facts_locatable'],
    'reviewer': 'deterministic evidence checks; no human or LLM review claimed',
    'scope': 'conditional source-specific construction input only; no finished memory, retrieval, injection or effectiveness proof',
}
LIMITS = [TYPE, 'two previously exposed training sources; no unseen-source validation',
          'fixed local_geometry_test_double continuation only; finite registered interventions',
          'all final stops EMPTY_POOL in this collection; no stable-complete gain demonstrated',
          'synthetic packaging load parameters; feasibility UNKNOWN; static prediction only',
          'no universal cross-box/rank rule; no global optimum or causal generalization',
          'JN3 construction, LLM extraction, retrieval and injection NOT_RUN; future experiments must preregister v2']
ZERO = {'new_suffixes': 0, 'model_api_calls': 0, 'credential_reads': 0}


def require(ok, reason):
    if not ok:
        raise JevSelectError('reanalysis_' + reason)


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def sign(value, tol):
    return 0 if abs(value) <= tol else (1 if value > 0 else -1)


def pareto(signs):
    nonzero = [s for s in signs if s]
    return ('neutral' if not nonzero else 'trade_off' if min(nonzero) < 0 < max(nonzero)
            else 'improved' if max(nonzero) > 0 else 'degraded')


def evaluate(reference, alternative, *, rule_version):
    """Explicit dispatch. v2 accepts normalized saved metric views, v1 receipts."""
    if rule_version == v1.LABEL_RULE['version']:
        return v1.classify(reference, alternative)
    require(rule_version == RULE_VERSION, 'unknown_rule_version')
    a, b = reference, alternative
    reasons = []
    for key in ('task_digest', 'data_identity', 'denominators'):
        if key not in a or key not in b or a[key] != b[key] or (key != 'denominators' and (not isinstance(a[key], str) or not a[key])):
            reasons.append('missing_or_unequal_' + key)
    for side, x in [('reference', a), ('alternative', b)]:
        if x.get('category') not in RULE['valid_categories']:
            reasons.append(side + '_invalid_category')
        if type(x.get('stable_complete')) is not bool:
            reasons.append(side + '_unverifiable_stable_complete')
        for key in ('placed_volume_ratio', 'placed_mass_kg', 'placed_items'):
            if not numeric(x.get(key)) or x[key] < 0:
                reasons.append(side + '_missing_nonfinite_or_negative_' + key)
        if type(x.get('placed_items')) is not int:
            reasons.append(side + '_noninteger_items')
        den = x.get('denominators', {})
        if not all(numeric(den.get(k)) and den[k] > 0 for k in ('items', 'mass_kg', 'volume_mm3')) or type(den.get('items')) is not int:
            reasons.append(side + '_invalid_denominators')
        elif numeric(x.get('placed_items')) and x['placed_items'] > den['items']:
            reasons.append(side + '_items_exceed_plan')
        if x.get('placed_items') == 0 and (x.get('placed_mass_kg') != 0 or x.get('placed_volume_ratio') != 0):
            reasons.append(side + '_inconsistent_empty')
        for key in ('actual_height_mm', 'envelope_utilization'):
            if type(x.get(key)) in (int, float) and not math.isfinite(x[key]):
                reasons.append(side + '_nonfinite_' + key)
        if numeric(x.get('placed_volume_ratio')) and x['placed_volume_ratio'] > 1 + 1e-9:
            reasons.append(side + '_volume_exceeds_plan')
        if numeric(x.get('placed_mass_kg')) and numeric(den.get('mass_kg')) and x['placed_mass_kg'] > den['mass_kg'] + 1e-9:
            reasons.append(side + '_mass_exceeds_plan')
        if x.get('stable_complete') is True and (x.get('category') != 'COMPLETE' or x.get('placed_items') != den.get('items') or not numeric(x.get('placed_volume_ratio')) or abs(x['placed_volume_ratio'] - 1) > 1e-9 or not numeric(x.get('placed_mass_kg')) or not numeric(den.get('mass_kg')) or abs(x['placed_mass_kg'] - den['mass_kg']) > 1e-9):
            reasons.append(side + '_inconsistent_complete')
        if x.get('category') == 'COMPLETE' and x.get('stable_complete') is not True:
            reasons.append(side + '_inconsistent_complete_category')
    keys = ('placed_volume_ratio', 'placed_items', 'placed_mass_kg', 'actual_height_mm', 'envelope_utilization')
    delta = {k: b[k]-a[k] if numeric(a.get(k)) and numeric(b.get(k)) else 'NA' for k in keys}
    gaps = []
    for side, x in [('reference', a), ('alternative', b)]:
        if x.get('placed_items', 0) != 0:
            for key in ('actual_height_mm', 'envelope_utilization'):
                if not numeric(x.get(key)) or x[key] <= 0 or (key == 'envelope_utilization' and x[key] > 1+1e-9):
                    gaps.append(side + '_' + key)
    secondary = []
    for key, direction, tol in [('placed_items', -1, 0), ('placed_mass_kg', -1, 1e-9), ('actual_height_mm', 1, 1e-6), ('envelope_utilization', -1, 1e-9)]:
        applicable = numeric(delta[key]) and not (key in ('actual_height_mm', 'envelope_utilization') and (gaps or a.get('placed_items') == 0 or b.get('placed_items') == 0))
        secondary.append({'metric': key, 'delta': delta[key], 'status': 'APPLICABLE' if applicable else 'NOT_APPLICABLE_OR_UNAVAILABLE', 'regressed': sign(delta[key], tol)*direction > 0 if applicable else None})
    result = {'comparison_valid': not reasons, 'label_v2': 'invalid', 'invalid_reasons': reasons,
              'decisive_level': 'INVALID', 'benefit_type': 'NONE', 'delta': delta,
              'secondary_regressions': secondary, 'metric_gaps': gaps,
              'compactness_status': 'UNAVAILABLE' if gaps else 'NOT_APPLICABLE' if a.get('placed_items') == b.get('placed_items') == 0 else 'AVAILABLE'}
    if reasons:
        return result
    level = 'STABLE_COMPLETION'; s = int(b['stable_complete']) - int(a['stable_complete'])
    if not s:
        level = 'LOADED_VOLUME'; s = sign(delta['placed_volume_ratio'], 1e-9)
    if s:
        label = 'improved' if s > 0 else 'degraded'
    else:
        level = 'COUNT_MASS'
        label = pareto([sign(delta['placed_items'], 0), sign(delta['placed_mass_kg'], 1e-9)])
        if label == 'neutral':
            level = 'COMPACTNESS'
            if gaps:
                result.update(comparison_valid=False, invalid_reasons=['compactness_unverifiable'])
                label = 'invalid'
            elif a['placed_items'] == b['placed_items'] == 0:
                label = 'neutral'
            else:
                label = pareto([-sign(delta['actual_height_mm'], 1e-6), sign(delta['envelope_utilization'], 1e-9)])
    result.update(label_v2=label, decisive_level=level,
                  benefit_type=('COMPACTNESS' if level == 'COMPACTNESS' else 'LOADING') if label == 'improved' else 'NONE')
    return result


def task_denominators(task):
    items = task['items']
    return {'items': len(items), 'mass_kg': sum(x['mass_kg'] for x in items),
            'volume_mm3': sum(math.prod(x['dimensions_mm'].values()) for x in items)}


def metric_view(receipt, task, data_identity):
    m = receipt['metrics']; loading = m['loading']
    return {'task_digest': digest(task), 'data_identity': data_identity,
            'denominators': task_denominators(task), 'category': receipt['status']['category'],
            'stable_complete': m['stable_complete'], 'placed_items': loading['placed_items'],
            'placed_mass_kg': loading['placed_mass_kg'], 'placed_volume_ratio': loading['placed_volume_ratio'],
            'actual_height_mm': m['actual_height_mm'], 'envelope_utilization': m['envelope_utilization']}


def verify_branch(location, jid):
    """Recompute receipt through the existing pure saved-metric implementation.

    No fork validate_plan/preflight, prepare/run, physics or algorithm dispatch.
    Frozen verifier additionally checks stage transitions/physical saved state.
    """
    plan = read(location/'branch_plan.json'); task = read(location/'task.private.json')
    r = read(location/'branches'/jid/'branch_receipt.json'); fork.check_seal(r)
    require(r == fork.branch_receipt(location, jid, plan, task), 'receipt_recomputation_mismatch')
    cp = read(location/'branches'/jid/'checkpoint.json')
    binding = read(location/'branches'/jid/'binding.json'); fork.check_seal(binding); fork.check_seal(plan)
    require(r['plan_digest'] == digest(plan) and r['binding_digest'] == digest(binding) and binding['config_digest'] == cp['config_digest'] == digest(plan['config']) and cp['task_digest'] == digest(task), 'branch_identity_mismatch')
    placed = cp['state']['placed_items']; ids = [x['item_id'] for x in placed]
    require(len(ids) == len(set(ids)), 'duplicate_committed_item')
    by_id = {x['item_id']: x for x in task['items']}
    require(all(x['item_id'] in by_id and x['mass_kg'] == by_id[x['item_id']]['mass_kg'] and x['dimensions_mm'] == by_id[x['item_id']]['dimensions_mm'] for x in placed), 'committed_item_task_mismatch')
    total = task_denominators(task); m = r['metrics']; l = m['loading']; final = m['branch_metrics']['final']
    volume = sum(math.prod(x['dimensions_mm'].values()) for x in placed)
    mass = sum(x['mass_kg'] for x in placed)
    require(final == {'items': len(placed), 'mass_kg': mass, 'volume_mm3': volume}, 'committed_totals_mismatch')
    require(l['planned_items'] == total['items'] and abs(l['planned_mass_kg']-total['mass_kg']) <= 1e-9, 'denominator_mismatch')
    require(l['placed_items'] == len(placed) and abs(l['placed_mass_kg']-mass) <= 1e-9 and abs(l['placed_volume_ratio'] - volume/total['volume_mm3']) <= 1e-9, 'loading_mismatch')
    require(abs(l['placed_item_ratio']-len(placed)/total['items']) <= 1e-9 and abs(l['placed_mass_ratio']-mass/total['mass_kg']) <= 1e-9, 'ratio_mismatch')
    return r, task, sorted(ids)


def inventory(parent):
    p = read(parent/'comparison_plan.json'); result = []
    for entry in p['entries']:
        location = REPO/entry['location']
        for jid in [f'B{i:02d}' for i in range(1, len(entry['first_actions']))]:
            cid = entry['group_id']+'_'+jid
            old = parent/'comparisons'/f'{cid}.json'
            result.append({'comparison_id': cid, 'v1_path': v1.rel(old), 'v1_sha256': fork.sha(old),
                           'reference_path': v1.rel(location/'branches/B00/branch_receipt.json'),
                           'alternative_path': v1.rel(location/'branches'/jid/'branch_receipt.json')})
    require(sorted(x['comparison_id'] for x in result) == sorted(p.stem for p in (parent/'comparisons').glob('*.json')), 'comparison_inventory_mismatch')
    return result


def freeze(parent, output, scheme):
    parent, root, scheme = Path(parent).resolve(), Path(output).resolve(), Path(scheme).resolve()
    require(not (root/'analysis_plan.json').exists(), 'plan_already_frozen')
    checked = v1.checked_manifest(parent)
    verification = read(root/'parent_verification.json')
    require(verification['status'] == 'PASS' and verification['parent'] == checked, 'parent_not_verified')
    files = source_manifest(); p = read(parent/'comparison_plan.json')
    plan = fork.seal({'version': 'jev_posthoc_analysis_plan_v2', 'analysis_type': TYPE,
                     'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
                     'scheme': {'path': v1.rel(scheme), 'sha256': fork.sha(scheme)},
                     'parent': checked, 'parent_verification_digest': digest(verification), 'inventory': inventory(parent), 'rule': RULE, 'rule_digest': digest(RULE),
                     'admission': ADMISSION, 'analysis_source_digest': digest(files), 'analysis_source_manifest': files,
                     'execution_source_digest': digest(p['execution_source_manifest']),
                     'historical_suffixes': read(parent/'budget_ledger.json')['registered_total'], 'operations': ZERO,
                     'limitations': LIMITS})
    validate_schema('packaging_reanalysis_plan_v2', plan)
    for n in files:
        target = root/'analysis_code_snapshot'/n; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).resolve().parents[1]/n, target)
    write(root/'source_manifest.json', files); write(root/'analysis_plan.json', plan)
    write(root/'plan_anchor.json', {'plan_digest': digest(plan)})
    return plan


def validate_plan(root):
    p = read(root/'analysis_plan.json'); fork.check_seal(p); validate_schema('packaging_reanalysis_plan_v2', p)
    require(digest(p) == read(root/'plan_anchor.json')['plan_digest'], 'plan_anchor_changed')
    require(p['rule'] == RULE and p['rule_digest'] == digest(RULE) and p['admission'] == ADMISSION, 'rule_changed')
    require(p['operations'] == ZERO and p['analysis_type'] == TYPE, 'scope_changed')
    require(source_manifest() == p['analysis_source_manifest'] == read(root/'source_manifest.json') and digest(source_manifest()) == p['analysis_source_digest'], 'analysis_source_changed')
    require(all(fork.sha(root/'analysis_code_snapshot'/n) == h for n,h in p['analysis_source_manifest'].items()), 'analysis_archive_changed')
    require(fork.sha(REPO/p['scheme']['path']) == p['scheme']['sha256'], 'scheme_changed')
    parent = REPO/p['parent']['path']
    require(v1.checked_manifest(parent) == p['parent'] and inventory(parent) == p['inventory'], 'parent_changed')
    require(digest(read(parent/'comparison_plan.json')['execution_source_manifest']) == p['execution_source_digest'], 'execution_identity_changed')
    verification = read(root/'parent_verification.json')
    require(verification['status'] == 'PASS' and verification['parent'] == p['parent'] and digest(verification) == p['parent_verification_digest'], 'parent_unverified')
    return p


def observable_conditions(state, reference, alternative):
    """Identifier-free facts of the saved public prefix, never future items."""
    item_keys = ('dimensions_mm', 'mass_kg', 'stackable', 'top_load_limit_kg_synthetic')
    def item_facts(item):
        return {k:item[k] for k in item_keys}
    by_id = {x['item']['item_id']:x['item'] for x in state['pending_items']}
    def action(first):
        candidate = first['candidate']; item = by_id[candidate['pick_item_id']]
        return {'item_attributes':item_facts(item), 'pose':candidate['pose'], 'oriented_size_mm':candidate['oriented_size_mm']}
    return {'container':{k:v for k,v in state['container'].items() if k != 'container_id'},
            'buffer_capacity':state['buffer_capacity'],
            'placed':[{**item_facts(x),'pose':x['pose'],'oriented_size_mm':x['oriented_size_mm'],
                       'supported_load_kg':x['supported_load_kg']} for x in state['placed_items']],
            'buffer':[item_facts(x['item']) for x in state['pending_items']],
            'reference_action':action(reference), 'alternative_action':action(alternative)}


def derive_record(root, plan, item):
    parent = REPO/plan['parent']['path']; old = read(REPO/item['v1_path']); fork.check_seal(old)
    pp = read(parent/'comparison_plan.json'); entry = next(e for e in pp['entries'] if e['group_id']+'_'+old['alternative_result']['job_id'] == item['comparison_id'])
    location = REPO/entry['location']
    ref, task, refset = verify_branch(location, 'B00')
    alt, alttask, altset = verify_branch(location, old['alternative_result']['job_id'])
    require(task == alttask, 'task_mismatch')
    payload = read(parent/'inputs'/f"{entry['group_id']}.json")['value']; snapshot = payload['snapshot']
    regenerated = v1.comparison_record(entry, snapshot, ref, alt, item['reference_path'], item['alternative_path'], plan['execution_source_digest'])
    require(regenerated == old, 'v1_record_or_delta_changed')
    require(task == payload['task'] and task['partition'] == 'train' and task['task_id'] == entry['task_id'] and ref['plan_digest'] == alt['plan_digest'] == entry['child_plan_digest'], 'training_plan_binding_mismatch')
    require(digest(snapshot) == entry['fork_digest'] and digest(payload['config']) == entry['config_digest'], 'snapshot_configuration_mismatch')
    a, b = metric_view(ref, task, pp['jn1_parent']['data_identity']), metric_view(alt, task, pp['jn1_parent']['data_identity'])
    result = evaluate(a, b, rule_version=RULE_VERSION)
    require(all(result['delta'][k] == old['delta'][k] for k in result['delta']), 'v2_delta_changed')
    row = fork.seal({'version': 'jev_comparison_record_v2', 'analysis_type': TYPE,
        'comparison_id': item['comparison_id'], 'source_group': old['source_group'],
        'provenance': {'v1': {**item, 'digest': digest(old)}, 'parent': plan['parent'],
                       'plan_digest': digest(plan), 'rule_version': RULE_VERSION, 'rule_digest': digest(RULE),
                       'analysis_source_digest': plan['analysis_source_digest'], 'execution_source_digest': plan['execution_source_digest'],
                       'receipts': old['receipts'], 'state_digest': old['state_digest'], 'candidate_pool_digest': old['candidate_pool_digest'],
                       'task_digest': digest(task), 'config_digest': entry['config_digest'], 'fork_digest': entry['fork_digest'],
                       'snapshot_path': v1.rel(parent/'inputs'/f"{entry['group_id']}.json")},
        'observable_conditions': observable_conditions(snapshot['state'], ref['first'], alt['first']),
        'label_v1': old['label'], 'raw_results': {'reference': ref['metrics'], 'alternative': alt['metrics']},
        'metric_views': {'reference': a, 'alternative': b}, 'original_delta': old['delta'], 'evaluation': result,
        'box_sets': {'reference': refset, 'alternative': altset, 'same': refset == altset,
                     'interpretation': 'same set' if refset == altset else 'only aggregate loading-equivalent layout description when loading equals'},
        'evidence_checks': {'authorized_training': True, 'parent_verified': True, 'same_prefix_pool_task_follow': True,
                            'no_technical_or_range_confound': result['comparison_valid'],
                            'metrics_costs_complete': not result['metric_gaps'], 'facts_locatable': True},
        'diagnostics': {'reference': {k:ref['metrics'][k] for k in ('area_load_ledger','latency_s','cost')},
                        'alternative': {k:alt['metrics'][k] for k in ('area_load_ledger','latency_s','cost')}},
        'interpretation': 'registered intervention with fixed local continuation; conditional saved facts only; neutral does not imply same layout'})
    validate_schema('packaging_comparison_record_v2', row)
    return row


def loading_candidate(row):
    r = row['evaluation']
    return r['comparison_valid'] and r['label_v2'] == 'improved' and r['decisive_level'] in ('STABLE_COMPLETION','LOADED_VOLUME','COUNT_MASS')


def review_candidate(row):
    r = row['evaluation']; a = row['metric_views']['reference']; b = row['metric_views']['alternative']
    # Construction input facts are identifier-free; IDs stay solely in provenance.
    facts = {'condition': 'saved public state and exact registered interventions; fixed deterministic local continuation',
             'reference': {k:a[k] for k in ('placed_items','placed_volume_ratio','placed_mass_kg','actual_height_mm','envelope_utilization')},
             'alternative': {k:b[k] for k in ('placed_items','placed_volume_ratio','placed_mass_kg','actual_height_mm','envelope_utilization')},
             'observable_conditions': row['observable_conditions'],
             'delta': r['delta'], 'secondary_regressions': r['secondary_regressions'],
             'scope': 'observed conditional result only; not rank advice or a universal intervention rule'}
    import re
    checks = dict(row['evidence_checks'])
    checks['no_label_or_order_shortcut'] = re.search(r'\bC\d+\b|NEW_\d+|J\d+_D\d+|SG_[0-9a-f]+', str(facts)) is None
    return {'comparison_id': row['comparison_id'], 'record_digest': digest(row), 'candidate': loading_candidate(row),
            'review_type': ADMISSION['reviewer'], 'checks': checks, 'facts': facts,
            'evidence': row['provenance'], 'costs': row['diagnostics'],
            'approved': loading_candidate(row) and all(checks.get(k) is True for k in ADMISSION['required_checks']),
            'rejection_reasons': [k for k in ADMISSION['required_checks'] if checks.get(k) is not True]}


def summaries(rows, plan):
    candidates = [r for r in rows if loading_candidate(r)]; reviews = [review_candidate(r) for r in candidates]
    approved = [r['comparison_id'] for r in reviews if r['approved']]
    summary = {'version': 'jev_comparison_summary_v2', 'comparisons': len(rows), 'valid': sum(r['evaluation']['comparison_valid'] for r in rows),
               'labels': {k:sum(r['evaluation']['label_v2'] == k for r in rows) for k in ('neutral','improved','degraded','trade_off','invalid')},
               'loading_candidates': [r['comparison_id'] for r in candidates],
               'compactness_improvements': [r['comparison_id'] for r in rows if r['evaluation']['benefit_type'] == 'COMPACTNESS'],
               'source_index': {s:[r['comparison_id'] for r in rows if r['source_group']==s] for s in sorted({r['source_group'] for r in rows})}}
    review = {'version': ADMISSION['version'], 'candidates_nonempty': bool(candidates), 'reviewed': len(reviews),
              'approved': approved, 'evidence_review_passed': bool(approved), 'records': reviews}
    ready = bool(approved)
    receipt = {'version': 'jev_comparison_dataset_receipt_v2', 'analysis_type': TYPE, 'rule_version': RULE_VERSION,
               'rule_digest': digest(RULE), 'parent': plan['parent'], 'analysis_plan_digest': digest(plan),
               'analysis_source_digest': plan['analysis_source_digest'], 'execution_source_digest': plan['execution_source_digest'],
               'parent_verification_digest': plan['parent_verification_digest'],
               'records': {r['comparison_id']:digest(r) for r in rows}, 'labels': summary['labels'],
               'engineering_complete': len(rows) == len(plan['inventory']) and bool(rows),
               'loading_candidates_nonempty': bool(candidates), 'evidence_review_passed': bool(approved),
               'approved_input_ids': approved, 'review_digest': digest(review),
               'experience_input_status': 'READY_IN_DECLARED_SCOPE' if ready else 'NOT_READY', 'JN3_A_input_ready': ready,
               'retrieval_verified': 'NOT_RUN', 'injection_verified': 'NOT_RUN', 'experience_benefit': 'NOT_ESTABLISHED',
               'historical_suffixes': plan['historical_suffixes'], 'operations': ZERO, 'limitations': LIMITS}
    transition = {'analysis_type': TYPE, 'entries': [{'comparison_id':r['comparison_id'],'old':r['label_v1'],'new':r['evaluation']['label_v2'],
                                                   'decisive_level':r['evaluation']['decisive_level'],'delta':r['original_delta'],
                                                   'secondary_regressions':r['evaluation']['secondary_regressions']} for r in rows]}
    return {'comparison_summary_v2.json':summary, 'experience_candidate_review.json':review,
            'comparison_dataset_receipt_v2.json':receipt, 'label_transition.json':transition}


def derive(root):
    root = Path(root).resolve(); plan = validate_plan(root)
    rows = [derive_record(root, plan, i) for i in plan['inventory']]
    return rows, summaries(rows, plan)


def analyze(root):
    root = Path(root).resolve(); require(not (root/'comparisons_v2').exists(), 'analysis_already_exists')
    require(not (root/'analysis_start_receipt.json').exists(), 'analysis_already_started')
    plan = validate_plan(root)
    write(root/'analysis_start_receipt.json', {'plan_digest':digest(plan), 'started_at_utc':datetime.now(timezone.utc).isoformat(), 'analysis_type':TYPE})
    rows, outputs = derive(root)
    for r in rows: write(root/'comparisons_v2'/f"{r['comparison_id']}.json", r)
    for n, v in outputs.items(): write(root/n, v)
    return outputs['comparison_summary_v2.json']


def validate(root):
    root = Path(root).resolve(); rows, outputs = derive(root)
    plan = read(root/'analysis_plan.json'); started = read(root/'analysis_start_receipt.json')
    require(started['plan_digest'] == digest(plan) and started['analysis_type'] == TYPE and started['started_at_utc'] >= plan['frozen_at_utc'], 'analysis_start_binding_changed')
    require(sorted(p.stem for p in (root/'comparisons_v2').glob('*.json')) == sorted(r['comparison_id'] for r in rows), 'record_set_changed')
    for row in rows: require(read(root/'comparisons_v2'/f"{row['comparison_id']}.json") == row, 'saved_record_changed')
    for n, v in outputs.items(): require(read(root/n) == v, 'saved_'+n+'_changed')
    if (root/'delivery_manifest.json').exists(): require(read(root/'delivery_manifest.json')['files_sha256'] == file_manifest(root), 'delivery_bytes_changed')
    return {'status': 'PASS', 'comparisons': len(rows), 'delta_unchanged': True, 'rule_version': RULE_VERSION,
            'verification': 'recompute all saved receipts, v1 records/deltas, v2 records/reviews/readiness; no execution routes'}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('command', choices=['freeze','analyze','validate']); parser.add_argument('--output',required=True)
    parser.add_argument('--parent'); parser.add_argument('--scheme'); args = parser.parse_args()
    if args.command == 'freeze': result = freeze(args.parent, args.output, args.scheme)
    elif args.command == 'analyze': result = analyze(args.output)
    else: result = validate(args.output)
    import json
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()

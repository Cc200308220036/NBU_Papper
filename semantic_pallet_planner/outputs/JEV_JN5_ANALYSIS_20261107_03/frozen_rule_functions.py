# Exact AST-selected pure functions from semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_reanalysis.py
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

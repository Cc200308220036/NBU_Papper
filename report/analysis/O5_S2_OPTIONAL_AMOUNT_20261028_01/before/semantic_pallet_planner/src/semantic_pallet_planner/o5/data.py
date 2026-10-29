"""Full-order, provenance-only source selection. No planner/model is called here."""
import collections
import json
import math
import re
from pathlib import Path
from .common import ROOT, VERSION, O5Error, atomic, canonical, digest, new_directory, read, sha
from .config import load

RAW_SHA = '6ecc91d92b9ce88de113ac66c45a450ac3eec303018f14cd73e4bd0eaf8eb3cc'
SOURCE_FIELD = re.compile(r'"(?:source_order_key|source_order_id|source_order_keys|excluded_source_values)"\s*:\s*("[^"\n]+"|\[[^\]]*\])')
NUMBER_TOKEN = re.compile(r'(?<!\d)\d{7,8}(?!\d)')
SKIP = {'code_snapshot', '__pycache__', '.git', 'node_modules', 'public', 'responses', 'views', 'rendered'}


def sequence(order):
    return sorted(order['item_sequence'].values(), key=lambda x: int(x['sequence']))


def profile(rows):
    # Per-box planar rotation is deliberately conservative for near-duplicate exclusion.
    return tuple((min(x['length/mm'], x['width/mm']), max(x['length/mm'], x['width/mm']),
                  x['height/mm'], x['weight/kg']) for x in rows)


def eligible(rows):
    return (14 <= len(rows) <= 20 and all(0 < x['weight/kg'] <= 100 and
            0 < x['height/mm'] <= 850 and 0 < min(x['length/mm'], x['width/mm']) <= 1000 and
            0 < max(x['length/mm'], x['width/mm']) <= 1200 for x in rows) and
            sum(x['length/mm'] * x['width/mm'] * x['height/mm'] for x in rows) <= 1200*1000*850 and
            sum(x['weight/kg'] for x in rows) <= 1000)


def provenance_files(root):
    """All plan/run/private/audit provenance plus dataset and human-facing reports.

    Model requests/images and frozen copies of code are not provenance sources.
    Hash every inspected file, even one without source tokens; record parse errors.
    """
    candidates = set()
    for name in ('docs', 'report', 'semantic_pallet_dataset_v1'):
        for p in (root / name).rglob('*'):
            if p.suffix.lower() in ('.json', '.md', '.html', '.csv', '.txt') and not any(s in SKIP for s in p.relative_to(root).parts):
                candidates.add(p)
    outputs = root / 'semantic_pallet_planner/outputs'
    for run in outputs.iterdir():
        if not run.is_dir() or 'O5_DIRECT_MEMORY' in run.name:
            continue
        for p in run.rglob('*.json'):
            parts = p.relative_to(run).parts
            if any(s in SKIP for s in parts):
                continue
            # Episodes contain actual source identities and are inspected as well.
            candidates.add(p)
    return sorted(candidates)


def exposure_audit(raw, root=ROOT):
    aliases = collections.defaultdict(set)
    for key, order in raw.items():
        for alias in (key, str(order['properties'].get('order_nr', '')), str(order['properties'].get('id', ''))):
            if alias:
                aliases[alias].add(key)
    evidence = collections.defaultdict(list)
    unknown = collections.defaultdict(list)
    incidental = collections.defaultdict(list)
    inspected = []
    reserved = set()
    registry = root / 'semantic_pallet_planner/outputs/DATA_O4_D_RESEARCH_20261024_01/private/source_registry.json'
    if registry.exists():
        for row in read(registry):
            if row.get('split') == 'test':
                reserved.update(aliases.get(str(row['source_order_key']), ()))
    for p in provenance_files(root):
        if 'O5_S0_S1_' in str(p.relative_to(root)):
            continue
        text = p.read_text(errors='replace')
        values = set()
        for match in SOURCE_FIELD.finditer(text):
            try:
                value = json.loads(match.group(1))
                values.update([str(value)] if isinstance(value, (str, int)) else map(str, value))
            except (ValueError, TypeError):
                raise O5Error('UNPARSEABLE_SOURCE_FIELD', str(p)) from None
        # Human-facing text/HTML and report tables may name raw orders without JSON keys.
        structured = set(values)
        if p.suffix.lower() != '.json':
            values.update(NUMBER_TOKEN.findall(text))
        found = set()
        rel = str(p.relative_to(root))
        for value in values:
            if value in aliases:
                found.update(aliases[value])
            elif value in structured:
                unknown[value].append(rel)
            else:
                incidental[value].append(rel)
        for key in found:
            evidence[key].append(rel)
        inspected.append({'path': rel, 'sha256': sha(p), 'matched_raw_orders': sorted(found)})
    return {'schema_version': 'o5_source_exposure_v1', 'files': inspected,
            'evidence': dict(evidence), 'reserved': sorted(reserved),
            'unresolved_references': [{'value': key, 'status': 'UNKNOWN', 'evidence_paths': paths,
                                      'eligible_for_selection': False} for key, paths in sorted(unknown.items())],
            'incidental_unmatched_numeric_token_count': len(incidental),
            'alias_collisions': {a: sorted(v) for a, v in aliases.items() if len(v) > 1},
            'scope': 'repository-recorded exposure/reservations; no claim about model pretraining or external use',
            'rules': 'all matched provenance conservatively excluded; O4-D test registry reserved; aliases unioned'}


def source_clusters(raw):
    """Union aliases, ordered clones, rotation-normalized multisets and shared >=12-box windows.

    Twelve is the historical O4-D/E5 window length. Shorter known V1 windows
    are explicitly compared separately by audit_dataset (source positions).
    A common individual SKU never joins orders on its own.
    """
    parent = {k: k for k in raw}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    edges = []
    def union(a, b, reason):
        x, y = find(a), find(b)
        if x != y:
            parent[max(x, y)] = min(x, y)
            edges.append({'left': a, 'right': b, 'reason': reason})
    seen = {}
    for key, order in sorted(raw.items()):
        p = profile(sequence(order))
        signatures = [('ordered', p), ('multiset', tuple(sorted(p)))]
        signatures += [('alias', alias) for alias in
                       (str(key), str(order['properties'].get('order_nr', key)), str(order['properties'].get('id', key)))]
        # Same complete or partial historical 12-box sequence must not cross splits.
        signatures += [('window12', p[i:i+12]) for i in range(max(0, len(p)-11))]
        signatures += [('window12_multiset', tuple(sorted(p[i:i+12]))) for i in range(max(0, len(p)-11))]
        for kind, signature in signatures:
            token = (kind, signature)
            if token in seen:
                union(key, seen[token], kind)
            else:
                seen[token] = key
    return {k: find(k) for k in raw}, edges


def item_from_raw(row, index):
    return {'item_id': f'box_{index+1:02d}',
            'dimensions_mm': {k: row[k + '/mm'] for k in ('length', 'width', 'height')},
            'mass_kg': row['weight/kg'], 'stackable': True, 'top_load_limit_kg_synthetic': 100.}


def representatives_for(orders, seed):
    representatives = {}
    for row in orders:
        if row['status'] != 'ELIGIBLE':
            continue
        old = representatives.get(row['source_cluster_id'])
        if old is None or digest([seed, row['source_order_key']]) < digest([seed, old['source_order_key']]):
            representatives[row['source_cluster_id']] = row
    return sorted(representatives.values(), key=lambda r: digest([seed, r['source_order_key']]))


def quantile_rule(available, cfg):
    values = sorted(row['maximum_planar_aspect_ratio'] for row in available)
    if not values:
        raise O5Error('BLOCKED_DATA', 'no eligible source cluster')
    rank = math.ceil(cfg['ood_definition']['quantile']*len(values))
    threshold = values[rank-1]
    return {'schema_version': 'o5_ood_frozen_rule_v1', 'data_design_version': cfg['data_design_version'],
            'definition': cfg['ood_definition'], 'population_clusters': len(values), 'rank_1_based': rank,
            'threshold': threshold, 'ties_at_boundary': values.count(threshold),
            'population_digest': digest([{'cluster': r['source_cluster_id'], 'source': r['source_order_key'],
                                         'feature': r['maximum_planar_aspect_ratio']} for r in available]),
            'id_pool': sum(v <= threshold for v in values), 'ood_pool': sum(v > threshold for v in values),
            'sampling_seed': cfg['seed'], 'split_targets': cfg['split_targets'],
            'ordering': 'ID <= threshold; OOD strictly > threshold; all boundary ties remain ID',
            'new_api_attempts': 0, 'planning_calls': 0}


def rule_sources():
    return {str(p.relative_to(ROOT)): sha(p) for p in
            (Path(__file__), Path(__file__).with_name('config.py'), Path(__file__).with_name('common.py'))}


def freeze_rule(audit_data, output, config=None):
    """Persist the approved rule against audited geometry before selecting any split."""
    cfg = load(config)
    audit_data = Path(audit_data).resolve()
    manifest = read(audit_data/'manifest.json')
    ledger_path = audit_data/'source_exposure_ledger.json'
    if manifest['raw_sha256'] != RAW_SHA or manifest['files']['source_exposure_ledger.json'] != sha(ledger_path):
        raise O5Error('AUDIT_INPUT_CHANGED')
    ledger = read(ledger_path)
    available = representatives_for(ledger['orders'], cfg['seed'])
    rule = quantile_rule(available, cfg)
    rule.update(raw_sha256=RAW_SHA, audited_ledger_path=str(ledger_path), audited_ledger_sha256=sha(ledger_path),
                config_digest=digest(cfg), algorithm_sources=rule_sources(),
                authorization='user approved geometric quantile OOD before sampling on2026-10-28',
                frozen_before_sampling=True)
    dest = new_directory(output)
    atomic(dest/'rule.json', rule)
    atomic(dest/'manifest.json', {'schema_version': 'o5_rule_plan_seal_v1', 'rule_digest': digest(rule),
                                'selected_orders': 0, 'new_api_attempts': 0, 'planning_calls': 0})
    return rule


def validate_rule_plan(path, cfg):
    path = Path(path).resolve()
    rule = read(path/'rule.json')
    if (read(path/'manifest.json')['rule_digest'] != digest(rule) or rule['config_digest'] != digest(cfg)
            or rule['raw_sha256'] != RAW_SHA or rule['algorithm_sources'] != rule_sources()
            or rule['audited_ledger_sha256'] != sha(rule['audited_ledger_path'])
            or rule['frozen_before_sampling'] is not True):
        raise O5Error('OOD_RULE_PLAN_CHANGED')
    return rule


def prepare(output, config=None, root=ROOT, rule_plan=None):
    cfg = load(config)
    if root.resolve() == ROOT and rule_plan is None:
        raise O5Error('OOD_RULE_PLAN_REQUIRED', 'freeze the approved rule before preparing real data')
    frozen = validate_rule_plan(rule_plan, cfg) if rule_plan is not None else None
    raw_path = root / 'raw/bed_bpp/bed-bpp_v1.json'
    if sha(raw_path) != RAW_SHA:
        raise O5Error('RAW_DATA_DRIFT')
    raw = read(raw_path)
    audit = exposure_audit(raw, root)
    clusters, edges = source_clusters(raw)
    exposed_clusters = {clusters[k] for k in audit['evidence']}
    reserved_clusters = {clusters[k] for k in audit['reserved']}
    # Explicit V1 provenance windows may be shorter than 12 and are already exposed.
    known_windows = set()
    for p in (root / 'semantic_pallet_dataset_v1/annotations/ground_truth_rules').glob('*.json'):
        row = read(p)
        key = row.get('source_order_key')
        positions = row.get('source_sequence_positions', [])
        if key in raw and positions:
            by_position = {int(x['sequence']): x for x in sequence(raw[key])}
            try:
                known_windows.add(profile([by_position[int(i)] for i in positions]))
            except KeyError:
                raise O5Error('UNRESOLVED_HISTORICAL_WINDOW', str(p)) from None
    by_length = collections.defaultdict(set)
    for window in known_windows:
        by_length[len(window)].add(window)
    ledger = []
    for key, order in sorted(raw.items()):
        rows = sequence(order)
        if not 14 <= len(rows) <= 20:
            continue
        p = profile(rows)
        window_overlap = any(p[i:i+n] in windows for n, windows in by_length.items() if n <= len(p)
                             for i in range(len(p)-n+1))
        status = ('RESERVED' if clusters[key] in reserved_clusters else
                  'EXPOSED' if clusters[key] in exposed_clusters or window_overlap else 'ELIGIBLE')
        if not eligible(rows):
            status = 'INELIGIBLE_PHYSICAL_NECESSARY_CONDITIONS'
        record = {'source_order_key': key, 'source_cluster_id': clusters[key], 'status': status,
                  'planned_items': len(rows), 'ordered_fingerprint': digest(p),
                  'multiset_fingerprint': digest(sorted(p)), 'historical_window_overlap': window_overlap,
                  'evidence_paths': audit['evidence'].get(key, []),
                  'maximum_planar_aspect_ratio': max(b/a for a, b, _, _ in p),
                  'total_volume_ratio': sum(a*b*h for a, b, h, _ in p)/(1200*1000*850)}
        ledger.append(record)
    available = representatives_for(ledger, cfg['seed'])
    rule = quantile_rule(available, cfg)
    if frozen is not None and any(frozen[k] != v for k, v in rule.items()):
        dest = new_directory(output)
        atomic(dest/'source_exposure_ledger.json', {'audit': audit, 'orders': ledger, 'cluster_edges': edges})
        atomic(dest/'initialization_error.json', {'status': 'OOD_RULE_POPULATION_DRIFT', 'expected_rule': frozen,
                                                 'observed_rule': rule, 'new_api_attempts': 0, 'planning_calls': 0})
        raise O5Error('OOD_RULE_POPULATION_DRIFT', 'fresh source audit differs from the frozen rule population')
    iid = [r for r in available if r['maximum_planar_aspect_ratio'] <= rule['threshold']]
    ood = [r for r in available if r['maximum_planar_aspect_ratio'] > rule['threshold']]
    needed_id = sum(cfg['split_targets'][s] for s in ('train', 'development', 'test_id'))
    status = 'PASS' if len(iid) >= needed_id and len(ood) >= 20 else 'BLOCKED_DATA'
    dest = new_directory(output)
    atomic(dest/'source_exposure_ledger.json', {'audit': audit, 'orders': ledger, 'cluster_edges': edges})
    # The rule is durably written before any selection or private task file.
    atomic(dest/'ood_rule.frozen.json', {**rule, 'rule_plan': str(Path(rule_plan).resolve()) if rule_plan else 'SYNTHETIC_TEST_REPOSITORY',
                                       'rule_plan_digest': digest(frozen) if frozen else None,
                                       'frozen_before_sampling': True})
    selections = {}
    if status == 'PASS':
        start = 0
        for split in ('train', 'development', 'test_id'):
            n = cfg['split_targets'][split]
            selections[split] = iid[start:start+n]
            start += n
        selections['test_geometry_ood'] = ood[:20]
        for split, records in selections.items():
            tasks = []
            for index, row in enumerate(records):
                key = row['source_order_key']
                tasks.append({'task_id': f'{split}_{index+1:03d}', 'source_cluster_id': row['source_cluster_id'],
                              'source_order_key': key, 'container': cfg['container'],
                              'items': [item_from_raw(x, i) for i, x in enumerate(sequence(raw[key]))]})
            atomic(dest/f'private/{split}.json', tasks)
            # Evaluator files are separate and not selector inputs. Read-only at rest.
            (dest/f'private/{split}.json').chmod(0o400)
        (dest/'private').chmod(0o700)
    selected = {r['source_order_key'] for rows in selections.values() for r in rows}
    manifest = {'schema_version': 'o5_dataset_manifest_v1', 'protocol_version': VERSION,
                'status': status, 'raw_sha256': RAW_SHA, 'raw_path': str(raw_path.resolve()), 'raw_orders': len(raw),
                'ood_rule': rule,
                'short_orders': len(ledger), 'eligible_source_clusters': len(available),
                'iid_available': len(iid), 'ood_available': len(ood), 'config': cfg,
                'split_counts': {s: len(v) for s, v in selections.items()},
                'splits': {s: [r['source_cluster_id'] for r in rows] for s, rows in selections.items()},
                'selection': selections, 'unselected_digest': digest([r for r in available if r['source_order_key'] not in selected]),
                'status_counts': dict(collections.Counter(r['status'] for r in ledger)),
                'physical_attributes': 'simulated: all stackable, top load100kg; real dimensions/mass/order',
                'independent_collection': False, 'model_pretraining_exposure': 'UNKNOWN',
                'new_api_attempts': 0, 'planning_calls': 0,
                'files': {str(p.relative_to(dest)): sha(p) for p in dest.rglob('*.json')}}
    from .schemas import validate
    validate('DatasetManifest', manifest)
    atomic(dest/'manifest.json', manifest)
    return manifest


def validate_dataset(root):
    root = Path(root)
    manifest = read(root/'manifest.json')
    from .schemas import validate
    validate('DatasetManifest', manifest)
    if manifest['status'] != 'PASS':
        raise O5Error('BLOCKED_DATA')
    from .config import validate as validate_config
    cfg = validate_config(manifest['config'])
    for name, checksum in manifest['files'].items():
        if sha(root/name) != checksum:
            raise O5Error('DATASET_CHANGED', name)
    validate_groups = [set(v) for v in manifest['splits'].values()]
    if any(a & b for i, a in enumerate(validate_groups) for b in validate_groups[i+1:]):
        raise O5Error('SOURCE_SPLIT_LEAKAGE')
    ledger = read(root/'source_exposure_ledger.json')
    available = representatives_for(ledger['orders'], cfg['seed'])
    rule = quantile_rule(available, cfg)
    frozen = read(root/'ood_rule.frozen.json')
    if manifest.get('ood_rule') != rule or any(frozen.get(k) != v for k, v in rule.items()):
        raise O5Error('OOD_RULE_DATASET_MISMATCH')
    if frozen['rule_plan'] != 'SYNTHETIC_TEST_REPOSITORY':
        plan = validate_rule_plan(frozen['rule_plan'], cfg)
        if digest(plan) != frozen['rule_plan_digest'] or any(plan[k] != v for k, v in rule.items()):
            raise O5Error('OOD_RULE_DATASET_MISMATCH')
    iid = [r for r in available if r['maximum_planar_aspect_ratio'] <= rule['threshold']]
    ood = [r for r in available if r['maximum_planar_aspect_ratio'] > rule['threshold']]
    expected, start = {}, 0
    for split in ('train', 'development', 'test_id'):
        n = cfg['split_targets'][split]
        expected[split] = iid[start:start+n]
        start += n
    expected['test_geometry_ood'] = ood[:cfg['split_targets']['test_geometry_ood']]
    if manifest['selection'] != expected or manifest['split_counts'] != cfg['split_targets']:
        raise O5Error('DATA_SELECTION_CHANGED')
    raw_path = Path(manifest['raw_path'])
    if sha(raw_path) != RAW_SHA or manifest['raw_sha256'] != RAW_SHA:
        raise O5Error('RAW_DATA_DRIFT')
    raw = read(raw_path)
    for split, rows in expected.items():
        tasks = read(root/f'private/{split}.json')
        if len(tasks) != len(rows):
            raise O5Error('FULL_ORDER_DERIVATION_CHANGED')
        for index, (task, row) in enumerate(zip(tasks, rows)):
            expected_task = {'task_id': f'{split}_{index+1:03d}', 'source_cluster_id': row['source_cluster_id'],
                             'source_order_key': row['source_order_key'], 'container': cfg['container'],
                             'items': [item_from_raw(x, i) for i, x in enumerate(sequence(raw[row['source_order_key']]))]}
            if task != expected_task or len(task['items']) != row['planned_items']:
                raise O5Error('FULL_ORDER_DERIVATION_CHANGED')
    return manifest

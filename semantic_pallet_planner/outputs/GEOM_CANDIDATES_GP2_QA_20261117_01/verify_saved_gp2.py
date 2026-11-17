"""Independent saved-action audit: never imports or runs a candidate generator.

Checks frozen bytes, exact saved coordinates, real independent geometry_oracle,
and hand-replays the reducer from saved records. No PCT, orders or new pools.
"""
from collections import Counter
from decimal import Decimal
from fractions import Fraction
import hashlib
import importlib.abc
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
QA = Path(__file__).resolve().parent
PACKAGE = ROOT / 'semantic_pallet_planner/src/semantic_pallet_planner'
DELIVERY = ROOT / 'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP2_20261117_01'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path, exact=False):
    def pairs(items):
        out = {}
        for key, value in items:
            assert key not in out, (str(path), key)
            out[key] = value
        return out
    return json.loads(path.read_text(), object_pairs_hook=pairs, parse_float=Decimal if exact else float,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def q(value):
    return Fraction(Decimal(str(value)))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def action_sort(record):
    key = record['action_key']
    return (key[0], *(Fraction(v) for v in key[1:]))


def joint_keys(record):
    key = record['action_key']
    z = Fraction(key[7])
    support = tuple(sorted(record['candidate']['support']['support_item_ids'])) if z else ('GROUND',)
    quadrant = (Fraction(key[5]) >= 0, Fraction(key[6]) >= 0)
    return {(int(key[4]), z, quadrant, support, source) for source in record['sources']}


def saved_joint_keys(rows):
    return {(int(yaw), Fraction(z), tuple(quadrant), tuple(support), source)
            for yaw, z, quadrant, support, source in rows}


def replay(records):
    score_sort = lambda r: (-Decimal(str(r['geometry_score'])), action_sort(r))
    groups = {}
    for record in records:
        key = record['action_key']
        group = (int(key[4]), 'floor' if Fraction(key[7]) == 0 else 'upper')
        groups.setdefault(group, []).append(record)
    selected, covered, trace = [], set(), []
    def add(record, reason):
        new = joint_keys(record) - covered
        selected.append(record)
        trace.append((tuple(record['action_key']), reason, len(new)))
        covered.update(joint_keys(record))
    for group in sorted(groups):
        add(min(groups[group], key=score_sort), 'REQUIRED_YAW_LEVEL')
    selected_keys = {tuple(r['action_key']) for r in selected}
    remaining = [r for r in records if tuple(r['action_key']) not in selected_keys]
    while remaining and len(selected) < 16:
        chosen = min(remaining, key=lambda r: (-len(joint_keys(r) - covered), *score_sort(r)))
        add(chosen, 'JOINT_COVERAGE' if joint_keys(chosen) - covered else 'SCORE_FILL')
        remaining.remove(chosen)
    return sorted(selected, key=action_sort), trace, covered, groups


class OracleOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('semantic_pallet_planner.') and fullname not in {
            'semantic_pallet_planner.evaluation', 'semantic_pallet_planner.evaluation.geometry_oracle'}:
            raise RuntimeError('forbidden project import: ' + fullname)
        if fullname.split('.')[0] in {'numpy', 'scipy', 'torch', 'requests', 'httpx'}:
            raise RuntimeError('forbidden dependency: ' + fullname)


def audit(event, args):
    if event.startswith(('socket.', 'subprocess.')) or event in {'os.system', 'os.fork', 'os.posix_spawn'}:
        raise RuntimeError('forbidden operation: ' + event)
    if event == 'open' and any(t in str(args[0]).lower() for t in ('credentials', 'secrets.json', 'api_key', '.pem', '.env')):
        raise RuntimeError('forbidden credential read')


def main():
    assert len(sys.argv) == 3 and sys.argv[1] == '--output'
    output = (ROOT / sys.argv[2]).resolve()
    assert output.is_relative_to(QA) and not output.exists()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    seal = load(DELIVERY / 'delivery_manifest.json')
    listed = {row['path']: row['sha256'] for row in seal['files']}
    assert len(listed) == len(seal['files'])
    assert all(sha(ROOT / name) == digest for name, digest in listed.items())
    package_members = {p.relative_to(ROOT).as_posix() for p in DELIVERY.rglob('*') if p.is_file()}
    excluded = {(DELIVERY / name).relative_to(ROOT).as_posix()
                for name in ('delivery_manifest.json', 'delivery_verification.log')}
    assert package_members - excluded == {name for name in listed if name.startswith(DELIVERY.relative_to(ROOT).as_posix() + '/')}
    source = load(DELIVERY / 'source_manifest.json')
    current = {p.relative_to(PACKAGE).as_posix(): sha(p) for p in PACKAGE.rglob('*')
               if p.is_file() and p.suffix in ('.py', '.json')
               and not {'tests', '__pycache__'}.intersection(p.relative_to(PACKAGE).parts)}
    old = load(ROOT / 'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP1_FIX_20261117_01/source_manifest.json')['files']
    assert current == source['files'] and all(current[k] == h for k, h in old.items())
    added = sorted(set(current) - set(old))
    assert added == sorted(source['added_production_files']) and len(added) == 3
    external = []
    for name, digest in listed.items():
        if name not in package_members:
            blob = subprocess.check_output(['git', 'show', head + ':' + name], cwd=ROOT)
            assert hashlib.sha256(blob).hexdigest() == digest
            external.append({'path': name, 'sha256': digest, 'git_commit': head})
    sys.meta_path.insert(0, OracleOnly())
    sys.addaudithook(audit)
    from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate
    inputs = load(DELIVERY / 'input_manifest.json')['inputs']
    results, raw_checks, proposal_refs = [], 0, 0
    for entry in inputs:
        input_path = ROOT / entry['path']
        assert sha(input_path) == entry['sha256']
        scene = load(input_path)
        exact = load(input_path, exact=True)
        name = entry['scene']
        result = load(DELIVERY / 'constructed' / (name + '_result.json'))
        audit_data = result['audit']
        assert audit_data['source_bytes_sha256'] == entry['sha256']
        assert audit_data['space_index_builds'] == 1 and audit_data['outcome'] == result['status']
        assert hashlib.sha256(canonical({k: v for k, v in audit_data.items() if k != 'semantic_digest'})).hexdigest() == audit_data['semantic_digest']
        hosts = {s['space_id']: (tuple(map(Fraction, s['bounds_mm'])), set(s['source_types'])) for s in audit_data['spaces']}
        levels = {Fraction(0)} | {q(o['pose']['z_base_mm']) + q(o['oriented_size_mm'][2]) for o in exact['placed_items']}
        assert [r['item_id'] for r in audit_data['items']] == [r['item_id'] for r in sorted(exact['buffer_items'], key=lambda r: r['arrival_index'])]
        expected_final, scene_raw = [], 0
        for item_audit in audit_data['items']:
            item = next(x for x in exact['buffer_items'] if x['item_id'] == item_audit['item_id'])
            dimensions = tuple(q(item['dimensions_mm'][k]) for k in ('length', 'width', 'height'))
            expected_attempts = 0
            for yaw in (0, 90):
                l, w, h = dimensions if yaw == 0 else (dimensions[1], dimensions[0], dimensions[2])
                expected_attempts += sum(5 * len(sources) for b, sources in hosts.values()
                                         if b[2] in levels and b[3]-b[0] >= l and b[4]-b[1] >= w and b[5]-b[2] >= h)
            assert item_audit['enumeration_complete'] is True
            assert item_audit['raw_point_attempts'] == expected_attempts <= 32768
            records = item_audit['raw_valid_candidates']
            keys = [tuple(r['action_key']) for r in records]
            assert len(keys) == len(set(keys)) == item_audit['raw_valid_count']
            assert records == sorted(records, key=action_sort)
            for record in records:
                key = record['action_key']; candidate = record['candidate']
                l, w, h = map(Fraction, key[1:4]); xyz = tuple(map(Fraction, key[5:])); yaw = int(key[4])
                expected_dims = dimensions if yaw == 0 else (dimensions[1], dimensions[0], dimensions[2])
                assert key[0] == item['item_id'] and (l, w, h) == expected_dims
                assert candidate['pick_item_id'] == key[0] and candidate['pose']['yaw_deg'] == yaw
                assert tuple(q(candidate['pose'][k]) for k in ('x_mm', 'y_mm', 'z_base_mm')) == xyz
                assert tuple(map(q, candidate['oriented_size_mm'])) == (l, w, h)
                assert xyz[2] in levels
                low = (xyz[0]-l/2, xyz[1]-w/2, xyz[2]); high = (xyz[0]+l/2, xyz[1]+w/2, xyz[2]+h)
                for sid in record['host_ids']:
                    b, _ = hosts[sid]
                    assert all(b[d] <= low[d] and high[d] <= b[d+3] for d in range(3))
                def host_rank(sid):
                    b, _ = hosts[sid]
                    return ((b[3]-b[0])*(b[4]-b[1])*(b[5]-b[2]), b)
                assert record['representative_host'] == min(record['host_ids'], key=host_rank)
                assert set(record['sources']) == {p['source_type'] for p in record['proposal_refs']}
                assert set(record['host_ids']) == {p['host_id'] for p in record['proposal_refs']}
                for reference in record['proposal_refs']:
                    b, sources = hosts[reference['host_id']]
                    assert reference['source_type'] in sources
                    # Verify the saved reference algebra, without enumerating a new pool.
                    pi = reference['point_index']
                    expected_x = b[0] if pi in (0, 2) else b[3]-l if pi in (1, 3) else (b[0]+b[3]-l)/2
                    expected_y = b[1] if pi in (0, 1) else b[4]-w if pi in (2, 3) else (b[1]+b[4]-w)/2
                    corner = tuple(map(Fraction, reference['proposal_corner_mm']))
                    assert pi in range(5) and corner == (expected_x, expected_y, b[2])
                    center = (corner[0]+l/2, corner[1]+w/2, corner[2])
                    assert tuple(Fraction(round(v*1000), 1000) for v in center) == xyz
                    assert center[2] == xyz[2]
                    proposal_refs += 1
                errors = check_candidate({'placed_items': scene['placed_items'], 'available_items': scene['buffer_items']},
                                         {'container': scene['container']}, candidate)
                assert not errors, (name, key, errors)
                raw_checks += 1
                expected_score = sum(Decimal(str(candidate['geometry_score_components'][k])) * Decimal(str(weight))
                                     for k, weight in {'compactness': .35, 'height': .25, 'stability': .25, 'balance': .15}.items())
                assert Decimal(str(record['geometry_score'])) == expected_score
                fingerprint = hashlib.sha256(canonical({'backend': result['backend'], 'input': audit_data['input_digest'], 'action': key})).hexdigest()
                assert candidate['candidate_fingerprint'] == fingerprint and candidate['candidate_id'] == 'G2_' + fingerprint[:24]
            rejected = item_audit['proposal_rejections']
            assert len(rejected) + sum(len(r['proposal_refs']) for r in records) == expected_attempts
            assert dict(Counter(r['reason'] for r in rejected)) == item_audit['rejection_counts']
            assert sum(r['reason'] == 'POSE_REPRESENTATION_REJECTED' for r in rejected) == item_audit['unrepresentable_proposals']
            assert len(set(keys) | {tuple(r['action_key']) for r in rejected}) == item_audit['unique_actions']
            chosen, trace, covered, groups = replay(records)
            actual_trace = [(tuple(t['action_key']), t['reason'], t['new_joint_keys']) for t in item_audit['coverage']['selection_order']]
            assert trace == actual_trace
            assert item_audit['coverage']['required_groups'] == [list(g) for g in sorted(groups)]
            all_joint = set().union(*(joint_keys(r) for r in records)) if records else set()
            assert saved_joint_keys(item_audit['coverage']['raw_joint_keys']) == all_joint
            assert saved_joint_keys(item_audit['coverage']['final_joint_keys']) == covered
            assert saved_joint_keys(item_audit['coverage']['uncovered_joint_keys']) == all_joint-covered
            assert item_audit['final_action_keys'] == [r['action_key'] for r in chosen]
            assert item_audit['final_candidates'] == len(chosen) == min(16, len(records))
            assert item_audit['coverage']['compressed_count'] == len(records)-len(chosen)
            expected_final.extend(r['candidate'] for r in chosen); scene_raw += len(records)
        assert expected_final == result['candidates'] and len(expected_final) <= 48
        assert result['status'] == ('OK' if expected_final else 'OK_EMPTY') and result['error'] is None
        results.append({'scene': name, 'status': 'PASS', 'raw_unique_checked': scene_raw,
                        'final': len(expected_final), 'per_item_final': [r['final_candidates'] for r in audit_data['items']]})
    faults = []
    for path in sorted((DELIVERY / 'faults').glob('*.json')):
        value = load(path)
        assert value['status'] == 'ERROR' and value['candidates'] == []
        faults.append({'path': path.relative_to(ROOT).as_posix(), 'status': 'PASS_SAVED_ERROR',
                       'error': value['error'], 'kind': 'TEST_DOUBLE' if 'TEST_DOUBLE' in path.name else 'ARCHIVED_REAL_DISAGREEMENT'})
    result = {'version': 'geometry_gp2_qa_saved_audit_v1', 'date': '2026-11-17', 'timezone': 'Asia/Shanghai',
              'status': 'PASS_SAVED_ACTIONS_AND_ARITHMETIC', 'head': head, 'python': platform.python_version(),
              'delivery_listed_files': len(listed), 'package_members': len(package_members),
              'explicit_exclusions': sorted(excluded), 'external_snapshots': external,
              'production_files': len(current), 'old_production_unchanged': len(old), 'added_production_files': added,
              'scenes': results, 'independent_oracle_calls_on_saved_unique_actions': raw_checks,
              'saved_proposal_references_arithmetically_checked': proposal_refs, 'fault_records': faults,
              'boundary': {'candidate_generation_or_reconstruction': 0, 'original_evaluate_pose_calls': 0,
                           'orders': 0, 'forks': 0, 'PCT_LP': 0, 'model_calls': 0,
                           'production_imports': ['evaluation.geometry_oracle'],
                           'original_gp2_test_rerun': 'NOT_RUN_SKILL_FORBIDS_CANDIDATE_RECONSTRUCTION'},
              'limits': 'Archived current outputs and mathematical reducer replay only; does not prove new generation on unseen states, original preproposal execution or full runtime integration.'}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': result['status'], 'production_files': len(current), 'scenes': len(results),
                      'saved_unique_oracle_checks': raw_checks, 'saved_proposal_ref_checks': proposal_refs}, ensure_ascii=False))


if __name__ == '__main__':
    main()

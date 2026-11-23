"""Verify tracked GP6 evidence without importing or executing the planner."""
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / 'semantic_pallet_planner/outputs'
PREFIX = 'GEOM_CANDIDATES_GP6_TOP_LOAD_'
AUTH = OUTPUT / (PREFIX + 'AUTHORIZED_20261122_01')
RUN = OUTPUT / (PREFIX + 'DISABLED_RUN_20261122_01')
LEDGERS = OUTPUT / (PREFIX + 'DISABLED_LEDGERS_20261122_01')
SWITCH = OUTPUT / (PREFIX + 'SWITCH_20261122_01')
BASELINE = OUTPUT / 'GEOM_CANDIDATES_GP6_F0_FORMAL_RUN_20261122_01'
SOURCE = ROOT / 'semantic_pallet_planner/src/semantic_pallet_planner'


def read(path):
    return json.loads(path.read_bytes())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode())


def keys(value):
    if isinstance(value, dict):
        return set(value).union(*(keys(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(keys(child) for child in value))
    return set()


def main():
    manifest = read(AUTH / 'delivery_manifest.json')
    for path, expected in manifest['files'].items():
        assert sha((ROOT / path).read_bytes()) == expected, path
    plan = read(RUN / 'plan.json')
    plan_id = digest(plan)
    assert plan == read(AUTH / 'gp6_top_load_plan_FROZEN.json')
    scope = read(AUTH / 'scope_authorization_APPROVED.json')
    review = read(AUTH / 'scope_review_APPROVED.json')['independent_review_reference']
    assert sha((ROOT / review['path']).read_bytes()) == review['sha256']
    assert plan_id == manifest['plan_digest'] == scope['plan_digest']
    assert scope['jobs'] == ['G00', 'G01'] and scope['single_execution']
    assert plan['status'] == 'FROZEN' and not plan['packaging_top_load_limit_enabled']
    source_manifest = {
        path.relative_to(SOURCE).as_posix(): sha(path.read_bytes())
        for path in sorted(SOURCE.rglob('*'))
        if path.is_file() and path.suffix in ('.py', '.json')
        and not {'tests', '__pycache__'}.intersection(path.relative_to(SOURCE).parts)
    }
    assert digest(source_manifest) == plan['source_identity']
    subprocess.run(['git', 'diff', '--exit-code', '51901de04..7e0bc28c',
                    '--', 'semantic_pallet_planner/src',
                    'semantic_pallet_planner/tests', str(SWITCH.relative_to(ROOT))],
                   cwd=ROOT, check=True)
    driver = read(RUN / 'driver_receipt.json')
    request_ledger = read(LEDGERS / 'requests/requests.json')
    call_ledger = read(LEDGERS / 'calls/calls.json')
    execution = read(AUTH / 'execution_receipt.json')
    assert execution['execution_invocations'] == 1 and execution['exit_code'] == 0
    assert execution['driver_sha256'] == driver['driver_sha256'] == sha(
        (SWITCH / 'formal_jev_driver.py').read_bytes())
    assert {driver['plan_digest'], request_ledger['plan_digest'],
            call_ledger['plan_digest'], read(RUN / 'run.json')['plan_digest']} == {plan_id}
    assert driver['status'] == 'COMPLETE_2_OF_2_DISPATCHED' and driver['no_implicit_retry']
    assert len({row['decision_id'] for row in request_ledger['requests']}) == 12
    requests = {row['decision_id']: row for row in request_ledger['requests']}
    assert len(requests) == len(request_ledger['requests'])
    remaining = set(requests)
    calls = call_ledger['calls']
    assert all(row['state'] == 'DONE' for row in calls)
    assert Counter(row['kind'] for row in calls) == {
        'assessment_entries': 12, 'solver_calls': 364}
    assert call_ledger['counts']['test_double_assessments'] == 0

    jobs = []
    forbidden = {'max_top_load_kg', 'effective_top_permission_kg',
                 'remaining_top_load_kg', 'capacity_utilization',
                 'utilization_status', 'top_load_limit_kg_synthetic'}
    assert [row['job_id'] for row in driver['rows']] == ['G00', 'G01']
    for row, count in zip(driver['rows'], (8, 4)):
        jid = row['job_id']
        folder = RUN / 'jobs' / jid
        config, checkpoint, metric = (read(folder / name) for name in
                                      ('config.json', 'checkpoint.json', 'metrics.json'))
        assert config['packaging_top_load_limit_enabled'] is False
        assert config['stability_monitor']['enabled'] and config['max_retries'] == 0
        assert config['transport_evidence'] == 'REAL_JEV'
        assert config['monitor_evidence'] == 'REAL_KERNEL'
        placed = [event for event in checkpoint['events'] if event['event'] == 'PLACE']
        assert len(placed) == count == row['placed_items'] == metric['placed_items']
        assert row['planned_items'] == metric['planned_items'] == 19
        assert count <= plan['per_job_max_sends'] == scope['per_job_max_sends'] == 19
        assert not metric['completed'] and metrics_match(metric, count)
        for event in placed:
            decision = event['decision_id']
            remaining.remove(decision)
            record = requests[decision]
            assert record['job_id'] == jid and record['send_started']
            assert record['state'] == 'SELECTION_SAVED'
            assert [step['state'] for step in record['history']] == [
                'INTENT', 'SENDING', 'RESPONSE_SAVED', 'SELECTION_SAVED']
            transport = record['transport']
            assert transport['network_attempted'] and transport['http_status'] == 200
            assert record['selection']['served_model'] == plan['model'] == 'jev-1.14.0'
            assert record['selection'] == event['selection']
            context = event['context']
            body = context['request_body']
            assert digest(body) == record['body_digest']
            assert body['state']['packaging_top_load_limit_enabled'] is False
            assert not (keys(body) & forbidden)
            assert {'mass_kg', 'support_ratio'} <= keys(body)
            mapping = context['display_mapping'][event['selection']['selected_display_id']]
            candidate = next(c for c in event['bundle']['physical_candidates']
                             if c['candidate_id'] == mapping['candidate_id'])
            assert digest(candidate) == mapping['candidate_digest']
            assert candidate['candidate_id'] == event['selection']['selected_candidate_id']
            item = next(i for i in event['after']['placed_items']
                        if i['item_id'] == candidate['pick_item_id'])
            assert item['pose'] == candidate['pose']
            assert item['oriented_size_mm'] == candidate['oriented_size_mm']
            assert event['action'] == event['proposed_action']
            assert event['monitor']['status'] == 'STABLE'
        terminal = checkpoint['events'][-1]
        assert terminal['event'] == 'STOP' and terminal['monitor'] is None
        assert checkpoint['reason'] == row['termination_reason'] == terminal['reason']
        assert terminal['reason'] == 'STOP_NO_PHYSICAL_CANDIDATE'
        assert terminal['context']['request_body'] is None
        assert not terminal['bundle']['physical_candidates']
        counts = terminal['bundle']['generation_counts']
        rejection = Counter()
        for item in counts:
            assert sum(item['rejections'].values()) == item['enumeration_attempts']
            rejection.update(item['rejections'])
        assert rejection == ({'out_of_bounds': 10224, 'overlap': 2565} if jid == 'G00'
                             else {'insufficient_support': 150})
        old = read(BASELINE / 'jobs' / jid / 'metrics.json')
        assert old['task_id'] == metric['task_id']
        jobs.append({'job_id': jid, 'placed': count, 'planned': 19,
                     'old_placed': old['placed_items'],
                     'container_utilization': metric['fixed_container_utilization'],
                     'old_container_utilization': old['fixed_container_utilization'],
                     'envelope_utilization': metric['envelope_utilization'],
                     'terminal_rejections': rejection})
    assert not remaining
    assert len(requests) <= scope['shared_max_sends'] == 38
    print(json.dumps({'status': 'PASS', 'manifest_files': len(manifest['files']),
                      'source_identity': plan['source_identity'], 'plan_digest': plan_id,
                      'requests_checked': len(requests), 'call_counts': call_ledger['counts'],
                      'jobs': jobs}, ensure_ascii=False, indent=2))


def metrics_match(metric, count):
    cost = metric['cost']
    return (cost['model_calls'] == cost['send_reservations'] == count
            and cost['failed_requests'] == cost['unknown_sends'] == 0
            and metric['packaging_top_load_compliance'] == 'NOT_APPLICABLE')


if __name__ == '__main__':
    main()

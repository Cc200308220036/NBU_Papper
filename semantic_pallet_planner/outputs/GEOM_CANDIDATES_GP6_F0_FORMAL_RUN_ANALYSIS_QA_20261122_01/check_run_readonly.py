"""Reconcile the saved GP6 batch, request rows, and placements without replay."""
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path

OUTPUT = Path('semantic_pallet_planner/outputs')
RUN = OUTPUT / 'GEOM_CANDIDATES_GP6_F0_FORMAL_RUN_20261122_01'
FREEZE = OUTPUT / 'GEOM_CANDIDATES_GP6_F0_FINAL_FREEZE_20261122_01'
PRIOR = OUTPUT / 'GEOM_CANDIDATES_GP6_F0_CREDENTIAL_FAILURE_ARCHIVE_20261122_01'


def read(path):
    return json.loads(path.read_bytes())


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def main():
    receipt = read(RUN / 'driver_receipt.json')
    run = read(RUN / 'run.json')
    plan = read(RUN / 'plan.json')
    assert plan == read(FREEZE / 'gp6_f0_order_plan_FROZEN.json')
    pd = digest(plan)
    allocation = read(FREEZE / 'ledgers/requests.json')
    meter = read(FREEZE / 'ledgers/shared_call_ledger.json')
    assert allocation['record_digest'] == digest({k: v for k, v in allocation.items() if k != 'record_digest'})
    assert pd == receipt['plan_digest'] == run['plan_digest'] == allocation['plan_digest'] == meter['plan_digest']
    assert receipt['status'] == 'COMPLETE_4_OF_4_DISPATCHED' and receipt['first_error'] is None
    assert receipt['dispatched_jobs'] == receipt['planned_jobs'] == len(run['rows']) == 4
    assert meter['evidence'] == 'REAL_KERNEL'
    actual_calls = Counter((r['job_id'], r['kind']) for r in meter['calls'])
    assert all(r['state'] == 'DONE' for r in meter['calls'])
    requests = {(r['job_id'], r['decision_id']): r for r in allocation['requests']}
    assert len(requests) == len(allocation['requests'])
    remaining = set(requests)
    summaries = []
    for row, job_receipt in zip(run['rows'], receipt['rows']):
        job = row['job_id']
        job_root = RUN / 'jobs' / job
        metrics = row['metrics']
        assert row['status'] == job_receipt['status'] == 'STOPPED'
        assert metrics == read(job_root / 'metrics.json')
        assert metrics['termination_reason'] == job_receipt['termination_reason'] == 'STOP_NO_PHYSICAL_CANDIDATE'
        assert not metrics['completed'] and metrics['planned_items'] == 19
        assert metrics['placed_items'] == job_receipt['placed_items']
        assert read(job_root / 'config.json')['runtime_identity']['source_identity'] == plan['source_identity']
        checkpoint = read(job_root / 'checkpoint.json')
        assert checkpoint == read(job_root / 'record.json')['checkpoint']
        assert checkpoint['phase'] == 'TERMINATED' and checkpoint['reason'] == metrics['termination_reason']
        events = [e for e in checkpoint['events'] if e.get('bundle')]
        stop = events[-1]
        placements = events[:-1]
        assert len(placements) == metrics['placed_items']
        assert stop['event'] == 'STOP' and not stop['bundle']['physical_candidates']
        assert stop['selection'] is None and stop['monitor'] is None
        assert (job, stop['decision_id']) not in requests
        counts = Counter()
        for item in stop['bundle']['generation_counts']:
            counts.update(item['rejections'])
            assert item['returned'] == 0
        tokens = Counter()
        latency = 0
        for event in placements:
            assert event['event'] == 'PLACE' and event['monitor']['status'] == 'STABLE'
            key = (job, event['decision_id'])
            r = requests[key]
            remaining.remove(key)
            t = r['transport']
            s = event['selection']
            context = event['context']
            assert r['state'] == 'SELECTION_SAVED' and r['origin'] == 'jev' and r['send_started']
            assert t['http_status'] == 200 and t['network_attempted'] is True and t['status'] == 'OK'
            assert s == r['selection'] and r['selection_digest'] == digest(s)
            assert digest(context) == r['context_digest'] and digest(context['request_body']) == r['body_digest']
            assert context['request_body']['state']['memories'] == []
            raw = base64.b64decode(t['raw_body_b64'], validate=True)
            assert hashlib.sha256(raw).hexdigest() == t['raw_sha256'] == s['raw_response_digest']
            response = json.loads(raw)
            assert response['model'] == s['served_model'] == 'jev-1.14.0'
            choice = response['answers']['next_action']['choice']
            assert choice == s['selected_display_id']
            assert context['display_mapping'][choice]['candidate_id'] == s['selected_candidate_id'] == event['action']['candidate_id']
            assert response['usage'] == s['usage']
            tokens.update(response['usage'])
            latency += t['latency_s']
        assert metrics['cost']['model_calls'] == metrics['cost']['successful_selections'] == len(placements)
        assert metrics['counts']['assessment_entries'] == actual_calls[(job, 'assessment_entries')] == len(placements)
        assert metrics['counts']['solver_calls'] == actual_calls[(job, 'solver_calls')]
        summaries.append({
            'job': job, 'backend': metrics['candidate_backend'], 'task': metrics['task_id'],
            'placed': len(placements), 'planned': metrics['planned_items'], 'arrived': metrics['arrived_items'],
            'placed_volume_ratio': metrics['placed_volume_ratio'], 'placed_mass_ratio': metrics['placed_mass_ratio'],
            'container_utilization': metrics['fixed_container_utilization'],
            'envelope_utilization': metrics['envelope_utilization'], 'height_mm': metrics['max_height_mm'],
            'stop_decision': stop['decision_id'], 'stop_rejections': counts,
            'empty_pool_before_end_of_stream': not stop['before']['end_of_stream'],
            'requests': len(placements), 'tokens': tokens, 'http_latency_s': latency,
            'lp_calls': metrics['counts']['solver_calls'],
            'timings': {v['segment']: v['seconds'] for v in metrics['timings']},
        })
    assert not remaining
    assert meter['counts'] == {'assessment_entries': len(requests),
                              'solver_calls': sum(x['lp_calls'] for x in summaries), 'test_double_assessments': 0}
    old = read(PRIOR / 'ledgers/requests.json')['requests']
    assert len(old) == 1 and old[0]['transport']['network_attempted'] is False
    totals = Counter()
    timing = Counter()
    for row in summaries:
        totals.update(row['tokens'])
        timing.update(row['timings'])
    print(json.dumps({
        'plan_digest': pd, 'source_identity': plan['source_identity'], 'jobs': summaries,
        'confirmed_model_requests': len(requests), 'monitor_and_lp_counts': meter['counts'],
        'sum_http_latency_s': sum(x['http_latency_s'] for x in summaries),
        'tokens': totals, 'timing_sums': timing,
        'prior_local_credential_failure_separate': True, 'actual_billing': 'UNKNOWN',
        'qa_model_calls': 0, 'qa_replay': 'NOT_RUN',
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

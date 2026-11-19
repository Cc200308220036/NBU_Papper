"""Fixed GP5-P2 4+6 corrected offline driver (GP5_P2_OFFLINE_DRIVER_CORRECTION_ONLY).

No approvals, launch records, completion reviews, or freezes are issued here.
Production sources and original frozen archives remain untouched.
"""
import argparse
import copy
import hashlib
import json
import shutil
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from semantic_pallet_planner.jev_select import geometry_order_execution as order
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.geometry_kernel_completion import check_success, required_coverage
from semantic_pallet_planner.jev_select.ledger import write

R = Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_BOUNDED_REAL_MONITOR_RUNTIME_20261119_01')
PHASES = ('SELECTED', 'MONITORED', 'COMMITTED')
EXPECTED_PLAN_DIGEST = '2e97da50ad87c91b50b0259129f1dfc0b584e11c653d23a9a25830f3499d6433'
EXPECTED_MONITOR_DIGEST = 'b6cda604eaf1640c48c7d6d71fb536f4ef777cac56ca2de0c01b8ed4dda3ab07'
LIMITS = {'assessment_entries': 8, 'solver_calls': 128}
ZERO_COUNTS = {'assessment_entries': 0, 'solver_calls': 0, 'test_double_assessments': 0}


def read(path):
    return json.loads(Path(path).read_bytes())


def hashes(root):
    root = Path(root)
    return {
        str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(root.rglob('*'))
        if f.is_file()
    }


def bind_external_reference(reference, specified, *, label):
    """GP5-P2-DRIVER-AUTH-01: bind launch reference to independently specified file path and SHA-256."""
    assert type(reference) is dict and set(reference) == {'path', 'sha256'}, f'{label}_REFERENCE_CONTRACT'
    if type(specified) is dict:
        assert set(specified) == {'path', 'sha256'}, f'{label}_SPECIFIED_CONTRACT'
        target = Path(specified['path'])
        expected_sha = specified['sha256']
    else:
        target = Path(specified)
        expected_sha = None
    raw = target.read_bytes()
    actual_sha = p.sha(raw)
    assert Path(reference['path']).resolve() == target.resolve(), f'{label}_REFERENCE_PATH_MISMATCH'
    if expected_sha is not None:
        assert actual_sha == expected_sha, f'{label}_FILE_BYTES_DRIFT'
        assert reference['sha256'] == expected_sha, f'{label}_REFERENCE_SHA256_MISMATCH'
    assert reference['sha256'] == actual_sha, f'{label}_REFERENCE_SHA256_MISMATCH'
    doc = p.read_reference(reference)
    assert doc == json.loads(raw), f'{label}_REFERENCE_PAYLOAD_MISMATCH'
    return doc, {'path': str(target), 'resolved_path': str(target.resolve()), 'sha256': actual_sha}


def check_initial_zero_ledger(plan):
    """GP5-P2-DRIVER-LEDGER-01: require a clean, zero-count shared ledger before first dispatch.

    Never clears or overwrites a non-empty prior ledger.
    """
    path = Path(plan['call_ledger_path'])
    v = read(path)
    assert set(v) == {'version', 'plan_digest', 'evidence', 'limits', 'calls', 'counts'}, 'LEDGER_SCHEMA_MISMATCH'
    assert v['version'] == 'geometry_call_ledger_v1', 'LEDGER_VERSION_MISMATCH'
    assert v['evidence'] == 'REAL_KERNEL' and v['plan_digest'] == digest(plan), 'LEDGER_IDENTITY_MISMATCH'
    assert v['limits'] == LIMITS, 'LEDGER_LIMITS_MISMATCH'
    assert v['calls'] == [], 'NONEMPTY_INITIAL_LEDGER_CALLS'
    assert v['counts'] == ZERO_COUNTS, 'NONZERO_INITIAL_LEDGER_COUNTS'
    return copy.deepcopy(v)


def check_counts(plan, *, previous=None, job_id=None, expected_assessment_delta=None, require_solver_delta=False):
    """GP5-P2-DRIVER-LEDGER-01: validate in-flight shared ledger integrity, attribution, and increments."""
    v = read(plan['call_ledger_path'])
    assert set(v) == {'version', 'plan_digest', 'evidence', 'limits', 'calls', 'counts'}, 'LEDGER_SCHEMA_MISMATCH'
    assert v['version'] == 'geometry_call_ledger_v1', 'LEDGER_VERSION_MISMATCH'
    assert v['evidence'] == 'REAL_KERNEL' and v['plan_digest'] == digest(plan), 'LEDGER_IDENTITY_MISMATCH'
    assert v['limits'] == LIMITS, 'LEDGER_LIMITS_MISMATCH'
    assert v['counts']['test_double_assessments'] == 0, 'TEST_DOUBLE_IN_REAL_LEDGER'
    calls = v['calls']
    assert all(
        set(c) == {'kind', 'state', 'index', 'job_id'}
        and c['state'] == 'DONE'
        and c['kind'] in LIMITS
        and c['index'] == idx
        for idx, c in enumerate(calls)
    ), 'UNKNOWN_OR_FAILED_CALL'
    for k, limit in LIMITS.items():
        total = sum(c['kind'] == k for c in calls)
        assert v['counts'][k] == total <= limit, f'LEDGER_COUNT_OR_LIMIT_DRIFT:{k}'
    if previous is not None:
        prev_calls = previous['calls']
        assert len(calls) >= len(prev_calls) and calls[:len(prev_calls)] == prev_calls, 'LEDGER_HISTORY_MUTATED'
        new_calls = calls[len(prev_calls):]
        if job_id is not None:
            assert all(c['job_id'] == job_id for c in new_calls), 'LEDGER_CALL_JOB_ATTRIBUTION_MISMATCH'
        delta = {
            k: v['counts'][k] - previous['counts'][k]
            for k in ('assessment_entries', 'solver_calls', 'test_double_assessments')
        }
        assert delta['test_double_assessments'] == 0, 'TEST_DOUBLE_DELTA_NONZERO'
        assert all(delta[k] == sum(c['kind'] == k for c in new_calls) for k in LIMITS), 'LEDGER_DELTA_MISMATCH'
        if expected_assessment_delta is not None:
            assert delta['assessment_entries'] == expected_assessment_delta, 'UNEXPECTED_ASSESSMENT_DELTA'
        if expected_assessment_delta == 0:
            assert delta['solver_calls'] == 0 and new_calls == [], 'UNEXPECTED_SOLVER_CALLS_ON_ZERO_ASSESSMENT'
        elif require_solver_delta:
            assert delta['solver_calls'] > 0, 'MISSING_SOLVER_CALLS_FOR_ASSESSMENT'
        return copy.deepcopy(v), delta
    return copy.deepcopy(v)


def verify_final_ledger_coverage(plan, coverage):
    """GP5-P2-DRIVER-LEDGER-01: verify final 4+6 assessment total (6+2=8) and per-job attribution."""
    v = check_counts(plan)
    calls = v['calls']
    ids = {r['job_id'] for r in coverage['primary']}
    assert all(c['job_id'] in ids for c in calls), 'UNKNOWN_JOB_ID_IN_LEDGER'
    for row in coverage['primary']:
        expected_assessments = len(row['poses']) + int(row['task_id'] == 'GP5_SYNTH_K01')
        actual_assessments = sum(c['kind'] == 'assessment_entries' and c['job_id'] == row['job_id'] for c in calls)
        actual_solvers = sum(c['kind'] == 'solver_calls' and c['job_id'] == row['job_id'] for c in calls)
        assert actual_assessments == expected_assessments, f'ASSESSMENT_COVERAGE_MISMATCH:{row["job_id"]}'
        assert actual_solvers > 0, f'SOLVER_COVERAGE_MISSING:{row["job_id"]}'
    assert v['counts']['assessment_entries'] == 8 <= LIMITS['assessment_entries'], 'FINAL_ASSESSMENT_TOTAL_MISMATCH'
    assert 0 < v['counts']['solver_calls'] <= LIMITS['solver_calls'], 'FINAL_SOLVER_TOTAL_MISMATCH'
    return copy.deepcopy(v['counts'])


def prepare(runtime, review_path, launch_path, authorization_path=None):
    runtime = Path(runtime)
    plan = read(runtime / 'acceptance_plan_FROZEN.json')
    snap = read(runtime / 'monitor_snapshot.json')
    req = read(runtime / 'startup_review_request.json')
    for k, v in (
        ('plan_digest', digest(plan)),
        ('monitor_digest', digest(snap)),
        ('source_identity', plan['source_identity']),
        ('environment_digest', plan['environment_digest']),
    ):
        assert req[k] == v, f'STARTUP_REQUEST_DRIFT:{k}'
    for key in ('plan_reference', 'monitor_reference'):
        p.read_reference(req[key])
    assert (plan['assessment_limit'], plan['solver_limit'], plan['model_calls_max']) == (8, 128, 0)
    assert [(j['job_id'], j['task_id'], j['backend']) for j in plan['jobs']] == [
        (f'J{i:02}', f'GP5_SYNTH_K{1 + i // 2:02}', ('e2_original_v1', 'ems_surface_hybrid_v1')[i % 2])
        for i in range(4)
    ]
    assert digest(plan) == EXPECTED_PLAN_DIGEST
    assert digest(snap) == EXPECTED_MONITOR_DIGEST

    launch = read(launch_path)
    assert type(launch) is dict and 'authorization' in launch and 'review' in launch, 'LAUNCH_REFERENCES_MISSING'
    expected_auth = req['authorization_reference'] if authorization_path is None else authorization_path
    bind_external_reference(launch['authorization'], expected_auth, label='AUTHORIZATION')
    bind_external_reference(launch['review'], review_path, label='REVIEW')

    p.validate_admission(plan, snap, launch)
    # Initial zero-ledger barrier before joint config preflight or any dispatch.
    initial_ledger = check_initial_zero_ledger(plan)
    # Joint read-only preflight: absolutely no dispatch until all four succeed.
    configs = [order.load_order_config(plan, j['job_id'], monitor_snapshot=snap, admission=launch) for j in plan['jobs']]
    tasks = {}
    for case, t in zip(('K01', 'K02'), plan['tasks'], strict=True):
        tasks[t['task_id']] = p.adapt_task(
            (runtime / f'{case}_task.json').read_bytes(),
            origin=t['origin'],
            expected_sha256=t['raw_sha256'],
        )
        assert tasks[t['task_id']]['identity'] == t
    return plan, snap, launch, tasks, configs, initial_ledger


def inspect_in_run_phase_snapshot(job_root, job_id, phase, cp):
    """Inspect durable state during a single primary run at phase callback/hook."""
    job_dir = Path(job_root) / 'jobs' / job_id
    acc_path = job_dir / 'accounting.json'
    acc = read(acc_path) if acc_path.exists() else None
    inv_status = acc['invocations'][-1]['status'] if acc and acc.get('invocations') else None
    return {
        'job_id': job_id,
        'phase': phase,
        'checkpoint_phase': cp['phase'],
        'checkpoint_digest': digest(cp),
        'accounting_last_status': inv_status,
        'resumable_without_mutation': inv_status != 'STARTED',
        'blocker_code_if_resumed_as_is': (
            'geometry_accounting_unknown_dispatch' if inv_status == 'STARTED' else None
        ),
    }


def execute(runtime, review, launch, dest, *, authorization=None):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=False)
    rows = [
        {'kind': 'primary', 'job_id': f'J{i:02}', 'status': 'NOT_RUN'} for i in range(4)
    ] + [
        {'kind': 'recovery', 'job_id': j, 'phase': ph, 'status': 'NOT_RUN'}
        for j in ('J00', 'J01')
        for ph in PHASES
    ]
    receipt = {
        'evidence': 'REAL_EXECUTION_REQUEST',
        'rows': rows,
        'model_calls': 0,
        'primary_dispatches': 0,
        'recovery_dispatches': 0,
        'status': 'PREFLIGHT',
        'stop': None,
    }

    def save():
        write(dest / 'driver_receipt.json', receipt)

    save()
    try:
        plan, snap, adm, tasks, _, ledger_state = prepare(
            runtime, review, launch, authorization_path=authorization
        )
        receipt['joint_preflight'] = '4/4 PASS'
        receipt['plan_digest'] = digest(plan)
        receipt['initial_ledger_counts'] = copy.deepcopy(ledger_state['counts'])
        save()
        coverage = required_coverage(plan)

        def success(root, job):
            record = read(Path(root) / 'jobs' / job['job_id'] / 'record.json')
            check_success(record, next(r for r in coverage['primary'] if r['job_id'] == job['job_id']))

        # GP5-P2-DRIVER-DISPATCH-01: exactly 4 primary dispatches (no exception cut+resume loop).
        captured_phases = {'J00': {}, 'J01': {}}
        for row, job in zip(rows[:4], plan['jobs'], strict=True):
            jid = job['job_id']
            row['status'] = 'RUNNING'
            save()
            expected_assessments = 1 if job['task_id'] == 'GP5_SYNTH_K01' else 2

            def on_cp(cp, _jid=jid):
                if _jid in captured_phases and cp.get('phase') in PHASES:
                    phase = cp['phase']
                    target = dest / 'saved' / _jid / phase
                    if not target.exists():
                        shutil.copytree(dest / 'primary', target)
                        write(target / 'saved_checkpoint.json', copy.deepcopy(cp))
                        obs = inspect_in_run_phase_snapshot(target, _jid, phase, cp)
                        write(target / 'phase_observation.json', obs)
                        write(dest / f'{_jid}_{phase}_files.json', hashes(target))
                        captured_phases[_jid][phase] = obs

            receipt['primary_dispatches'] += 1
            result = order.run_order_job(
                plan,
                jid,
                tasks[job['task_id']],
                monitor_snapshot=snap,
                admission=adm,
                root=dest / 'primary',
                resume=None,
                on_checkpoint=on_cp,
            )
            assert result['summary']['completed'], 'UNEXPECTED_PRIMARY_STOP'
            success(dest / 'primary', job)
            ledger_state, delta = check_counts(
                plan,
                previous=ledger_state,
                job_id=jid,
                expected_assessment_delta=expected_assessments,
                require_solver_delta=True,
            )
            row.update(
                status='COMPLETE',
                counts=copy.deepcopy(ledger_state['counts']),
                ledger_delta=delta,
            )
            save()

        # Verify whether the 6 saved snapshots from the 4 single primary dispatches are directly resumable
        # without post-hoc mutation of accounting.json or extra primary cut-and-resume calls.
        for row in rows[4:]:
            jid = row['job_id']
            phase = row['phase']
            saved = dest / 'saved' / jid / phase
            assert saved.exists(), f'MISSING_SAVED_PHASE:{jid}:{phase}'
            assert hashes(saved) == read(dest / f'{jid}_{phase}_files.json'), 'SAVED_DURABLE_DRIFT'
            obs = read(saved / 'phase_observation.json')
            if not obs['resumable_without_mutation']:
                raise RuntimeError(
                    f'GP5_P2_DISPATCH_SNAPSHOT_BLOCKER:{jid}:{phase}:{obs["blocker_code_if_resumed_as_is"]}'
                )

            root = dest / 'recovery' / jid / phase
            shutil.copytree(saved, root)
            cp = read(root / 'saved_checkpoint.json')
            before = copy.deepcopy(ledger_state['counts'])
            row['status'] = 'RUNNING'
            save()
            job = next(j for j in plan['jobs'] if j['job_id'] == jid)
            receipt['recovery_dispatches'] += 1
            with ExitStack() as guards:
                for target in (
                    'candidate_backends.build_geometry_bundle',
                    'geometry_native_shape_bridge.publish_native_shape_pool_v3',
                    'packaging_runtime.LocalPackagingDouble.select',
                ):
                    guards.enter_context(
                        patch(
                            'semantic_pallet_planner.jev_select.' + target,
                            side_effect=RuntimeError('RECOVERY_FORBIDDEN:' + target),
                        )
                    )
                result = order.run_order_job(
                    plan,
                    jid,
                    tasks[job['task_id']],
                    monitor_snapshot=snap,
                    admission=adm,
                    root=root,
                    resume=cp,
                )
            expected_delta = int(phase == 'SELECTED')
            ledger_state, ledger_delta = check_counts(
                plan,
                previous=ledger_state,
                job_id=jid,
                expected_assessment_delta=expected_delta,
                require_solver_delta=(expected_delta > 0),
            )
            after = copy.deepcopy(ledger_state['counts'])
            delta = result['summary']['accounting']['invocation_delta']
            success(root, job)
            event = result['checkpoint']['events'][-1]
            pending = cp['pending_event']
            assert event['selection'] == pending['selection'] and event['proposed_action'] == pending['proposed_action']
            if phase != 'SELECTED':
                assert event['monitor']['result_digest'] == pending['monitor']['result_digest']
            assert result['summary']['completed'], 'UNEXPECTED_RECOVERY_STOP'
            assert delta['selector_calls'] == delta['singleton_executions'] == 0
            assert delta['commit_attempts'] == delta['commit_successes']
            assert (delta['monitor_entries'], delta['commit_successes']) == (
                int(phase == 'SELECTED'),
                int(phase != 'COMMITTED'),
            )
            assert delta['monitor_reuses'] == int(phase == 'MONITORED')
            row.update(
                status='COMPLETE',
                before=before,
                after=after,
                ledger_delta=ledger_delta,
                accounting=delta,
            )
            save()

        receipt['final_counts'] = verify_final_ledger_coverage(plan, coverage)
        receipt['status'] = 'COMPLETE'
    except BaseException as exc:
        receipt.update(status='STOPPED', stop={'type': type(exc).__name__, 'reason': str(exc)})
        for row in rows:
            if row['status'] == 'RUNNING':
                row['status'] = 'FAILED'
        raise
    finally:
        save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--review', required=True)
    parser.add_argument('--launch', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--authorization', default=None)
    args = parser.parse_args()
    execute(R, args.review, args.launch, args.output, authorization=args.authorization)

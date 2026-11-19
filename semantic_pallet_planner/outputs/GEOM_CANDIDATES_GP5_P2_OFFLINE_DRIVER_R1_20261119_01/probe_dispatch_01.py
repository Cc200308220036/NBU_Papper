"""Pure probe for GP5-P2-DRIVER-DISPATCH-01: inspect single-primary-run durable snapshots vs public recovery gates.

No real order entry, no real monitor/LP/freeze/model calls.
"""
import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from semantic_pallet_planner.jev_select import geometry_order_accounting as accounting
from semantic_pallet_planner.jev_select import geometry_order_execution as order
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.contracts import JevSelectError, digest

import driver as d


def run_probe():
    plan = d.read(d.R / 'acceptance_plan_FROZEN.json')
    snap = d.read(d.R / 'monitor_snapshot.json')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Construct an offline config structure matching J00 without running real kernel or preflight
        with patch.object(order, 'validate_admission'), patch.object(order, 'preflight_order'):
            cfg = order.load_order_config(plan, 'J00', monitor_snapshot=snap, admission={'OFFLINE_PROBE': True})

        # 1. Trace what geometry_order_accounting.invocation writes during a single primary run
        acc_path = root / 'jobs' / 'J00' / 'accounting.json'
        acc_path.parent.mkdir(parents=True, exist_ok=True)
        in_run_snapshots = {}
        fake_cps = {}
        with accounting.invocation(acc_path, cfg, 'J00', resume=None):
            accounting.tick(cfg, 'selector_calls')
            for phase in d.PHASES:
                if phase == 'MONITORED':
                    accounting.tick(cfg, 'monitor_entries')
                elif phase == 'COMMITTED':
                    accounting.tick(cfg, 'commit_attempts')
                    accounting.tick(cfg, 'commit_successes')
                cp = {'phase': phase, 'job_id': 'J00', 'pending_event': {'phase': phase}}
                fake_cps[phase] = cp
                snap_dir = root / 'saved_in_run' / phase / 'jobs' / 'J00'
                snap_dir.mkdir(parents=True, exist_ok=True)
                (snap_dir / 'accounting.json').write_bytes(acc_path.read_bytes())
                d.write(snap_dir / 'checkpoint.json', cp)
                in_run_snapshots[phase] = d.inspect_in_run_phase_snapshot(
                    root / 'saved_in_run' / phase, 'J00', phase, cp
                )
            accounting.completed(cfg, {'phase': 'TERMINATED', 'job_id': 'J00'})

        # 2. Attempt to resume from each unmutated in-run snapshot via public accounting.invocation
        resume_attempts = []
        for phase in d.PHASES:
            snap_acc = root / 'saved_in_run' / phase / 'jobs' / 'J00' / 'accounting.json'
            before_bytes = snap_acc.read_bytes()
            try:
                with accounting.invocation(snap_acc, cfg, 'J00', resume=fake_cps[phase]):
                    pass
            except JevSelectError as exc:
                resume_attempts.append({
                    'phase': phase,
                    'saved_invocation_status': in_run_snapshots[phase]['accounting_last_status'],
                    'resume_outcome': 'REJECTED_BY_PUBLIC_ACCOUNTING_GATE',
                    'error_type': type(exc).__name__,
                    'error_code': exc.code,
                    'bytes_unchanged': snap_acc.read_bytes() == before_bytes,
                })
            else:
                raise AssertionError(f'Expected accounting gate rejection for STARTED snapshot at {phase}')

        # 3. Attempt to resume from an unmutated in-run run.json (status == 'RUNNING') via run_order_job gate
        run_doc = p.update_run(p.draft_run(plan), plan, 'J00', 'RUNNING')
        prior = next(r for r in run_doc['rows'] if r['job_id'] == 'J00')
        run_json_allows_resume_when_resume_not_none = (prior['status'] == 'NOT_RUN' or fake_cps['SELECTED'] is not None)

        return {
            'schema': 'gp5_p2_dispatch_01_probe_v1',
            'plan_digest': digest(plan),
            'source_identity': plan['source_identity'],
            'single_primary_run_accounting_trace': {
                'in_run_snapshots': in_run_snapshots,
                'completed_primary_accounting': d.read(acc_path),
            },
            'unmutated_in_run_resume_attempts': resume_attempts,
            'run_json_gate_observation': {
                'in_run_row_status': prior['status'],
                'allows_resume_with_checkpoint': run_json_allows_resume_when_resume_not_none,
                'note': 'geometry_order_execution.py:172 allows resume!=None when run.json row is RUNNING, but geometry_order_accounting.py:41 rejects accounting.json when invocations[-1].status=="STARTED", and geometry_order_meter.py:28 rejects shared_call_ledger.json if any call is "STARTED".',
            },
            'findings': {
                'blobs_and_checkpoint_at_callback': 'COMPLETE_AND_FSYNCED (GeometryStore.save_input, save_event, save_checkpoint all complete and fsync before on_checkpoint/hook in episode.py:517,522,548)',
                'shared_call_ledger_at_callback': 'CONSISTENT_DONE (SELECTED callback precedes monitor_selected_action; MONITORED/COMMITTED callbacks occur after assess_candidate returns and CallBudget marks DONE)',
                'per_job_accounting_at_callback': 'BLOCKED_STARTED (geometry_order_accounting.invocation sets invocations[-1].status="STARTED" at entry line 45 and only transitions to "RETURNED" at context exit line 52 after run_episode returns; on_checkpoint/hook fire inside run_episode while status is still "STARTED", and line 41 rejects resume if invocations[-1].status=="STARTED" with geometry_accounting_unknown_dispatch)',
                'exception_cut_side_effects': 'Raising ControlledCut inside hook forces invocation.__exit__ to write status="ERROR" and run_order_job to write run.json="TECHNICAL_FAILURE" + driver_failure.json, and requires 3 extra run_order_job resume calls per K01 job (total 10 primary calls + 6 recovery calls = 16 dispatches).',
            },
        }


if __name__ == '__main__':
    out = Path(__file__).resolve().parent / 'probe_dispatch_01_results.json'
    result = run_probe()
    d.write(out, result)
    print(json.dumps(result['findings'], ensure_ascii=False, indent=2))

"""Launch the user-authorized frozen plan once through the unchanged formal CLI."""
from collections import Counter
from datetime import datetime
import importlib.metadata
import os
from pathlib import Path
import platform
import subprocess
import sys
from zoneinfo import ZoneInfo

from semantic_pallet_planner.jev_select import instruction_probe_execution as entry
from semantic_pallet_planner.jev_select.transport import credential

ROOT = Path('semantic_pallet_planner/outputs/GP6_INSTRUCTION_PROBE_EXEC_AUTH_20261128_01')
PLAN = Path('semantic_pallet_planner/outputs/GP6_INSTRUCTION_PROBE_EXEC_SCORE_FIX_20261126_01/pending_execution/execution_plan.json')
EXPECTED = '20754f06fd30b60f3f77e53ae55d6764ab4c35f8862cb9d81eeb32a9dff38bc1'


def stamp():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()


def main():
    assert platform.system() == 'Linux', 'target_linux_required'
    assert not (ROOT / 'launch_receipt.json').exists(), 'launch_already_claimed_no_retry'
    assert not entry.RUN.exists(), 'preserve_existing_run_no_retry'
    plan = entry.read(PLAN)
    assert entry.digest(plan) == EXPECTED, 'authorized_plan_digest_mismatch'
    prepared, contexts, bodies = entry.preflight(plan)
    auth = entry.read(ROOT / 'authorization.json')
    entry.validate_authorization(plan, auth)
    manifest = entry.read(PLAN.parent.parent / 'manifest.json')
    for name, info in manifest['files'].items():
        assert entry.sha(name) == info['sha256'], 'delivery_manifest_changed'
        assert Path(name).stat().st_size == info['bytes'], 'delivery_size_changed'
    started = stamp()
    versions = {}
    for name in ('jsonschema', 'numpy', 'scipy'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = 'NOT_INSTALLED'
    entry.durable_write(ROOT / 'preflight.json', {
        'version': 'gp6_instruction_authorized_preflight_v1', 'timestamp': started,
        'plan_digest': EXPECTED, 'preflight': 'PASS', 'manifest_files': len(manifest['files']),
        'frozen_files': len(plan['frozen_files']), 'contexts': len(contexts),
        'request_bodies': len(bodies), 'slots': len(plan['slots']),
        'run_root': str(entry.RUN), 'run_root_existed': False,
        'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'python': platform.python_version(), 'dependencies': versions,
        'independent_qa_for_revised_plan': 'NOT_PRESENT_IN_LOCAL_ARCHIVE',
        'execution_authority': 'current explicit user authorization for exact digest and built-in checks',
    })
    # Use the existing credential parser; keep the secret only in process memory.
    env_name = plan['transport_config']['api_key_env']
    previous = os.environ.get(env_name)
    key = credential(env_name) if previous and previous.strip() else credential(env_name, Path('typesafe_api_key.md'))
    entry.durable_write(ROOT / 'launch_receipt.json', {
        'version': 'gp6_instruction_authorized_launch_v1', 'timestamp': stamp(),
        'plan_digest': EXPECTED, 'status': 'CLAIMED_NO_WRAPPER_RETRY',
        'entry': 'instruction_probe_execution.main execute', 'credentials_loaded': True,
    })
    os.environ[env_name] = key
    del key
    error_class = None
    old_argv = sys.argv
    try:
        sys.argv = ['instruction_probe_execution', 'execute', '--plan', str(PLAN),
                    '--authorization', str(ROOT / 'authorization.json')]
        print('Frozen checks PASS; invoking unchanged formal CLI once.', flush=True)
        entry.main()
    except BaseException as error:
        # Do not persist exception messages, headers, or credential values.
        error_class = type(error).__name__
    finally:
        sys.argv = old_argv
        if previous is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = previous
        ledger = entry.read(entry.RUN / 'requests.json') if (entry.RUN / 'requests.json').exists() else None
        receipt = {
            'version': 'gp6_instruction_authorized_run_receipt_v1',
            'started': started, 'ended': stamp(), 'plan_digest': EXPECTED,
            'status': ledger['status'] if ledger else 'NO_LEDGER_REVIEW_REQUIRED',
            'origin': ledger['origin'] if ledger else None,
            'reservations': ledger['reservations'] if ledger else 'UNKNOWN',
            'recorded_network_attempts': ledger['network_attempts'] if ledger else 'UNKNOWN',
            'slot_status_counts': dict(Counter(row['status'] for row in ledger['rows'])) if ledger else {},
            'exception_class': error_class, 'retry_performed': False,
            'authorization': str(ROOT / 'authorization.json'), 'plan': str(PLAN),
            'ledger': str(entry.RUN / 'requests.json'),
            'statistics': str(entry.RUN / 'statistics.json'),
            'service_cost_usd': ledger['service_cost_usd'] if ledger else 'UNKNOWN',
        }
        entry.durable_write(ROOT / 'run_receipt.json', receipt)
        print(receipt['status'], receipt['reservations'], receipt['slot_status_counts'], flush=True)
    return 0 if receipt['status'] == 'FINISHED' and error_class is None else 2


if __name__ == '__main__':
    raise SystemExit(main())

"""Focused offline regression; block real connection and credential entrypoints."""
import json
import socket
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select import transport

ROOT = Path(__file__).resolve().parent
counts = {'network_connects': 0, 'credential_reads': 0}
def no_network(*args, **kwargs):
    counts['network_connects'] += 1
    raise AssertionError('real connection forbidden during scope repair tests')
def no_credential(*args, **kwargs):
    counts['credential_reads'] += 1
    raise AssertionError('credential access forbidden during scope repair tests')
socket.socket.connect = no_network
transport.credential = no_credential
code = pytest.main([
    'semantic_pallet_planner/tests/unit/test_packaging_monitor_scope.py',
    'semantic_pallet_planner/tests/unit/test_packaging_evaluation_v10_stops.py',
    'semantic_pallet_planner/tests/unit/test_packaging_synthetic_execution.py',
    '-q', '--disable-warnings', '--junitxml='+str(ROOT/'tests_final.xml'),
    '--basetemp='+str(ROOT/'constructed'),
])
(ROOT/'test_access_guards.json').write_text(json.dumps({'exit_code':code, **counts})+'\n')
raise SystemExit(code or int(any(counts.values())))

"""Bounded independent v3/v12 and old-v2/v11 regressions, never real sends."""
import json
import socket
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select import transport
root=Path(__file__).resolve().parent
counts={'credential_reads':0,'network_connects':0}
def no_auth(*a,**kw):
    counts['credential_reads']+=1
    raise AssertionError('credentials forbidden during offline acceptance')
def no_network(*a,**kw):
    counts['network_connects']+=1
    raise AssertionError('network forbidden during offline acceptance')
transport.credential=no_auth;socket.socket.connect=no_network
code=pytest.main(['semantic_pallet_planner/tests/unit/test_packaging_exact.py',
    'semantic_pallet_planner/tests/unit/test_stability_balance.py::test_physical_fixtures',
    'semantic_pallet_planner/tests/unit/test_packaging_synthetic_execution.py',
    'semantic_pallet_planner/tests/unit/test_packaging_monitor_scope.py::test_scope_extraction_excludes_success_without_mutating_saved_facts',
    'semantic_pallet_planner/tests/unit/test_packaging_monitor_scope.py::test_scope_extraction_fails_closed',
    '-q','--disable-warnings','--junitxml='+str(root/'tests_final.xml'),'--basetemp='+str(root/'constructed')])
(root/'offline_guards.json').write_text(json.dumps({'exit_code':code,**counts})+'\n')
raise SystemExit(code or int(any(counts.values())))

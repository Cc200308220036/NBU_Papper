"""P1 authorized synthetic/regression tests; actual freezer/assess/solver/network all guarded."""
import copy,json,sys,unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
import socket

sys.path.insert(0,'semantic_pallet_planner/tests/unit')
snapshot=json.loads(Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N3_20261117_01/cases/ems_surface_hybrid_v1_stable/config.json').read_bytes())['stability_monitor']
from semantic_pallet_planner.jev_select.stability import monitor,exact_adapter,balance_adapter,balance_network
from semantic_pallet_planner.jev_select import transport
with ExitStack() as stack:
 def forbidden(*a,**kw):raise AssertionError('ACTUAL_FREEZE_ASSESS_SOLVER_NETWORK_FORBIDDEN')
 for obj,name in [(exact_adapter,'assess_candidate'),(balance_adapter,'assess_candidate'),(balance_network,'solve_network'),(balance_network,'linprog'),(socket.socket,'connect'),(transport,'credential')]:stack.enter_context(patch.object(obj,name,side_effect=forbidden))
 # Old v15 configuration regression consumes a saved identity as an explicit
 # test-layer metadata double; no actual freezer or algorithm identity is called.
 stack.enter_context(patch.object(monitor,'exact_freeze',side_effect=lambda:copy.deepcopy(snapshot)))
 stack.enter_context(patch.object(monitor,'freeze',side_effect=lambda enabled=False:copy.deepcopy(snapshot) if enabled else dict(enabled=False,algorithm=None,kernel_config=None,algorithm_identity=None,execution_environment=None)))
 stack.enter_context(patch.object(exact_adapter,'algorithm_identity',side_effect=lambda:copy.deepcopy(snapshot['algorithm_identity'])))
 suite=unittest.TestSuite()
 for module in ('test_geometry_execution_n3','test_geometry_recovery_r1','test_geometry_binding_r1'):
  suite.addTests(unittest.defaultTestLoader.loadTestsFromName(module))
 result=unittest.TextTestRunner(verbosity=2).run(suite)
 print('REAL_KERNEL=0 LP=0 ACTUAL_FREEZE=0 NETWORK=0 REAL_SOURCE_ORDERS=0')
 sys.exit(not result.wasSuccessful())

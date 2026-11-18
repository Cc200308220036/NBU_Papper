"""Run only original R5 isolation/exact-rejection tests against byte-identical helpers."""
import importlib.util,unittest
from pathlib import Path
if __name__=='__main__':
    old=Path(__file__).resolve().parent.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R5_20261118_01/test_r5_pure.py'
    spec=importlib.util.spec_from_file_location('r5_guard_tests_readonly',old);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (module.Isolation,module.Negatives))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)

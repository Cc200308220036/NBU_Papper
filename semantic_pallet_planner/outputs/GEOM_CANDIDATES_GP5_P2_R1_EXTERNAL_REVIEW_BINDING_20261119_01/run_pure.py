"""Run explicit pure review tests only, with temporary fixtures and no dispatch."""
import json,unittest
from pathlib import Path
import test_geometry_external_review_identity_r1 as t
O=Path(__file__).resolve().parent
result=unittest.TextTestRunner(verbosity=2,failfast=True).run(unittest.defaultTestLoader.loadTestsFromTestCase(t.ReviewIdentity))
(O/'pure_results.json').write_text(json.dumps({'methods':result.testsRun,'success':result.wasSuccessful(),'failures':[(str(x),s) for x,s in result.failures],'errors':[(str(x),s) for x,s in result.errors],'receipts':t.RECEIPTS,'fixture_kind':'TEMPORARY_SYNTHETIC_BINDING_AND_COVERAGE_ONLY','genuine_completion_validation':'NOT_RUN','effective_authorizations_launches_completion_receipts_issued':0,'real_assessments':0,'LP':0,'orders':0,'resumes':0,'freeze':0,'models':0},ensure_ascii=False,indent=2)+'\n')
raise SystemExit(not result.wasSuccessful())

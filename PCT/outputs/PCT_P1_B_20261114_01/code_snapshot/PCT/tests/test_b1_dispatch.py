"""B12 lazy loader tests without importing dependency-heavy public contracts."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from pct_baseline.protocol import schema_name, validate_value
from pct_baseline.contracts import digest

ROOT=Path(__file__).resolve().parents[2]


def registry():
    spec=importlib.util.spec_from_file_location('tested_packaging_versions',ROOT/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_versions.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class DispatchTests(unittest.TestCase):
    def test_exact_names_and_fake_suffixes(self):
        m=registry()
        for value in ['jev_packaging_choice_v4','forged_b1_v1','pct_b1_config_v1_v13']:
            self.assertIsNone(m.resolve_extension(value))
        self.assertEqual(m.resolve_extension('pct_b1_config_v1').SUFFIX,'b1_v1')
        self.assertEqual(schema_name('config','pct_b1_config_v1'),'config_b1_v1')
        for name,version in [('config','fake_b1_v1'),('decision_context','pct_b1_config_v1'),('config_b1_v1','unknown')]:
            with self.assertRaisesRegex(ValueError,'MISMATCH'):schema_name(name,version)

    def test_absent_extension_does_not_affect_old_registry(self):
        m=registry()
        with patch('importlib.import_module',side_effect=ModuleNotFoundError('absent',name='pct_baseline')) as mocked:
            self.assertIsNone(m.resolve_extension('jev_packaging_choice_v4'));mocked.assert_not_called()
            with self.assertRaisesRegex(ModuleNotFoundError,'PCT_B1_EXTENSION_MISSING'):m.resolve_extension('pct_b1_config_v1')

    def test_missing_internal_dependency_keeps_actual_diagnostic(self):
        m=registry();error=ModuleNotFoundError('no such internal dependency',name='pct_internal_test_dependency')
        with patch('importlib.import_module',side_effect=error):
            with self.assertRaises(ModuleNotFoundError) as caught:m.resolve_extension('pct_b1_config_v1')
        self.assertIs(caught.exception,error)

    def test_unfiltered_and_filtered_pool_invariants(self):
        physical=[{'candidate_id':'original'}]
        value={'version':'jev_candidate_bundle_b1_v1','physical_candidates':physical,'selectable_candidates':[],
               'physical_digest':digest(physical),'selectable_digest':digest([]),'selectable_pool':'unfiltered','policy_digest':None}
        validate_value('candidate_bundle_b1_v1',value)
        value.update(selectable_pool='physical_feasible',policy_digest=digest('policy'))
        with self.assertRaisesRegex(ValueError,'PHYSICAL_POOL'):validate_value('candidate_bundle_b1_v1',value)
        value.update(selectable_candidates=physical,selectable_digest=digest(physical))
        validate_value('candidate_bundle_b1_v1',value)
        value.update(selectable_pool='unfiltered')
        with self.assertRaisesRegex(ValueError,'UNFILTERED'):validate_value('candidate_bundle_b1_v1',value)

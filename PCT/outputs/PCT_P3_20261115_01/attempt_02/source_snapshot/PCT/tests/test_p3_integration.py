"""P3 pre-dispatch tests: no candidate generation, LP or physical runs."""
import copy
from pathlib import Path
import unittest
import torch
from pct_baseline import dataset,p3_runtime as rt
from pct_baseline.contracts import digest,read,ContractError

class P3Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
        _,rows=dataset.authenticate(Path('.'))
        spec=dataset.execution_spec(Path('.'),'PCT/configs/data_b1_v1.json')
        cls.tasks=[dataset.derive(row,parent,identity,spec) for row,parent,identity in rows if row['task_id'] in rt.TASKS]
    def test_closed_config_exact_monitor_and_old_admission(self):
        from semantic_pallet_planner.jev_select.contracts import validate_schema
        from pct_baseline.execution import build_config as old_build
        task=self.tasks[0];c=rt.build_config(task,'geometry_b1',digest('preflight'))
        rt.preflight(c)
        wrong=copy.deepcopy(c);wrong['stability_monitor']['enabled']=False
        with self.assertRaises(ValueError):rt.preflight(wrong)
        wrong=copy.deepcopy(c);wrong['unexpected']=True
        with self.assertRaises(ValueError):validate_schema('config',wrong)
        with self.assertRaises(ValueError):old_build(task)
        self.assertEqual(sum(len(t['items']) for t in self.tasks),33)
    def test_model_identity_and_admission_required(self):
        b=rt.model_binding('PCT/outputs/PCT_P2_C_20261115_01/attempt_03/tests/model_manifest.json',
                           'PCT/outputs/PCT_P2_C_20261115_01/attempt_03/tests/weight_tensors.json')
        model=rt.load_bound(b);model.check_identity()
        c=rt.build_config(self.tasks[0],'pct_load_b1',digest('preflight'),digest(b));rt.preflight(c)
        with self.assertRaises(ValueError):
            rt.admit_execution(self.tasks[0],None,c,execution=None,job_id='invalid',method='pct_load_b1',resume=None,
                on_checkpoint=None,expected_events=None,training_fork=None,memory_snapshot=None,memory_view=None,memory_driver=None)
        c['model_identity']=None
        with self.assertRaises(ValueError):rt.preflight(c)

if __name__=='__main__':unittest.main()

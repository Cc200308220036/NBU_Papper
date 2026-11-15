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
    def test_real_singleton_value_forward_only(self):
        import tempfile
        from pathlib import Path
        from pct_baseline.contracts import digest
        fixture=read('PCT/outputs/PCT_P2_C_20261115_01/attempt_03/tests/route_1.json')
        b=rt.model_binding('PCT/outputs/PCT_P2_C_20261115_01/attempt_03/tests/model_manifest.json',
                           'PCT/outputs/PCT_P2_C_20261115_01/attempt_03/tests/weight_tensors.json')
        model=rt.load_bound(b)
        config=copy.deepcopy(fixture['config'])
        config.update(version='pct_p3_config_v1',selector='pct_load_b1',p3_mode='training',
                      p3_plan_digest=digest('singleton_fixture_precheck'),model_identity=digest(b))
        context=copy.deepcopy(fixture['context']);context['local_binding']['config_digest']=digest(config)
        counters={'policy_choice_forwards':0,'singleton_critic_forwards':0,'selection_record_reuses':0}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'records').mkdir()
            selector=rt.ModelSelector(config,model,root,counters)
            selector.bind({'context':context,'bundle':{'selectable_candidates':fixture['candidates']},
                           'decision_id':context['local_binding']['decision_id']})
            record=read(next((root/'records').glob('*.json')))
            self.assertEqual(record['selection']['status'],'singleton')
            self.assertTrue(torch.isfinite(torch.tensor(record['output']['value'])))
        self.assertEqual(counters['singleton_critic_forwards'],1)
        self.assertEqual(counters['policy_choice_forwards'],0)
        self.assertEqual(model.calls,0)

    def test_sink_observer_hits_actual_persisted_stages(self):
        from pct_baseline.persistence import JournalSink,JobLock
        import tempfile
        from pathlib import Path
        for phase in ('DECISION_READY','SELECTED','MONITORED','COMMITTED'):
            counts={'candidate_generations':0,'candidate_actions':0,'monitor_calls':0,'commits':0}
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);(root/'journal').mkdir()
                with JobLock(root) as lock:
                    sink=JournalSink(root,{'synthetic':'observer_only'},[],lock,cut=rt.checkpoint_observer(counts,phase))
                    cp={'phase':phase,'pending_event':{'bundle':{'physical_candidates':[1,2]}}}
                    with self.assertRaises(rt.PlannedCut):sink(cp)
                    self.assertEqual(len(sink.rows),1)
                    self.assertTrue((root/'journal/00000000.json').exists())
            self.assertEqual(counts['monitor_calls'],int(phase=='MONITORED'))
            self.assertEqual(counts['commits'],int(phase=='COMMITTED'))
            self.assertEqual(counts['candidate_generations'],int(phase=='DECISION_READY'))

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

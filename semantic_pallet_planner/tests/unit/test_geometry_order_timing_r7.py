"""Pure summary arithmetic only. Never execute/resume an order or rebind history."""
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from semantic_pallet_planner.jev_select import geometry_order_execution as order
from semantic_pallet_planner.jev_select.packaging_runtime import summary

BASE=Path('semantic_pallet_planner/outputs')
OLD=BASE/'GEOM_CANDIDATES_GP5_NUM_N1_FIXED_SYNTHETIC_REVALIDATION_20261118_01'
P1=BASE/'GEOM_CANDIDATES_GP5_P1_R1_20261117_01/final_evidence/test_metrics_independent_arithmetic_and_complete_run_denominator'
EVIDENCE={}

def read(p):return json.loads(p.read_bytes())
def event(times):return {'decision_id':'PURE','timings':times}

class TimingSummary(unittest.TestCase):
    def setUp(self):
        self.guards=ExitStack();self.addCleanup(self.guards.close)
        for target in ('semantic_pallet_planner.jev_select.geometry_order_execution.run_order_job',
                       'semantic_pallet_planner.jev_select.episode.run_episode',
                       'semantic_pallet_planner.jev_select.candidates.CandidateProvider.build',
                       'semantic_pallet_planner.jev_select.execution.commit_physical'):
            self.guards.enter_context(patch(target,side_effect=AssertionError('BUSINESS_DISPATCH_FORBIDDEN')))
        self.guards.enter_context(patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')))

    def test_numeric_zero_null_missing_and_mixed(self):
        cases=[('numeric',[event({'a_s':1.25}),event({'a_s':2})],[{'segment':'a_s','seconds':3.25}]),
               ('zero',[event({'a_s':0}),event({'a_s':0.0})],[{'segment':'a_s','seconds':0.0}]),
               ('null',[event({'a_s':None})],[]),('missing',[event({})],[]),
               ('mixed',[event({'a_s':1.25}),event({'a_s':None})],[{'segment':'measured_partial/a_s','seconds':1.25}]),
               ('missing_one',[event({'a_s':1.25}),event({})],[{'segment':'measured_partial/a_s','seconds':1.25}]),
               ('zero_null',[event({'a_s':0.0}),event({'a_s':None})],[{'segment':'measured_partial/a_s','seconds':0.0}]),
               ('arrival_not_sample',[{'event':'ARRIVE','timings':{}},event({'a_s':2})],[{'segment':'a_s','seconds':2}])]
        results=[]
        for name,events,expected in cases:
            with self.subTest(name=name):
                original=copy.deepcopy(events);actual=order._order_timing_totals(events,[])
                self.assertEqual(actual,expected);self.assertEqual(events,original)
                results.append({'case':name,'input':events,'output':actual,'status':'PASS'})
        EVIDENCE['sample_cases']=results

    def test_monitor_duration_missing_null_zero(self):
        cases=[([],[]),([{}],[]),([{'result':{'duration_s':None}}],[]),
               ([{'result':{'duration_s':0}}],[{'segment':'monitor_result_duration_s','seconds':0}]),
               ([{'result':{'duration_s':1.5}},{}],[{'segment':'measured_partial/monitor_result_duration_s','seconds':1.5}])]
        for monitors,expected in cases:
            before=copy.deepcopy(monitors)
            self.assertEqual(order._order_timing_totals([],monitors),expected);self.assertEqual(monitors,before)
        EVIDENCE['monitor_duration_cases']=len(cases)

    def test_original_failed_event_data(self):
        path=OLD/'R_recovery/J01_COMMITTED/jobs/J01/checkpoint.json';before=path.read_bytes();cp=read(path)
        values=[e['timings']['decision_wall_s'] for e in cp['events'] if 'decision_wall_s' in e.get('timings',{})]
        self.assertEqual(values,[7.323691413999768,None])
        with self.assertRaises(TypeError):sum(values)
        events=copy.deepcopy(cp['events']);monitors=[e['monitor'] for e in events if e.get('monitor')]
        totals=order._order_timing_totals(events,monitors);by_name={x['segment']:x['seconds'] for x in totals}
        self.assertNotIn('decision_wall_s',by_name)
        self.assertEqual(by_name['measured_partial/decision_wall_s'],values[0])
        self.assertEqual(events,cp['events']);self.assertEqual(path.read_bytes(),before)
        EVIDENCE['archived_failure']={'checkpoint':str(path),'sha256':hashlib.sha256(before).hexdigest(),'original_values':values,'new_totals':totals,'original_events_unchanged':True,'actual_resume':'NOT_RUN'}

    def test_v16_v17_shared_summary_schema_without_execution(self):
        cp=read(OLD/'R_recovery/J01_COMMITTED/jobs/J01/checkpoint.json')
        configs=[read(P1/'inputs/K02_J00/config.json'),read(OLD/'E/jobs/J01/config.json')]
        state=cp['state'];task={'task_id':'PURE_METRICS_ONLY','items':[{'dimensions_mm':dict(zip(('length','width','height'),o['oriented_size_mm'])),'mass_kg':o['mass_kg']} for o in state['placed_items']]}
        results=[]
        for cfg in configs:
            before=copy.deepcopy((task,cfg,state,cp['events']))
            metrics=summary(task,cfg,cfg['selector'],state,cp['events'],'ALL_ITEMS_PLACED')
            self.assertEqual((task,cfg,state,cp['events']),before)
            self.assertIn(metrics['version'],('geometry_order_metrics_v1','geometry_order_metrics_v2'))
            self.assertTrue(metrics['completed']);self.assertEqual(metrics['accounting']['status'],'UNKNOWN_UNINSTRUMENTED')
            self.assertEqual(next(x['seconds'] for x in metrics['timings'] if x['segment']=='measured_partial/decision_wall_s'),7.323691413999768)
            results.append({'config_version':cfg['version'],'metrics_schema':metrics['version'],'timings':metrics['timings'],'status':'PASS_PURE_SUMMARY_NOT_ORDER_ACCEPTANCE'})
        EVIDENCE['shared_entry']=results

    def test_existing_numeric_e_totals_unchanged(self):
        results=[]
        for jid in ('J00','J01','J02','J03','J04','J05','J06','J07'):
            events=read(OLD/f'E/jobs/{jid}/episode.json')['events'];before=copy.deepcopy(events)
            monitors=[e['monitor'] for e in events if e.get('monitor')]
            # run_order_job appends invocation_wall_s after order_metrics;
            # compare only the shared summary's own numeric rows here.
            expected=[r for r in read(OLD/f'E/jobs/{jid}/metrics.json')['timings']
                      if r['segment']!='invocation_wall_s']
            actual=order._order_timing_totals(events,monitors)
            self.assertEqual(actual,expected);self.assertEqual(events,before)
            results.append({'job_id':jid,'status':'PASS_EXISTING_NUMERIC_TIMINGS_EQUAL','rows':len(actual)})
        EVIDENCE['existing_numeric_e']=results

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TimingSummary))
    if os.environ.get('GP5_R7_EVIDENCE'):
        Path(os.environ['GP5_R7_EVIDENCE']).write_text(json.dumps({'status':'PASS' if result.wasSuccessful() else 'FAIL','tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'scope':'PURE_SUMMARY_ONLY','actual_order_and_resume':'NOT_RUN','evidence':EVIDENCE},ensure_ascii=False,indent=2)+'\n')
    raise SystemExit(not result.wasSuccessful())

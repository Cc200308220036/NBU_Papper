"""Pure positive/negative timing and provenance checks. No episodes."""
import copy,json,unittest
from pathlib import Path
from timing_assertions import assert_recovery_timing
from lineage import relative,verify_rows,read,member_bytes,sha
I=Path(__file__).resolve().parent
class PureChecks(unittest.TestCase):
 def test_mixed_partial_positive_and_negative(self):
    events=[{'decision_id':'a','timings':{'decision_wall_s':1.25,'selection_s':0}},{'decision_id':'b','timings':{'decision_wall_s':None,'selection_s':0}}]
    summary={'timings':[{'segment':'measured_partial/decision_wall_s','seconds':1.25},{'segment':'selection_s','seconds':0}]}
    original=copy.deepcopy(events);assert_recovery_timing(events,summary,phase='COMMITTED');self.assertEqual(events,original)
    for rows in ([{'segment':'decision_wall_s','seconds':1.25},{'segment':'selection_s','seconds':0}],[{'segment':'measured_partial/decision_wall_s','seconds':0},{'segment':'selection_s','seconds':0}],summary['timings']+[{'segment':'decision_wall_s','seconds':1.25}],summary['timings']+[summary['timings'][0]]):
        with self.assertRaises(AssertionError):assert_recovery_timing(events,{'timings':rows},phase='COMMITTED')
 def test_complete_zero_and_unmeasured(self):
    events=[{'decision_id':'a','timings':{'decision_wall_s':0,'not_measured_s':None}},{'decision_id':'b','timings':{'decision_wall_s':2,'not_measured_s':None}}]
    summary={'timings':[{'segment':'decision_wall_s','seconds':2}]}
    assert_recovery_timing(events,summary,phase='SELECTED')
    with self.assertRaises(AssertionError):assert_recovery_timing(events,summary,phase='COMMITTED')
    with self.assertRaises(AssertionError):assert_recovery_timing(events,{'timings':summary['timings']+[{'segment':'not_measured_s','seconds':0}]},phase='SELECTED')
 def test_production_aggregator_against_independent_expectation(self):
    from semantic_pallet_planner.jev_select.geometry_order_execution import _order_timing_totals
    events=[{'decision_id':'a','timings':{'decision_wall_s':0.5},'monitor':{'result':{'duration_s':0}}},{'decision_id':'b','timings':{'decision_wall_s':None},'monitor':{'result':{'duration_s':None}}}]
    summary={'timings':_order_timing_totals(events,[e['monitor'] for e in events])}
    assert_recovery_timing(events,summary,phase='COMMITTED')
 def test_paths_reject_escape_and_normalize_only_known_prefix(self):
    self.assertEqual(relative('/home/cyw/NBU_Papper/a/b'),'a/b')
    self.assertEqual(relative('a/b'),'a/b')
    for path in ('../a','/tmp/a','a/../../b'):
        with self.assertRaises(ValueError):relative(path)
 def test_namespaces_same_path_different_revision_and_drift(self):
    freeze=read(I/'frozen_identity.json');path='semantic_pallet_planner/src/semantic_pallet_planner/jev_select/geometry_order_execution.py'
    old=next(r for r in freeze['historical_members'] if r['path']==path and r['kind']=='git')
    current=next(r for r in freeze['current_members'] if r['path']==path)
    self.assertNotEqual(old['sha256'],current['sha256']);verify_rows([old,current])
    self.assertEqual(old['sha256'],'6a65e0457ab26a0df6f13eb44c8c7705dbd52062e0f8552406baa3008904cf3a')
    self.assertEqual(current['sha256'],'c2d7d83709cd484dcf3673a7db6ac28ebdeda9bb17309add34798d12b41965d7')
    for row in (old,current):
        bad=copy.deepcopy(row);bad['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'LINEAGE_MEMBER_DRIFT'):verify_rows([bad])
    bad=copy.deepcopy(old);bad['revision']='HEAD'
    with self.assertRaisesRegex(ValueError,'UNPINNED_REVISION'):member_bytes(bad)
if __name__=='__main__':unittest.main(verbosity=2,failfast=True)

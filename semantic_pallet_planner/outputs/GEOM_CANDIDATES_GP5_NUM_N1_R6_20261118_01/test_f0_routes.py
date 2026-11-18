"""Pure saved-context/in-memory negative tests. No orders or request creation."""
import copy,json,unittest
from pathlib import Path
from f0_receipts import f0_receipt,compare_f0
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError
BASE=Path('semantic_pallet_planner/outputs')
J00=BASE/'GEOM_CANDIDATES_GP5_NUM_N1_R1_20261118_01/E/jobs/J00'
J01=BASE/'GEOM_CANDIDATES_GP5_NUM_N1_R2_20261118_01/continuation/jobs/J01'
def read(p):return json.loads(p.read_bytes())
def fixture(root=J00):return read(root/'episode.json'),read(root/'config.json')
def decision_events(ep):return [e for e in ep['events'] if e.get('context') is not None]
def bind_metadata_copy(ctx):
    # Only negative/null-stop metadata variants in memory; never write back,
    # publish, execute, or re-sign a historical checkpoint/config identity.
    for field,key in [('mapping_digest','display_mapping'),('model_state_digest','model_state'),('criteria_digest','criteria'),('request_body_digest','request_body')]:ctx['local_binding'][field]=digest(ctx[key])

class F0Routes(unittest.TestCase):
    def test_complete_saved_mixed_routes_and_null_preservation(self):
        for root in (J00,J01):
            ep,cfg=fixture(root);original=copy.deepcopy(ep);r=f0_receipt(ep,cfg)
            self.assertEqual([row['route'] for row in r['contexts']],['CHOICE_REQUIRED','SINGLETON_BYPASS'])
            self.assertEqual(r['context_count'],2);self.assertFalse(r['request_constructed']);self.assertEqual(r['contexts_dropped'],0)
            self.assertEqual(r['contexts'][1]['request_fields'],None);self.assertTrue(r['contexts'][1]['request_body_is_null'])
            self.assertEqual(r['contexts'][0]['shared_public_contract'],r['contexts'][1]['shared_public_contract'])
            self.assertEqual(ep,original)
    def test_wrong_choice_request_state_options_and_fields_rejected(self):
        ep,cfg=fixture();choice=decision_events(ep)[0]
        for label in ('null','state','criteria','unknown_request_field','unknown_public_field','mapping'):
            ev=copy.deepcopy(choice);ctx=ev['context']
            if label=='null':ctx['request_body']=None
            elif label=='state':ctx['request_body']['state']['objective']='WRONG_PUBLIC_STATE'
            elif label=='criteria':ctx['request_body']['questions']['next_action']['criteria']={}
            elif label=='unknown_request_field':ctx['request_body']['UNRECOGNIZED']=True
            elif label=='unknown_public_field':ctx['model_state']['UNRECOGNIZED']=True
            else:ctx['display_mapping']['C01']['candidate_digest']='0'*64
            bind_metadata_copy(ctx)
            with self.subTest(label=label),self.assertRaises((JevSelectError,AssertionError)):f0_receipt({'events':[ev]},cfg)
    def test_singleton_wrong_request_or_cardinality_rejected(self):
        ep,cfg=fixture();choice,single=decision_events(ep)
        bad=copy.deepcopy(single);bad['context']['request_body']=copy.deepcopy(choice['context']['request_body']);bind_metadata_copy(bad['context'])
        with self.assertRaises(JevSelectError):f0_receipt({'events':[bad]},cfg)
        bad=copy.deepcopy(choice);bad['context']['route']='SINGLETON_BYPASS';bad['context']['request_body']=None;bind_metadata_copy(bad['context'])
        with self.assertRaises(JevSelectError):f0_receipt({'events':[bad]},cfg)
    def test_no_candidate_null_and_empty_options_contract(self):
        ep,cfg=fixture();ev=copy.deepcopy(decision_events(ep)[1]);ctx=ev['context']
        ctx.update(route='STOP_NO_PHYSICAL_CANDIDATE',criteria={},display_mapping={},request_body=None);bind_metadata_copy(ctx)
        ev['bundle']['physical_candidates']=[];ev['bundle']['selectable_candidates']=[]
        r=f0_receipt({'events':[ev]},cfg);self.assertEqual(r['contexts'][0]['candidate_count'],0);self.assertIsNone(r['contexts'][0]['request_fields'])
        ctx['route']='SINGLETON_BYPASS'
        with self.assertRaises(JevSelectError):f0_receipt({'events':[ev]},cfg)
    def paired_metadata(self):
        ep,cfg=fixture();full=f0_receipt(ep,cfg);choice=f0_receipt({'events':[decision_events(ep)[0]]},cfg)
        receipts=[]
        for task in ('GP5_SYNTH_K02_INT','GP5_SYNTH_K02'):
            for method in ('local_geometry_test_double','local_first_test_double'):
                for backend,base in [('e2_original_v1',full),('ems_surface_hybrid_v1',choice)]:
                    row=copy.deepcopy(base);row.update(task_id=task,method=method,backend=backend,fixture='PURE_PAIR_MATCHER_METADATA_NOT_BACKEND_EXECUTION');receipts.append(row)
        return receipts
    def test_backend_distribution_can_differ(self):
        pairs=compare_f0(self.paired_metadata());self.assertEqual(len(pairs),4)
        for pair in pairs:
            a,b=pair['backend_evidence'];self.assertNotEqual(a['route_counts'],b['route_counts']);self.assertFalse(pair['equal_route_counts_or_presence_required'])
    def test_backend_field_or_route_contract_disagreement_rejected(self):
        rows=self.paired_metadata();rows[1]['contract']['criteria_fields'].append('WRONG_FIELD')
        with self.assertRaisesRegex(AssertionError,'F0_PUBLIC_FIELD_CONTRACT_DISAGREEMENT'):compare_f0(rows)
        rows=self.paired_metadata();rows[1]['route_contracts']['SINGLETON_BYPASS']['request_body']='OBJECT'
        with self.assertRaisesRegex(AssertionError,'F0_ROUTE_REQUEST_CONTRACT_DISAGREEMENT'):compare_f0(rows)
if __name__=='__main__':unittest.main()

"""Only test-layer metadata/temp IO; no fixed C suite or orders dispatched."""
import json,tempfile,unittest,hashlib,copy
from pathlib import Path
from run_state import RunState,read,write,file_hashes
from negative_contract import expect_rejection,snapshot_variant
I=Path(__file__).resolve().parent

class Isolation(unittest.TestCase):
    def archive_fixture(self,tmp):
        sealed=Path(tmp)/'sealed';sealed.mkdir();write(sealed/'call_accounting.json',{'original_zero_call':True});write(sealed/'scope.json',read(I/'validation_scope.json'))
        return sealed
    def original_members(self):return {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in read(I/'archive_member_identity.json')['files']}
    def test_simulated_all_success_preserves_every_original_member(self):
        originals=self.original_members()
        with tempfile.TemporaryDirectory() as tmp:
            sealed=self.archive_fixture(tmp);before=file_hashes(sealed);state=RunState(sealed,Path(tmp)/'new_run',read(I/'validation_scope.json'),authorization={'SIMULATION_ONLY':True})
            self.assertEqual(len(read(state.root/'case_results.json')['rows']),35)
            for row in state.rows:
                with state.case(row['id']) as evidence:
                    write(state.root/'literal_results'/row['id'].replace('/','_'),{'simulated':'NOT_BUSINESS_EXECUTION'})
                    evidence.append({'scope':'TEMP_IO_SIMULATION_ONLY'})
            state.verify_archives();self.assertEqual(file_hashes(sealed),before)
            result=read(state.root/'case_results.json');self.assertEqual(sum(r['status']=='PASS' for r in result['rows']),35);self.assertEqual(result['R_attempts'],6);self.assertEqual(result['R_passes'],6)
        self.assertEqual(self.original_members(),originals)
    def test_first_failure_preserves_error_counts_and_full_denominator(self):
        originals=self.original_members()
        with tempfile.TemporaryDirectory() as tmp:
            sealed=self.archive_fixture(tmp);before=file_hashes(sealed);state=RunState(sealed,Path(tmp)/'stopped_run',read(I/'validation_scope.json'),authorization={'SIMULATION_ONLY':True})
            initial=RuntimeError('SIMULATED_FIRST_FAILURE')
            with self.assertRaises(RuntimeError) as caught:
                with state.case('R/J01/SELECTED'):
                    write(state.root/'call_accounting.json',{'pure_simulated_dispatch_markers':[1,2],'actual_monitors':0});raise initial
            self.assertIs(caught.exception,initial)
            result=read(state.root/'case_results.json');self.assertEqual(result['R_attempts'],1);self.assertEqual(result['R_passes'],0)
            self.assertEqual(result['counts']['R']['failed'],1);self.assertEqual(sum(r['status']=='NOT_RUN' for r in result['rows']),34)
            self.assertEqual(read(state.root/'call_accounting.json')['pure_simulated_dispatch_markers'],[1,2])
            with self.assertRaisesRegex(RuntimeError,'FIRST_FAILURE_ALREADY_STOPPED'):
                with state.case('E/J00'):pass
            self.assertEqual(file_hashes(sealed),before)
        self.assertEqual(self.original_members(),originals)
    def test_output_overlap_and_existing_root_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            sealed=self.archive_fixture(tmp);scope=read(I/'validation_scope.json')
            with self.assertRaises(ValueError):RunState(sealed,sealed/'new',scope)
            with self.assertRaises(FileExistsError):RunState(sealed,sealed,scope)

class Negatives(unittest.TestCase):
    def test_expected_geometry_and_jev_exact_type_code(self):
        from semantic_pallet_planner.planner.space_candidates.contracts import GeometryError
        from semantic_pallet_planner.jev_select.contracts import JevSelectError
        for cls in (GeometryError,JevSelectError):
            def fail():raise cls('FIXED_EXPECTED','PURE_HELPER')
            receipt=expect_rejection('literal',fail,cls,'FIXED_EXPECTED')
            self.assertEqual(receipt['exception_type'],cls.__name__);self.assertEqual(receipt['code'],'FIXED_EXPECTED')
    def test_unexpected_type_or_code_preserves_original(self):
        from semantic_pallet_planner.planner.space_candidates.contracts import GeometryError
        from semantic_pallet_planner.jev_select.contracts import JevSelectError
        for original in (RuntimeError('UNRELATED'),JevSelectError('EXPECTED'),GeometryError('OTHER_CODE')):
            def fail():raise original
            with self.assertRaises(type(original)) as caught:expect_rejection('literal',fail,GeometryError,'EXPECTED')
            self.assertIs(caught.exception,original)
    def test_no_rejection_is_a_failure(self):
        from semantic_pallet_planner.planner.space_candidates.contracts import GeometryError
        with self.assertRaisesRegex(AssertionError,'EXPECTED_REJECTION_MISSING'):expect_rejection('literal',lambda:None,GeometryError,'EXPECTED')
    def test_saved_positive_baseline_and_one_leaf_mutations(self):
        from semantic_pallet_planner.planner.space_candidates.contracts import GeometryError
        from semantic_pallet_planner.jev_select.geometry_runtime_input import validate_runtime_views_v1
        root=I.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R1_20261118_01/E/jobs/J00'
        ep=read(root/'episode.json');ev=[e for e in ep['events'] if e.get('bundle')][-1]
        doc=read(root/'blobs'/ev['geometry_ref']['sha256']);a=doc['audit'];n=bytes.fromhex(a['native_bytes_hex']);g=bytes.fromhex(a['geometry_bytes_hex'])
        validate_runtime_views_v1(n,g)
        for kind,code in [('type','RUNTIME_INPUT_INVALID'),('sign','RUNTIME_SNAPSHOT_MISMATCH')]:
            changed,receipt=snapshot_variant(n,g,kind)
            self.assertEqual(len(receipt['only_changed_paths']),1)
            result=expect_rejection(kind,lambda:validate_runtime_views_v1(changed,g),GeometryError,code)
            self.assertEqual(result['code'],code)
        # Saved-byte helper checks, not a replay of J00 or one of the 15 X/H jobs.

class PublicContract(unittest.TestCase):
    def test_pair_contract_ignores_trajectory_values_and_requires_same_fields(self):
        from coverage_checks import compare_f0
        rows=[]
        for task in ('GP5_SYNTH_K02_INT','GP5_SYNTH_K02'):
            for method in ('local_geometry_test_double','local_first_test_double'):
                for index,backend in enumerate(('e2_original_v1','ems_surface_hybrid_v1')):
                    rows.append({'task_id':task,'method':method,'backend':backend,'contract':{'fields':['pose','features']},'contexts':[{'candidate_count':index+1,'value':'DIFFERENT_'+str(index)}]})
        self.assertEqual(len(compare_f0(rows)),4)
        bad=copy.deepcopy(rows);bad[1]['contract']['fields'].append('UNEXPECTED_DIAGNOSTIC')
        with self.assertRaisesRegex(AssertionError,'F0_PUBLIC_FIELD_CONTRACT_DISAGREEMENT'):compare_f0(bad)
if __name__=='__main__':unittest.main()

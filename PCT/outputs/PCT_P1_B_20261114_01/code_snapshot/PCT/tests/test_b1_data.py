"""B10: immutable real parents and drift rejection, stdlib only."""
import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from pct_baseline import dataset as d
from pct_baseline.contracts import read, digest, write_new

REPO=Path(__file__).resolve().parents[2]
SPEC=REPO/'PCT/configs/data_b1_v1.json'


class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parents,cls.rows=d.authenticate(REPO)
        cls.execution=read(SPEC)['execution_spec']

    def test_both_parents_all_physical_fields(self):
        self.assertEqual(len(self.rows),22)
        self.assertEqual(sum(len(parent['items']) for _,parent,_ in self.rows),428)
        self.assertEqual(len({i for _,_,i in self.rows}),2)
        for row,parent,identity in self.rows:
            derived=d.derive(row,parent,identity,self.execution)
            self.assertEqual(derived['container'],parent['container'])
            self.assertEqual(derived['arrival_order'],parent['arrival_order'])
            self.assertEqual(derived['candidate_limits'],parent['candidate_limits'])
            for original,item in zip(parent['items'],derived['items']):
                self.assertEqual({k:original[k] for k in d.FIELDS},{k:item[k] for k in d.FIELDS})
            self.assertEqual(derived['parent_task_sha256'],row['sha256'])
            self.assertEqual(derived['parent_task_digest'],digest(parent))
            self.assertEqual(derived['buffer_capacity'],1)

    def test_parent_identity_and_content_digest_drift(self):
        row,parent,identity=self.rows[0]
        with self.assertRaisesRegex(ValueError,'DATA_IDENTITY_DRIFT'):
            d.derive(row,parent,'0'*64,self.execution)
        modified=copy.deepcopy(parent);modified['items'][0]['mass_kg']+=1
        with self.assertRaisesRegex(ValueError,'TASK_IDENTITY_DRIFT'):
            d.derive(row,modified,identity,self.execution)

    def test_execution_extra_fields_and_capacity_drift(self):
        for mutation in ({'unexpected':True},{'buffer_capacity':3}):
            with tempfile.TemporaryDirectory() as temporary:
                spec=read(SPEC);spec['execution_spec'].update(mutation)
                path=Path(temporary)/'spec.json';write_new(path,spec)
                with self.assertRaisesRegex(ValueError,'EXECUTION_SPEC_DRIFT'):
                    d.prepare(REPO,path,Path(temporary)/'derived')

    def test_invalid_order_empty_duplicate_and_permutation(self):
        original=self.rows[0][1]
        for kind,code in [('empty','EMPTY_TASK'),('duplicate','DUPLICATE_ITEM'),('order','ARRIVAL_ORDER_MISMATCH')]:
            parent=copy.deepcopy(original)
            if kind=='empty':parent['items']=[]
            elif kind=='duplicate':parent['items'].append(copy.deepcopy(parent['items'][0]))
            else:parent['arrival_order']=parent['arrival_order'][::-1]
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,code):d.project(parent)

    def test_alias_physical_drift(self):
        parent=copy.deepcopy(self.rows[0][1]);parent['items'][0]['max_top_load_kg']+=1
        with self.assertRaisesRegex(ValueError,'PHYSICAL_FIELD_DRIFT'):d.project(parent)

    def test_prepare_validate_and_derived_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'derived'
            d.prepare(REPO,SPEC,output)
            self.assertEqual(d.validate_data(REPO,output)['status'],'PASS')
            with self.assertRaises(FileExistsError):d.prepare(REPO,SPEC,output)
            manifest=read(output/'dataset.json');entry=manifest['tasks'][0]
            task=read(output/entry['path']);task['items'][0]['mass_kg']+=1
            task['derived_task_digest']=digest({k:v for k,v in task.items() if k!='derived_task_digest'})
            (output/entry['path']).unlink();write_new(output/entry['path'],task)
            entry.update(sha256=d.sha(output/entry['path']),digest=digest(task))
            manifest['data_identity']=digest({k:v for k,v in manifest.items() if k!='data_identity'})
            (output/'dataset.json').unlink();write_new(output/'dataset.json',manifest)
            with self.assertRaisesRegex(ValueError,'PHYSICAL_FIELD_OR_DERIVATION_DRIFT'):d.validate_data(REPO,output)

    def test_parent_byte_and_manifest_drift_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo=Path(temporary)
            for root in (d.PACK,d.SYN,d.P0):shutil.copytree(REPO/root,repo/root)
            path=repo/self.rows[0][0]['path'];before=path.read_bytes();path.write_bytes(before+b'\n')
            with self.assertRaisesRegex(ValueError,'PARENT_INVENTORY_DRIFT'):d.authenticate(repo)
            path.write_bytes(before)
            path=repo/d.PACK/'manifest.json';path.write_bytes(path.read_bytes()+b'\n')
            with self.assertRaisesRegex(ValueError,'DATA_IDENTITY_DRIFT'):d.authenticate(repo)

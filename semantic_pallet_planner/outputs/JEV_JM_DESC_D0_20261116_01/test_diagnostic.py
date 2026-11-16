"""D0 synthetic bookkeeping tests, not research states or geometry generation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import diagnose as d


def action(cid,pick='p',x='0',z='0',yaw='0',size=None):
 return dict(candidate_id=cid,pick_item_id=pick,pose=dict(x_mm=x,y_mm='0',z_base_mm=z,yaw_deg=yaw),oriented_size_mm=size or ['1','1','1'])


def fixture():
 inp=dict(version='jev_jm_fs_input_v1',coordinate='bottom_center_x_right_y_back_z_up_v1',precision='SAVED_LEXEMES',
 state=dict(container=dict(length_mm='10',width_mm='10',max_height_mm='10'),buffer=[dict(item_id=k,size_mm=['1','1','1']) for k in ('p','q')],placed_objects=[]),
 pool=[action('a'),action('b',x='1')],descriptor_scope=dict(mode='FULL_POOL',contrast=None),provenance=dict(state_sha256='0'*64,pool_sha256='1'*64))
 rect=['0','1','0','1'];rows=[];desc=[]
 for cid in ('a','b'):
  key=cid*64
  rows.append(dict(candidate_id=cid,status='VALUE',fit_ids=['q'],members=[dict(item_id='q',orientations=[dict(yaw_deg=y,fits=True,witness=rect,descriptor_key=key) for y in (0,90)])]))
  desc.append(dict(key=key,height_mm='1',maximum_area_mm2='1',action_ids=[cid],maximal_rectangles=[rect]))
 v=copy.deepcopy(inp);v.pop('provenance')
 sem=dict(version='jev_jm_fs_result_v1',algorithm='jm_fs_floor_grid_neighbor_v1',input_sha256=d.sha(d.canonical(inp)),input_semantic_digest=d.digest(v),descriptor_scope=dict(mode='FULL_POOL',action_ids=['a','b'],contrast=None),budget=dict(q=1),status='VALUE',actions=rows,descriptors=desc,cost={})
 sem['budget_digest']=d.digest(sem['budget'])
 sem['scope_digest']=d.digest(dict(input=sem['input_semantic_digest'],scope=sem['descriptor_scope'],algorithm=sem['algorithm'],budget=sem['budget']))
 result=dict(semantic=sem);seal(result)
 return inp,result

def seal(r):
 sem=r['semantic'];sem['semantic_digest']=d.digest({k:v for k,v in sem.items() if k not in ('semantic_digest','input_sha256','cost')})

class DiagnosticTests(unittest.TestCase):
 def test_set_identity_empty_unknown(self):
  for a,b,w in [([],[],'NO_DIRECTION'),([],['q'],'B_STRICT_SUPERSET'),(['q'],[],'A_STRICT_SUPERSET'),(['q'],['twin'],'TRADEOFF'),(None,[],'UNKNOWN')]:self.assertEqual(d.relation(a,b),w)
  self.assertEqual(d.relation(['box1'],['box2']),'TRADEOFF')

 def test_all_categories_denominator_and_order(self):
  a=[action('a'),action('b',x='1'),action('c',yaw='90'),action('d',pick='q'),action('e',z='1'),action('f')]
  import itertools,collections
  pairs=[d.classify(x,y) for x,y in itertools.combinations(a,2)]
  self.assertEqual(collections.Counter(pairs),dict(OUT_OF_SCOPE_NONFLOOR=5,OUT_OF_SCOPE_CROSS_BOX=4,OUT_OF_SCOPE_YAW=3,DUPLICATE_EXACT_ACTION=1,ELIGIBLE_FS_PAIR=2))
  self.assertEqual(sum(collections.Counter(pairs).values()),15)
  self.assertEqual(d.classify(action('z',pick='q',z='1'),action('a')),'OUT_OF_SCOPE_NONFLOOR')
  self.assertEqual(d.classify(action('z',pick='q',yaw='90'),action('a')),'OUT_OF_SCOPE_CROSS_BOX')
  self.assertEqual(4*(48*47//2)+28*27//2,4890)

 def test_exact_height_dedup_area_and_no_fit_relabel(self):
  inp,result=fixture();sem=result['semantic']
  rows={r['candidate_id']:r for r in sem['actions']};desc={r['key']:r for r in sem['descriptors']}
  desc['b'*64]['maximum_area_mm2']='1.000000000000000000000000000000001'
  boxes={k:dict(size_mm=['1','1','1.000']) for k in ('q','twin')}
  for r in rows.values():r['members'].append(dict(r['members'][0],item_id='twin'))
  status,vector=d.area_vector('a','b',boxes,rows,desc)
  self.assertEqual(status,'EQUAL_FIT_AREA_DIFF');self.assertEqual(len(vector),1)
  self.assertEqual(d.num(vector[0]['delta_B_minus_A_mm2']),d.num('0.000000000000000000000000000000001'))
  self.assertEqual(d.relation(['q'],['q']),'NO_DIRECTION')
  for r in desc.values():r['maximum_area_mm2']='1'
  self.assertEqual(d.area_vector('a','b',boxes,rows,desc)[0],'EQUAL_FIT_AREA_EQUAL')

 def test_seals_members_bindings_and_tamper(self):
  inp,result=fixture();d.validate_saved(inp,result,d.sha(d.canonical(inp)))
  r=copy.deepcopy(result);r['semantic']['actions'][0]['fit_ids']=['p'];seal(r)
  with self.assertRaisesRegex(d.Invalid,'FIT_IDENTITY'):d.validate_saved(inp,r,d.sha(d.canonical(inp)))
  r=copy.deepcopy(result);r['semantic']['descriptor_scope']['action_ids']=['a'];seal(r)
  with self.assertRaises(d.Invalid):d.validate_saved(inp,r,d.sha(d.canonical(inp)))
  r=copy.deepcopy(result);r['semantic']['descriptors'][0]['action_ids']=['b'];seal(r)
  with self.assertRaises(d.Invalid):d.validate_saved(inp,r,d.sha(d.canonical(inp)))
  r=copy.deepcopy(result);r['semantic']['actions'][0]['fit_ids']=[]
  with self.assertRaisesRegex(d.Invalid,'SEMANTIC_SEAL'):d.validate_saved(inp,r,d.sha(d.canonical(inp)))

 def test_unknown_and_missing_not_false(self):
  inp,result=fixture();rows,desc=d.validate_saved(inp,result,d.sha(d.canonical(inp)))
  rows['a']['status']='UNKNOWN';rows['a']['fit_ids']=None
  pair=d.inventory(inp,rows,desc)[0]
  self.assertEqual(pair['fit_relation'],'UNKNOWN');self.assertIsNone(pair['A_fit_ids'])
  self.assertEqual(pair['area_status'],'NOT_APPLICABLE')
  rows['a']['status']='VALUE';rows['a']['fit_ids']=['q'];desc.pop('a'*64)
  self.assertEqual(d.inventory(inp,rows,desc)[0]['area_status'],'UNKNOWN')
  a=action('a');a['pose']['z_base_mm']=None
  self.assertEqual(d.classify(a,action('b')),'UNKNOWN')
  with self.assertRaises(d.Invalid):d.classify(action('a'),action('b',size=['2','1','1']))

 def test_permutations_canonical_inventory(self):
  inp,result=fixture();rows,desc=d.validate_saved(inp,result,d.sha(d.canonical(inp)))
  before=d.inventory(inp,rows,desc)
  inp['pool'].reverse();inp['state']['buffer'].reverse()
  self.assertEqual(before,d.inventory(inp,dict(reversed(list(rows.items()))),dict(reversed(list(desc.items())))))
  self.assertEqual(before[0]['A'],'a');self.assertEqual(before[0]['B'],'b')

 def test_numeric_and_read_allowlist_failure(self):
  for v in (True,0.5,'NaN','Infinity','1xx'):
   with self.assertRaises(d.Invalid):d.num(v)
  for s in ('1.000000000000000000000000000001','1e-50','-0.0001'):self.assertEqual(d.num(d.dec(d.num(s))),d.num(s))
  with self.assertRaises(d.Invalid):d.loads(b'{"a":1,"a":2}')
  reader=d.Reader(dict(files=[]))
  with self.assertRaisesRegex(d.Invalid,'READ_NOT_ALLOWLISTED'):reader.read('not-allowed.json')
  with tempfile.TemporaryDirectory() as folder:
   with patch.object(d,'ROOT',Path(folder)):
    reader=d.Reader(dict(files=[dict(path='absent.json',sha256='0'*64,bytes=1)]))
    with self.assertRaisesRegex(d.Invalid,'MISSING'):reader.read('absent.json')

if __name__=='__main__':unittest.main()

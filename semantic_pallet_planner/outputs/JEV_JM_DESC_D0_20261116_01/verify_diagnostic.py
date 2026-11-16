"""Read-only D0 audit of frozen identities, all pair slots and exact saved values.

Does not import the diagnostic implementation or any production module.
"""
from collections import Counter
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
import hashlib
import itertools
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
READS=[]
def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def read(p):
 b=p.read_bytes();READS.append(dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(b)));return b

def load(p):return json.loads(read(p),parse_float=Decimal)
def number(x):return Fraction(Decimal(x))
def at(v,p):
 for token in p.split('/')[1:]:v=v[int(token)] if isinstance(v,list) else v[token.replace('~1','/').replace('~0','~')]
 return v

def main():
 plan=load(OUT/'diagnostic_plan.json');manifest=load(OUT/'input_manifest.json')
 freeze=load(OUT/'freeze_receipt.json');start=load(OUT/'execution_receipt.json');end=load(OUT/'completion_receipt.json')
 assert (freeze['sequence'],start['sequence'],end['sequence'])==(1,2,3)
 assert datetime.fromisoformat(freeze['time_utc'])<=datetime.fromisoformat(start['time_utc'])<=datetime.fromisoformat(end['time_utc'])
 for n in ('diagnostic_plan.json','input_manifest.json'):assert sha(read(OUT/n))==freeze['files'][n]
 assert start['freeze_receipt_sha256']==end['freeze_receipt_sha256']==sha(read(OUT/'freeze_receipt.json'))
 assert end['execution_receipt_sha256']==sha(read(OUT/'execution_receipt.json'))
 assert end['summary_sha256']==sha(read(OUT/'diagnostic_summary.json'))
 assert freeze['freeze_reads_sha256']==sha(read(OUT/'freeze_reads.json'))
 expected={r['path']:r for r in manifest['files']}
 for path,r in expected.items():
  data=read(ROOT/path);assert sha(data)==r['sha256'] and len(data)==r['bytes'],path
 actual=load(OUT/'actual_reads.json')
 assert set(r['path'] for r in actual['payload_reads'])==set(expected)
 for r in actual['payload_reads']:assert r['sha256']==expected[r['path']]['sha256']
 assert actual['control_reads']['diagnostic_plan.json']==freeze['files']['diagnostic_plan.json']
 summary=load(OUT/'diagnostic_summary.json');totals=Counter();total=0;component_points={}
 for p,s in zip(plan['points'],summary['states']):
  assert p['point_id']==s['point_id'];assert s['status']=='COMPLETE'
  source=at(load(ROOT/p['source_matrix_ref']['path']),p['source_matrix_ref']['pointer'])
  admission=load(ROOT/p['source_link']['path'])
  assert p['source_link']['task_id'] in source['variants']
  assert admission['job_id'].startswith('JM1_C1_'+p['source_link']['task_id']+'_')
  assert p['source_component']==source['component'] and p['source_order']==source['original_source']
  inp=load(ROOT/p['input']);result=load(ROOT/p['result']);sem=result['semantic']
  assert sha(read(ROOT/p['input']))==sem['input_sha256']
  assert sha(canonical({k:v for k,v in sem.items() if k not in ('input_sha256','cost','semantic_digest')}))==sem['semantic_digest']
  ids=sorted(a['candidate_id'] for a in inp['pool']);pool={a['candidate_id']:a for a in inp['pool']}
  rows={r['candidate_id']:r for r in sem['actions']};descs={r['key']:r for r in sem['descriptors']}
  assert sem['descriptor_scope']['mode']=='FULL_POOL' and sem['descriptor_scope']['action_ids']==ids
  assert set(rows)==set(ids) and len(ids)==p['expected_actions']
  raw=read(ROOT/s['pair_inventory']['path']);assert sha(raw)==s['pair_inventory']['sha256']
  pairs=[json.loads(line) for line in raw.splitlines()]
  assert [(r['A'],r['B']) for r in pairs]==list(itertools.combinations(ids,2))
  counts=Counter();relations=Counter();areas=Counter()
  for i,r in enumerate(pairs):
   assert r['ordinal']==i and r['point_id']==p['point_id']
   a,b=[pool[r[k]] for k in ('A','B')];ap,bp=a['pose'],b['pose']
   # Independent classification expression; no call to diagnose.classify.
   if number(ap['z_base_mm']) or number(bp['z_base_mm']):kind='OUT_OF_SCOPE_NONFLOOR'
   elif a['pick_item_id']!=b['pick_item_id']:kind='OUT_OF_SCOPE_CROSS_BOX'
   elif number(ap['yaw_deg'])!=number(bp['yaw_deg']):kind='OUT_OF_SCOPE_YAW'
   elif all(number(ap[k])==number(bp[k]) for k in ap) and list(map(number,a['oriented_size_mm']))==list(map(number,b['oriented_size_mm'])):kind='DUPLICATE_EXACT_ACTION'
   else:kind='ELIGIBLE_FS_PAIR'
   assert r['classification']==kind
   counts[kind]+=1
   for label,document in [('input_refs',inp),('result_refs',result),('descriptor_refs',result)]:
    for ref in r['evidence'][label]:
     assert ref['sha256']==expected[ref['path']]['sha256']
     assert ref['pointer'] is not None
     at(document,ref['pointer'])
   if kind!='ELIGIBLE_FS_PAIR':continue
   aa,bb=[set(rows[r[k]]['fit_ids']) for k in ('A','B')]
   assert aa==set(r['A_fit_ids']) and bb==set(r['B_fit_ids'])
   relation='NO_DIRECTION' if aa==bb else 'A_STRICT_SUPERSET' if bb<aa else 'B_STRICT_SUPERSET' if aa<bb else 'TRADEOFF'
   assert r['fit_relation']==relation;relations[relation]+=1
   if relation!='NO_DIRECTION':
    assert r['area_vector']==[];continue
   remaining={o['item_id']:o for o in inp['state']['buffer'] if o['item_id']!=a['pick_item_id']}
   heights=sorted(set(number(o['size_mm'][2]) for o in remaining.values()))
   assert [number(v['height_mm']) for v in r['area_vector']]==heights
   for v in r['area_vector']:
    expected_values=[]
    for role in ('A','B'):
     keys={o['descriptor_key'] for member in rows[r[role]]['members'] if number(remaining[member['item_id']]['size_mm'][2])==number(v['height_mm']) for o in member['orientations']}
     assert len(keys)==1 and None not in keys
     expected_values.append(number(descs[next(iter(keys))]['maximum_area_mm2']))
    assert [number(v['A_mm2']),number(v['B_mm2'])]==expected_values
    assert number(v['delta_B_minus_A_mm2'])==expected_values[1]-expected_values[0]
   area='EQUAL_FIT_AREA_DIFF' if any(number(v['delta_B_minus_A_mm2']) for v in r['area_vector']) else 'EQUAL_FIT_AREA_EQUAL'
   assert area==r['area_status'];areas[area]+=1
  assert sum(counts.values())==len(ids)*(len(ids)-1)//2
  for key,value in s['classification_counts'].items():assert counts[key]==value
  for key,value in s['fit_relation_counts'].items():assert relations[key]==value
  for key,value in s['area_counts'].items():assert areas[key]==value
  component_points.setdefault(p['source_component'],[]).append(p['point_id'])
  totals.update(counts);total+=len(pairs)
 assert total==summary['pairs_enumerated']==summary['pairs_planned']==4890
 assert summary['actions_planned']==220
 assert {r['component']:r['states'] for r in summary['by_component']}==component_points
 assert summary['next_stage_admission']=='NOT_ASSESSED' and summary['return_to']=='INDEPENDENT_QA'
 print('PASS_FROZEN_ORDER_31_INPUTS_4890_PAIRS_EXACT_SETS_AREAS_AND_POINTERS')
 # Read audit is stdout only; no modification of delivered/frozen files.
 print(json.dumps(dict(verification_reads=READS),ensure_ascii=False))

if __name__=='__main__':main()

"""Independent stdlib arithmetic/source/order audit of frozen P4-A files."""
import argparse
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path

def read(p):return json.loads(Path(p).read_text())
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--package',type=Path,required=True);ap.add_argument('--receipt',type=Path,required=True);a=ap.parse_args()
 root=a.package;c=read(root/'data_catalog.json');t=read(root/'training_plan.json');e=read(root/'evaluation_template.json')
 assert c['catalog_digest']==digest({k:v for k,v in c.items() if k!='catalog_digest'})
 for plan in (t,e):
  assert plan['plan_digest']==digest({k:v for k,v in plan.items() if k!='plan_digest'})
  assert plan['catalog_digest']==c['catalog_digest'] and plan['execution_admitted'] is False and plan['sending_admitted'] is False
  for path,h in plan['input_identity'].items():assert sha(path)==h,path
 rows={r['task_id']:r for r in c['tasks']};training={k:v for k,v in rows.items() if v['training_eligible']}
 assert len(rows)==22 and sum(r['box_count'] for r in rows.values())==428
 assert len(training)==16 and sum(r['box_count'] for r in training.values())==264
 assert len({r['original_order'] for r in training.values()})==4
 assert len({r['source_component'] for r in training.values()})==3
 models={m['model_id']:m for m in t['models']};assert len(models)==6
 assert {(m['method'],m['seed']) for m in models.values()}==set(itertools.product(('pct_geo_b1','pct_load_b1'),(11,23,37)))
 for model in models.values():assert model['weights_sha256'] is None and model['status']=='PENDING_TRAINING'
 attempts=0
 for schedule in t['schedules']:
  m=models[schedule['model_id']];slots=schedule['attempts'];attempts+=len(slots)
  assert len(slots)==2000 and Counter(r['task_id'] for r in slots)==Counter({k:125 for k in training})
  assert sum(s['action_cap'] for s in slots)==33000
  for epoch in range(1,126):
   ids=sorted(training,key=lambda tid:(digest([m['seed'],epoch,tid]),tid))
   actual=[s for s in slots if s['epoch']==epoch]
   assert [s['task_id'] for s in actual]==ids
   for s in actual:
    assert s['status']=='NOT_RUN' and s['task_digest']==training[s['task_id']]['derived_task_digest']
    assert s['batch_id']==s['attempt_index']//8 and s['action_cap']==training[s['task_id']]['box_count']
 assert attempts==12000
 jobs=e['jobs'];assert len(jobs)==len({j['job_id'] for j in jobs})==220
 assert jobs[0]['job_id']=='NEW_00100027_controlled_base/jev_none_b1/r0'
 expected=set()
 for tid in rows:
  expected.add((tid,'geometry_b1',None,None))
  expected.update((tid,method,seed,None) for method in ('pct_geo_b1','pct_load_b1') for seed in (11,23,37))
  expected.update((tid,'jev_none_b1',None,r) for r in range(3))
 assert {(j['task_id'],j['method'],j['seed'],j['repeat']) for j in jobs}==expected
 block_ids=list(dict.fromkeys(j['task_id'] for j in jobs));seed=e['ordering_seed']
 first='NEW_00100027_controlled_base'
 assert block_ids==[first]+sorted((tid for tid in rows if tid!=first),key=lambda tid:(digest([seed,'task_block',tid]),tid))
 for block,tid in enumerate(block_ids):
  group=[j for j in jobs if j['task_id']==tid]
  assert len(group)==10 and all(j['block']==block for j in group)
  ordered=sorted(group,key=lambda j:(digest([seed,'slot',tid,j['method'],j['seed'],j['repeat']]),j['job_id']))
  if tid==first:
   anchor=next(j for j in ordered if j['p4c_probe_budget']==1);ordered=[anchor]+[j for j in ordered if j!=anchor]
  assert group==ordered
 for i,j in enumerate(jobs):
  row=rows[j['task_id']];n=row['box_count'];pct=j['method'].startswith('pct_');jev=j['method']=='jev_none_b1'
  assert j['order_index']==i and j['weights_sha256'] is None and j['status']=='NOT_RUN'
  assert j['source_component']==row['source_component'] and j['source_layer']==row['evaluation_layer']
  assert j['task_digest']==row['derived_task_digest'] and j['send_cap']==(n if jev else 0) and j['network_choice_cap']==(n if pct else 0)
  assert not j['execution_admitted'] and not j['sending_admitted']
  if pct:assert models[j['model_id']]['method']==j['method'] and models[j['model_id']]['seed']==j['seed']
 assert sum(j['send_cap'] for j in jobs)==1284 and sum(j['network_choice_cap'] for j in jobs)==2568
 assert sum(j['p4c_probe_budget'] for j in jobs)==1
 audit=read(root/'storage_roundtrip.json');assert audit['transitions']==147 and audit['attempts']==16 and audit['source_unchanged']
 for name,h in audit['original_hashes'].items():assert sha(Path('PCT/outputs/PCT_P3_20261115_01/attempt_02/training')/name)==h
 receipt={'status':'PASS_STDLIB_SAVED_PLAN_AUDIT','training_models':6,'planned_attempts':12000,'evaluation_slots':220,
          'sends_cap':1284,'local_choice_cap':2568,'source_independent_holdout':0,'source_files_checked':len(t['input_identity']),
          'source_file_roundtrip_hashes_checked':len(audit['original_hashes']),'business_execution':'NONE','model_imports':'NONE'}
 with a.receipt.open('x') as stream:json.dump(receipt,stream,ensure_ascii=False,indent=2)
 print(json.dumps(receipt))
if __name__=='__main__':main()

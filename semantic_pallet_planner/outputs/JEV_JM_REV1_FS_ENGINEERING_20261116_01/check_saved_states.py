"""Frozen five-point engineering coverage; saved public bytes only, no replay."""
import hashlib
import json
from pathlib import Path
import sys
import tracemalloc

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'semantic_pallet_planner/src'),str(ROOT/'semantic_pallet_planner/tests/unit')]
import test_packaging_scenario_features as guard
from semantic_pallet_planner.jev_select import packaging_fs_geometry as g
OUT=Path(__file__).resolve().parent
A1=ROOT/'semantic_pallet_planner/outputs/JEV_JM2_A1_20261115_01'
A2=ROOT/'semantic_pallet_planner/outputs/JEV_JM2_A2_20261115_01'
C1=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_C1_REAL_BASELINES_20261112_01'

def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def reference(p):
 return dict(path=p.relative_to(ROOT).as_posix(),sha256=g.sha(p.read_bytes()))
def checked(r):
 p=Path(r['path']);p=p if p.is_absolute() else ROOT/p
 assert p.resolve().is_relative_to(ROOT)
 raw=p.read_bytes();assert g.sha(raw)==r['sha256']
 return p,raw

def main():
 # Bind indexes to their saved manifests before locating any diagnostic inputs.
 for folder in (A1,A2):
  man=json.loads((folder/'delivery_manifest.json').read_text())
  selected=('field_origin_index.json','private_audit_index.json')
  for entry in man['files']:
   if Path(entry['path']).name in selected:checked(entry)
 origins=json.loads((A1/'field_origin_index.json').read_text())['points']
 cards=json.loads((A2/'private_audit_index.json').read_text())['cards']
 points=json.loads((C1/'fork_plan.json').read_text())['points']
 assert len(points)==len(origins)==len(cards)==5
 frozen=[]
 for p,o,card in zip(points,origins,cards):
  assert p['point_id']==o['point_id'] and p['point_id'] in card['family']['point_ids']
  loc=p['public_evidence_location']
  sp,sraw=checked(loc['prefix_ref']);pp,praw=checked(loc['pool_ref'])
  assert card['full_pool']['sha256']==g.sha(praw)
  checked(card['a1_input'])
  frozen.append(dict(point_id=p['point_id'],state=reference(sp),pool=reference(pp),
                     a1_input=card['a1_input'],
                     contrast=[x['candidate_id'] for x in p['branches']],
                     pool_count=len(json.loads(praw))))
 inventory=dict(version='jm_rev1_saved_inventory_v1',scope='ENGINEERING_ONLY_EXPOSED_NO_APPLICABILITY_OR_BENEFIT',
                origins=[reference(A1/'field_origin_index.json'),reference(A2/'private_audit_index.json'),reference(C1/'fork_plan.json')],points=frozen)
 target=OUT/'saved_input_inventory.json'
 if target.exists():assert json.loads(target.read_text())==inventory,'FROZEN_INVENTORY_CHANGED'
 else:write(target,inventory)
 replay_check=(OUT/'saved_state_coverage.json').exists()
 rows=[]
 for entry in frozen:
  _,sraw=checked(entry['state']);_,praw=checked(entry['pool'])
  for mode in ('HISTORICAL_AB','FULL_POOL'):
   raw,identity=g.from_saved_public(sraw,praw,state_sha256=entry['state']['sha256'],
          pool_sha256=entry['pool']['sha256'],mode=mode,contrast=entry['contrast'])
   name=entry['point_id']+'_'+mode
   input_path=OUT/(name+'_input.json')
   if input_path.exists():assert input_path.read_bytes()==raw,'INPUT_CHANGED'
   else:input_path.write_bytes(raw)
   tracemalloc.start()
   result=g.evaluate(raw,expected_sha256=identity)
   _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
   result['observations']['peak_traced_bytes']=peak
   # Memory is an outer engineering observation, never part of result schema or
   # deterministic geometry. Keep schema-validated core separately.
   peak=result['observations'].pop('peak_traced_bytes')
   result_path=OUT/(name+'_result.json')
   if replay_check:
    assert json.loads(result_path.read_text())['semantic']==result['semantic'],'GEOMETRY_CHANGED'
   else:write(result_path,result)
   sem=result['semantic']
   row=dict(point_id=entry['point_id'],mode=mode,pool_count=entry['pool_count'],
      status=sem['status'],reason=sem['reason'],contrast=sem['contrast'],
      action_status_counts={k:sum(a['status']==k for a in sem['actions']) for k in ('VALUE','NOT_APPLICABLE','UNKNOWN','INVALID_INPUT')},
      preflight=sem['preflight'],actual_cost=sem['cost'],elapsed_s=result['observations']['elapsed_s'],
      peak_traced_bytes=peak,input=reference(OUT/(name+'_input.json')),result=reference(OUT/(name+'_result.json')))
   rows.append(row)
   print(json.dumps({k:row[k] for k in ('point_id','mode','status','reason','elapsed_s','preflight')},ensure_ascii=False),flush=True)
 coverage=dict(version='jm_rev1_saved_coverage_v1',scope=inventory['scope'],rows=rows,
    points=5,scopes=10,not_a_retrieval_label=True,research_benefit='NOT_ESTABLISHED',
    memory='tracemalloc Python allocations per scope;not process RSS or physical system maximum',
    missing_or_adapter_failures=0)
 if replay_check:
  prior=json.loads((OUT/'saved_state_coverage.json').read_text())
  fields=('point_id','mode','pool_count','status','reason','contrast','action_status_counts','preflight','actual_cost','input','result')
  assert [{k:r[k] for k in fields} for r in prior['rows']]==[{k:r[k] for k in fields} for r in rows]
  print('PASS_READ_ONLY_RECHECK_NO_ARCHIVE_OVERWRITE',flush=True)
 else:write(OUT/'saved_state_coverage.json',coverage)

if __name__=='__main__':main()

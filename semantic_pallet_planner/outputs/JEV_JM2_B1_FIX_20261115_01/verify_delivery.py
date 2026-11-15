"""Read-only exact identities, historical retention and remediation records."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
BASE=ROOT/'semantic_pallet_planner/outputs';PARENT=BASE/'JEV_JM2_B1_LIMITED_20261115_01';QA=BASE/'JEV_JM2_B1_LIMITED_QA_20261115_01'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 count=0
 for folder in [OUT,PARENT,QA]:
  for e in read(folder/'delivery_manifest.json')['files']:
   p=ROOT/e['path']
   if sha(p)!=e['sha256']:
    assert folder==PARENT and p.name in ['packaging_experience_contract.py','packaging_versions.py']
    p=OUT/'entry_source_bytes'/p.name
   assert p.stat().st_size==e['bytes'] and sha(p)==e['sha256'];count+=1
   assert not e['path'].startswith('SKILL/')
 refs=[]
 def walk(v):
  if isinstance(v,dict):
   if {'path','sha256'}<=set(v):
    p=(ROOT/v['path']).resolve();assert p.is_relative_to(ROOT) and sha(p)==v['sha256']
    if v.get('pointer'):
     data=read(p)
     for t in v['pointer'].split('/')[1:]:
      t=t.replace('~1','/').replace('~0','~');data=data[int(t)] if isinstance(data,list) else data[t]
    refs.append(v)
   else:
    for x in v.values():walk(x)
  elif isinstance(v,list):
   for x in v:walk(x)
 for p in OUT.glob('*.json'):
  if p.name not in ['delivery_manifest.json','source_manifest.json']:walk(read(p))
 for n,d in read(OUT/'source_manifest.json').items():assert sha(ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'/n)==d
 result=read(OUT/'focused_results.json');assert len(result['cases'])==51 and result['unexpected_exceptions']==[]
 for row in result['cases']:
  r=row['result'];assert r['qualified_generation_input'] is False and r['execution_eligible'] is False
 ready=read(OUT/'experience_generation_readiness.json');assert ready['next_stage_admission']=='NOT_READY' and ready['qualified_real_cards']==0
 assert read(QA/'next_stage_admission.json')['status']=='NOT_READY'
 assert any(f['blocking'] for f in read(QA/'quality_review.json')['findings'])
 assert len(read(OUT/'issue_closure.json')['issues'])==3
 report=ROOT/read(OUT/'handoff.json')['report']
 for target in re.findall(r'\]\(([^)]+)\)',report.read_text()):assert (report.parent/target).resolve().is_file()
 print('PASS_MINIMAL_FIX_DELIVERY',count,'MANIFEST_ENTRIES',len(refs),'REFERENCES; HISTORICAL_FAIL_PARTIAL_RETAINED; NEXT_STAGE_NOT_READY')
if __name__=='__main__':main()

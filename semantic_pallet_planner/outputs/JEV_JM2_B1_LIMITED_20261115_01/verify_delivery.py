"""Read-only B1 delivery/parent/reference checks; stdlib only."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
BASE=ROOT/'semantic_pallet_planner/outputs'
CACHE={}
def read(p):
 p=p.resolve()
 if p not in CACHE:CACHE[p]=json.loads(p.read_text())
 return CACHE[p]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def at(v,p):
 for k in p.split('/')[1:]:
  k=k.replace('~1','/').replace('~0','~');v=v[int(k)] if isinstance(v,list) else v[k]
 return v

def main():
 files=0
 for folder in [OUT,BASE/'JEV_JM2_A3_QA_20261115_01',BASE/'JEV_JM2_A3_20261115_01',BASE/'JEV_JM2_A2_20261115_01']:
  for e in read(folder/'delivery_manifest.json')['files']:
   p=ROOT/e['path'];raw_path=p
   if sha(p)!=e['sha256']:
    assert folder!=OUT and e['path'] in ['semantic_pallet_planner/src/semantic_pallet_planner/jev_select/contracts.py','semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_versions.py']
    raw_path=OUT/'entry_source_bytes'/p.name
   assert sha(raw_path)==e['sha256'] and raw_path.stat().st_size==e['bytes'];files+=1
   assert not e['path'].startswith('SKILL/')
 refs=[]
 def walk(v):
  if isinstance(v,dict):
   if {'path','sha256'}<=set(v):
    p=(ROOT/v['path']).resolve();assert p.is_relative_to(ROOT) and sha(p)==v['sha256']
    if v.get('pointer') or p.suffix=='.json' and 'pointer' in v:at(read(p),v.get('pointer',''))
    refs.append(v)
   else:
    for x in v.values():walk(x)
  elif isinstance(v,list):
   for x in v:walk(x)
 for p in sorted(OUT.glob('*.json')):
  if p.name not in ['delivery_manifest.json','source_manifest.json']:walk(read(p))
 original=read(BASE/'JEV_JM2_A2_20261115_01/case_snapshot_candidate.json')['cards']
 packs=read(OUT/'real_negative_fact_packs.json')['packs'];rejections=read(OUT/'real_card_rejections.json')['cases']
 for c,p,r in zip(original,packs,rejections):
  assert c==p['case'] and p['origin']=='REAL_ARCHIVE_NEGATIVE'
  assert r['gate']['status']=='NOT_READY' and not r['gate']['qualified_generation_input']
 fixture=read(OUT/'synthetic_positive_contract.json');assert fixture['origin']=='SYNTHETIC_FIXTURE_ONLY'
 assert fixture['result']['content_review']=='PENDING' and not fixture['gate']['qualified_generation_input']
 assert len(read(OUT/'constructed_validation.json')['cases'])==20
 ready=read(OUT/'experience_generation_readiness.json')
 assert ready['real_material_status']=='NOT_READY' and ready['qualified_real_cards']==0 and ready['full_B1_exit']=='NOT_AUTHORIZED_NOT_CLOSED'
 for n,d in read(OUT/'source_manifest.json').items():assert sha(ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'/n)==d
 report=ROOT/read(OUT/'handoff.json')['report']
 for target in re.findall(r'\]\(([^)]+)\)',report.read_text()):assert (report.parent/target).resolve().is_file()
 assert read(OUT/'acceptance.json')['items'][1]['status']=='PARTIAL' and read(OUT/'acceptance.json')['items'][2]['status']=='PARTIAL'
 print('PASS_B1_LIMITED_DELIVERY',files,'MANIFEST_ENTRIES',len(refs),'EXACT_REFERENCES; REAL_NOT_READY_QUALIFIED0_FULL_B1_NOT_CLOSED')
if __name__=='__main__':main()

"""Read-only verification of A3 and preserved parent artifacts."""
import json,re
from pathlib import Path
from review_saved import ROOT,OUT,A2,BASE,read,sha,resolve

def main():
 total=0
 for directory in [OUT,A2,BASE/'JEV_JM2_A2_QA_20261115_01']:
  manifest=read(directory/'delivery_manifest.json')
  for e in manifest['files']:
   p=ROOT/e['path'];assert p.stat().st_size==e['bytes'] and sha(p)==e['sha256'];assert not e['path'].startswith('SKILL/');total+=1
 review=read(OUT/'projection_sufficiency_review.json');assert len(review['cards'])==5 and review['summary']['comparisons']==9
 refs=[]
 def walk(v):
  if isinstance(v,dict):
   if {'path','sha256','pointer'}<=set(v):
    p=Path(v['path']);p=p if p.is_absolute() else ROOT/p
    assert p.resolve().is_relative_to(ROOT) and sha(p)==v['sha256']
    if v['pointer'] or p.suffix=='.json':resolve(v)
    refs.append(v)
   else:
    for x in v.values():walk(x)
  elif isinstance(v,list):
   for x in v:walk(x)
 for name in ['projection_sufficiency_review.json','evidence_mapping.json','review_source.json','inherited_boundaries.json','check_attempts.json','handoff.json']:walk(read(OUT/name))
 for card in review['cards']:
  assert len(card['dimensions'])==6 and card['disposition']=='ARCHIVE_ONLY' and not card['execution_eligible']
  assert card['trusted_content_approval']=='PENDING' and card['M21_07']['overall']=='PARTIAL_PENDING_TRUSTED_REVIEW'
 source=read(OUT/'review_source.json');assert source['human_signature'] is None and source['independent_reviewer'] is None and not source['trusted_independent_approval']
 pkg=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
 for name,d in read(OUT/'source_manifest.json').items():assert sha(pkg/name)==d
 report=ROOT/read(OUT/'handoff.json')['report']
 for target in re.findall(r'\]\(([^)]+)\)',report.read_text()):assert (report.parent/target).resolve().is_file()
 assert read(OUT/'acceptance.json')['items'][-1]['status']=='PARTIAL_PENDING_TRUSTED_REVIEW'
 assert read(OUT/'handoff.json')['next_stage_admission']=='INDEPENDENT_QA_ONLY'
 print('PASS_A3_DELIVERY_EXACT_BYTES_AND_REFERENCES',total,len(refs),'PARENT_FAILURE_LOG_RETAINED; M21_07_PARTIAL')
if __name__=='__main__':main()

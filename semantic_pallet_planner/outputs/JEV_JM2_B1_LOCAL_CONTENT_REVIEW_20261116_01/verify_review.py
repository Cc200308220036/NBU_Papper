"""Read-only byte/reference and review-disposition verification."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 files=read(OUT/'delivery_manifest.json')['files']
 for e in files:
  p=ROOT/e['path'];assert p.stat().st_size==e['bytes'] and sha(p)==e['sha256'];assert not e['path'].startswith('SKILL/')
 refs=[]
 def walk(v):
  if isinstance(v,dict):
   if {'path','sha256','pointer'}<=set(v):
    p=(ROOT/v['path']).resolve();assert p.is_relative_to(ROOT) and sha(p)==v['sha256'];x=read(p)
    for k in v['pointer'].split('/')[1:]:
     k=k.replace('~1','/').replace('~0','~');x=x[int(k)] if isinstance(x,list) else x[k]
    refs.append(v)
   else:
    for x in v.values():walk(x)
  elif isinstance(v,list):
   for x in v:walk(x)
 for p in OUT.glob('*.json'):
  if p.name!='delivery_manifest.json':walk(read(p))
 review=read(OUT/'per_card_content_review.json');assert len(review['cards'])==5
 for c in review['cards']:
  assert c['review_status']=='COMPLETED_LOCAL_CONTENT_REVIEW' and c['decision']=='ARCHIVE_ONLY'
  assert c['qualified_generation_input'] is False and c['execution_eligible'] is False and c['causal_proof_required'] is False
  assert all(c[k] for k in ['observable_preconditions','comparison_direction','claim_scope_review','cost_and_counterevidence','registered_condition_expression','unknown_effect_on_disposition'])
 source=read(OUT/'authorization_and_source.json');assert source['human_signature'] is None and source['external_model'] is None and source['prior_participation']
 ready=read(OUT/'experience_generation_readiness.json');assert ready['review_execution']=='COMPLETED_5' and ready['qualified_real_cards']==0 and ready['next_stage_admission']=='NOT_READY'
 manifest=read(ROOT/read(OUT/'source_identity.json')['production_manifest']['path'])
 for n,d in manifest.items():assert sha(ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'/n)==d
 report=ROOT/read(OUT/'handoff.json')['report']
 for t in re.findall(r'\]\(([^)]+)\)',report.read_text()):assert (report.parent/t).resolve().is_file()
 print('PASS_LOCAL_REVIEW_ARCHIVE',len(files),'FILES',len(refs),'REFERENCES; FIVE_REVIEWED; QUALIFIED0; SOURCE517_UNCHANGED')
if __name__=='__main__':main()

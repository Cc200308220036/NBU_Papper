"""Read-only supplemental artifacts, pointers, identities and conclusion checks."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
BASE=ROOT/'semantic_pallet_planner/outputs'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 count=0
 for e in read(OUT/'delivery_manifest.json')['files']:
  p=ROOT/e['path'];assert p.stat().st_size==e['bytes'] and sha(p)==e['sha256'];count+=1
  assert not e['path'].startswith('SKILL/')
 refs=[]
 def walk(v):
  if isinstance(v,dict):
   if {'path','sha256','pointer'}<=set(v):
    p=(ROOT/v['path']).resolve();assert p.is_relative_to(ROOT) and sha(p)==v['sha256']
    if p.suffix=='.json':
     x=read(p)
     for t in v['pointer'].split('/')[1:]:
      t=t.replace('~1','/').replace('~0','~');x=x[int(t)] if isinstance(x,list) else x[t]
    else:assert v['pointer']==''
    refs.append(v)
   else:
    for x in v.values():walk(x)
  elif isinstance(v,list):
   for x in v:walk(x)
 for p in OUT.glob('*.json'):
  if p.name!='delivery_manifest.json':walk(read(p))
 source=read(BASE/'JEV_JM2_B1_FIX_20261115_01/source_manifest.json')
 for n,d in source.items():assert sha(ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'/n)==d
 cards=read(OUT/'per_card_supplement_matrix.json')['cards'];assert len(cards)==5
 labels={}
 for c in cards:
  assert c['disposition']['current']=='ARCHIVE_ONLY' and c['disposition']['trusted_content_approval']=='PENDING'
  assert not c['disposition']['generation_input_eligible'] and not c['disposition']['execution_eligible']
  assert c['deletion_rationale']['actual_deletion_test'].startswith('NOT_RUN')
  assert all(c[k] for k in ['tradeoff','necessary_observable_conditions','retained_support_space_structure','unknowns','existing_public_record_answer','result_and_counterevidence','deletion_rationale','disposition'])
  for row in c['result_and_counterevidence']['observations']:labels[row['label']]=labels.get(row['label'],0)+1
 assert labels=={'improved':4,'degraded':3,'neutral':2}
 bounds=read(OUT/'inherited_boundaries.json');assert len(bounds['original_stage_gaps'])==7 and len(bounds['original_class_gaps'])==5
 assert bounds['C2']['registered_jobs']==18 and bounds['C2']['registered_pairs']==9
 assert bounds['C2']['independent_unseen_sources']==0
 ready=read(OUT/'experience_generation_readiness.json');assert ready['admission']=='NOT_READY' and ready['qualified_real_cards']==0 and ready['mechanism_proof_required'] is False
 reviewer=read(OUT/'review_source.json');assert reviewer['human_signature'] is None and reviewer['verifiable_trusted_authorization'] is None and reviewer['status']=='PENDING'
 report=ROOT/read(OUT/'handoff.json')['report']
 for target in re.findall(r'\]\(([^)]+)\)',report.read_text()):assert (report.parent/target).resolve().is_file()
 print('PASS_SUPPLEMENT_DELIVERY',count,'FILES',len(refs),'REFERENCE_OCCURRENCES; SOURCE517_UNCHANGED; TRUSTED_APPROVAL_PENDING_5; NOT_READY')
if __name__=='__main__':main()

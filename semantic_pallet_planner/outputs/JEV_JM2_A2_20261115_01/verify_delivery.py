"""Read-only final A2 byte/provenance/link checks; no engine or remote work."""
import hashlib,json,re
from pathlib import Path
from build_and_verify import ROOT,OUT,read,sha,resolve,leaves

def main():
 manifest=read(OUT/'delivery_manifest.json')
 for item in manifest['files']:
  p=ROOT/item['path'];assert p.is_file() and p.stat().st_size==item['bytes'] and sha(p)==item['sha256']
  assert not item['path'].startswith('SKILL/')
 cards=read(OUT/'case_snapshot_candidate.json')['cards']
 mapping=read(OUT/'field_and_claim_evidence.json')['cards'];refs=0
 for card,entry in zip(cards,mapping):
  fields=dict(leaves(card));assert set(fields)=={r['output_pointer'] for r in entry['fields']}
  for row in entry['fields']:
   values=[resolve(r) for r in row['sources']];refs+=len(values)
   if row['transform'] in ('COPY','PROTOCOL_CONSTANT_NOT_EMPIRICAL_CLAIM'):assert fields[row['output_pointer']]==values[0]
   if row['transform']=='B_MINUS_A':assert fields[row['output_pointer']]==values[1]-values[0]
  for claim in entry['claims']:
   for r in claim['sources']:resolve(r);refs+=1
 queries=read(OUT/'query_projection_checks.json')['queries']
 for c,q in zip(cards,queries):
  assert set(q)=={'version','coordinate','structure','features'}
  for k in ('structure','features','coordinate'):assert c[k]==q[k]
 source=read(OUT/'source_manifest.json');pkg=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
 for name,d in source.items():assert sha(pkg/name)==d
 assert hashlib.sha256(json.dumps(source,sort_keys=True,separators=(',',':')).encode()).hexdigest()==read(OUT/'source_identity.json')['source_digest']
 report=ROOT/read(OUT/'handoff.json')['report']
 for target in re.findall(r'\]\(([^)]+)\)',report.read_text()):assert (report.parent/target).resolve().is_file()
 assert read(OUT/'acceptance.json')['not_closed'][0]=={'id':'M21-07','status':'NOT_RUN_A3'}
 print('PASS_DELIVERY_BYTES_SOURCE_LINKS_AND_ALL_FIELD_REFERENCES',len(manifest['files']),len(source),refs)
if __name__=='__main__':main()

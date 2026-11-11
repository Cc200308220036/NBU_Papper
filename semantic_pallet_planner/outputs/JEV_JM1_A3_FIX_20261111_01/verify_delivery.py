"""Standard library only: saved hashes, production-test receipts, no dispatch."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

OUT=Path(__file__).resolve().parent
REPO=OUT.parents[2]
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def local(s):
    p=(REPO/s).resolve();assert p.is_relative_to(REPO);return p

def main():
    manifest=read(OUT/'delivery_manifest.json')
    for r in manifest['files']:
        p=local(r['path']);assert sha(p)==r['sha256'] and p.stat().st_size==r['bytes'],r['path']
    for r in read(OUT/'input_evidence_index.json')['files']:
        assert sha(local(r['path']))==r['sha256'],r['path']
    source=read(OUT/'source_identity.json')['source_manifest']
    for p,h in source.items():assert sha(REPO/'semantic_pallet_planner/src/semantic_pallet_planner'/p)==h,p
    counts={}
    for n in ('targeted','regression','legacy'):
        t=ET.parse(OUT/(n+'_junit.xml'))
        assert not t.findall('.//failure') and not t.findall('.//error') and not t.findall('.//skipped')
        counts[n]=len(t.findall('.//testcase'))
    assert counts=={'targeted':11,'regression':62,'legacy':58}
    evidence=read(OUT/'production_negative_evidence.json')
    assert len(evidence['cases'])==8
    assert {s for c in evidence['cases'] for s in c['request_states']} >= {'RESPONSE_SAVED','SELECTION_SAVED','INTENT'}
    for c in evidence['cases']:
        r=read(local(c['receipt']))
        assert r['production_validator'] and not r['identities_or_schemas_substituted']
        assert r['remaining_files_before']==r['remaining_files_after']
        assert [x['entry'] for x in r['rejections']]==['validate_saved_execution','run_repeat']
        for result in r['rejections']:
            assert result['remaining_files_unchanged'] and not any(result['dispatch_counts'].values())
        if c['kind']=='joint_loss':
            root=local(c['copy_root'])
            assert not (root/'stages').exists() and not (root/'checkpoint_head.json').exists() and not (root/'episode.json').exists()
            for p in root.rglob('*'):
                if p.is_file():assert sha(p)==sha(local(c['source_root'])/p.relative_to(root))
    assert len(read(OUT/'regression_evidence_index.json')['recovery_observations'])==26
    print(json.dumps({'status':'PASS_SAVED_FACTS_ONLY','manifest_files':len(manifest['files']),
                      'source_files':len(source),'tests':counts,'production_negative_cases':8,
                      'zero_dispatch_rejections':16},ensure_ascii=False))

if __name__=='__main__':main()

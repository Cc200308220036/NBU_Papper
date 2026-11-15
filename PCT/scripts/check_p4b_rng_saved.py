"""Stdlib saved-byte/claim receipts check; no model/planner import or execution."""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'PCT/outputs/PCT_P4_B_0_RNG_20261115_01'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    manifest=json.loads((OUT/'delivery_manifest.json').read_text())
    for row in manifest['files']:
        p=ROOT/row['path'];assert p.is_file() and p.stat().st_size==row['bytes'] and sha(p)==row['sha256'],row['path']
    protected=json.loads((OUT/'historical_protection.json').read_text())
    for name,h in protected['unchanged'].items():assert sha(ROOT/name)==h,name
    for name,h in protected['public_patches_unchanged_from_entry'].items():assert sha(ROOT/name)==h,name
    counter=json.loads((OUT/'original_counterexample_recheck.json').read_text())
    assert counter['fixed_python_third_draw']==counter['expected_python_third_draw']!=counter['archived_wrong_python_third_draw']
    prefixes=json.loads((OUT/'batch_prefix_comparison.json').read_text())['cases']
    assert [r['saved_prefix'] for r in prefixes]==[0,1,2,3,5,7,8]
    assert all(r['all_three_rng_and_results_equal'] for r in prefixes)
    stages=json.loads((OUT/'five_stage_rng_comparison.json').read_text())['cases']
    assert len(stages)==5 and len({r['post_rng_digest'] for r in stages})==1
    print(json.dumps({'status':'PASS_SAVED_ONLY','manifest_files':len(manifest['files']),
                      'historical_unchanged':len(protected['unchanged']),'public_patches_unchanged':3,
                      'prefix_cases':len(prefixes),'phase_cases':len(stages)}))


if __name__=='__main__':main()

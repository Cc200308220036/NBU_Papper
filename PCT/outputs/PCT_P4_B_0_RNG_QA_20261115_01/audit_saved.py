"""Stdlib saved evidence and identity audit; no business/model imports."""
import hashlib
import json
import random
from pathlib import Path
P=Path('PCT/outputs/PCT_P4_B_0_RNG_20261115_01');Q=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
manifest=read(P/'delivery_manifest.json');navigation=[]
for row in manifest['files']:
 p=Path(row['path'])
 if sha(p)!=row['sha256'] or p.stat().st_size!=row['bytes']:
  assert str(p) in ('PCT/README.md','PCT/docs/README.md'),str(p)
  navigation.append(str(p))
protection=read(P/'historical_protection.json')
for n,h in protection['unchanged'].items():assert sha(n)==h,n
for n,h in protection['public_patches_unchanged_from_entry'].items():assert sha(n)==h,n
source=read(P/'identity.json')['execution_identity']['source']
for name,h in source.items():
 path=Path('PCT/src')/name if name.startswith('pct_baseline/') else Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select')/name
 assert sha(path)==h,str(path)
old=read('PCT/outputs/PCT_P4_B_0_FIX_QA_20261115_01/batch_rng_probe.json')
current=read(Q/'original_counterexample_recheck.json');archive=read(P/'original_counterexample_recheck.json')
generator=random.Random(11);draws=[generator.random() for _ in range(3)]
assert current==archive and current['fixed_python_third_draw']==draws[2]==old['next_uninterrupted_draw']
assert current['archived_wrong_python_third_draw']==draws[0]==old['next_resumed_draw']
prefixes=read(Q/'batch_prefix_comparison.json');phases=read(Q/'five_stage_rng_comparison.json')
assert prefixes==read(P/'batch_prefix_comparison.json')
assert phases==read(P/'five_stage_rng_comparison.json')
assert [r['saved_prefix'] for r in prefixes['cases']]==[0,1,2,3,5,7,8]
for r in prefixes['cases']:
 n=r['saved_prefix'];assert r['new_synthetic_callbacks']==8-n and r['cursor']==8
 assert r['actual_reused_counts']=={'actual_attempts':8-n,'saved_attempt_reuses':n,'rng_post_consumptions':n}
 assert r['next_draw']==prefixes['baseline_next_draw']
assert len(phases['cases'])==5
for field in ('post_rng_digest','results_digest','next_three_draws','final_state'):
 assert all(r[field]==phases['cases'][0][field] for r in phases['cases'])
receipt={'status':'PASS_SAVED_IDENTITIES_AND_INDEPENDENT_ARITHMETIC','manifest_files':len(manifest['files']),
 'history_files':len(protection['unchanged']),'public_patch_files':len(protection['public_patches_unchanged_from_entry']),
 'source_identity_files':len(source),'navigation_differences':navigation,'prefixes':7,'stages':5,
 'fixed_python_draw':draws[2],'old_wrong_draw_preserved':draws[0],
 'current_vs_archived_receipts':'EQUAL','scope':'saved facts and independent Python draw/count arithmetic; current tests separately cover synthetic process restarts',
 'business_execution':'NONE'}
(Q/'independent_saved_checks.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))

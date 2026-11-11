"""B1 saved-byte/source checks only. No business-engine imports or recomputation.

Run at repository root. Manifest excludes itself to avoid a hash cycle.
"""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent

def sha(raw):return hashlib.sha256(raw).hexdigest()
def load(p):return json.loads(p.read_text())

manifest=load(OUT/'delivery_manifest.json')
for row in manifest['files']:
    p=ROOT/row['path']
    assert p.is_file() and sha(p.read_bytes())==row['sha256'],row['path']
inputs=load(OUT/'input_evidence_index.json')['files']
for row in inputs:
    if row.get('git_ref'):
        raw=subprocess.check_output(['git','show',row['git_ref']+':'+row['path']],cwd=ROOT)
    else:
        raw=(ROOT/row['path']).read_bytes()
    assert sha(raw)==row['sha256'],row['path']
for row in load(OUT/'source_identity.json')['source_files']:
    assert sha((ROOT/row['path']).read_bytes())==row['sha256'],row['path']
# Preexisting tracked files changed only where explicitly authorized.
changed=subprocess.check_output(['git','-c','core.quotepath=false','diff','--name-only','HEAD'],cwd=ROOT,text=True).splitlines()
allowed={'docs/03_阶段产出分析/Jev/README.md',
         'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_versions.py'}
assert set(changed)<=allowed,changed
registry='semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_versions.py'
previous=subprocess.check_output(['git','show','HEAD:'+registry],cwd=ROOT)
current=(ROOT/registry).read_bytes()
assert current.startswith(previous) and b'JM_SAMPLING_PROTOCOLS' in current[len(previous):]
# New module's only relative business package import is the inert version registry.
module=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_jev_sampling.py'
tree=ast.parse(module.read_text())
relative=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.level]
assert relative==['packaging_versions'],relative
# Check every archived selected action and its full frozen candidate and raw bytes.
batch=load(OUT/'cap_batch.json')
checks=[(load(OUT/'constructed_public.json'),load(OUT/'constructed_diagnostic.json'))]
checks.extend((p,load(OUT/'cap_coverage.json')) for p in batch['decisions'])
dup=load(OUT/'duplicate_actions.json');checks.append((dup['input'],dup['result']))
checked=0
for public,diagnostic in checks:
    evidence=public['probability_evidence']
    import base64
    assert sha(base64.b64decode(evidence['raw_base64'],validate=True))==evidence['raw_sha256']
    for field,expected in [('pool_ref',[c['frozen_candidate'] for c in public['pool']]),('prefix_ref',public['public_state'])]:
        ref=public[field];p=ROOT/ref['path']
        assert sha(p.read_bytes())==ref['sha256'] and ref['pointer']==''
        assert load(p)==expected
    for point in diagnostic['selected_points']:
        if (point['task_id'],point['decision_id'])!=(public['task_id'],public['decision_id']):continue
        for branch in point['branches']:
            c=next(c for c in public['pool'] if c['candidate_id']==branch['candidate_id'])
            assert branch['candidate_digest']==c['candidate_digest']
            assert any(m['label']==branch['label'] and m['candidate_id']==c['candidate_id'] for m in public['display_mapping'])
            checked+=1
# Local Markdown links in new report and adapter; no historical link rewrite.
report=ROOT/load(OUT/'handoff.json')['report']
for path in [report,OUT/'input_adapter_notes.md']:
    for target in re.findall(r'\]\(([^)]+)\)',path.read_text()):
        if '://' not in target and not target.startswith('#'):
            assert (path.parent/target.split('#')[0]).exists(),target
print(json.dumps({'status':'PASS_SAVED_BYTES_AND_STATIC_PROTECTION','delivery_files':len(manifest['files']),
                  'input_files':len(inputs),'selected_action_references_checked':checked,
                  'business_imports':0,'candidate_model_monitor_dispatches':0},ensure_ascii=False))

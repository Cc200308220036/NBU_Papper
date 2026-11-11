"""JM1-B2 versioned pure saved-byte delivery audit; no current HEAD dependency.

No business imports, execution, candidate generation, sampling or monitor solve.
Run from repository root, before or after committing unchanged delivery bytes.
"""
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent

def load(path):return json.loads(path.read_text())
def sha(raw):return hashlib.sha256(raw).hexdigest()
def path_for(relative):
    path=(ROOT/relative).resolve()
    assert not Path(relative).is_absolute() and path.is_relative_to(ROOT),'path escape'
    return path

def exact(row):
    path=path_for(row['path']);raw=path.read_bytes()
    assert len(raw)==row['bytes'] and sha(raw)==row['sha256'],row['path']

manifest=load(OUT/'delivery_manifest.json')
assert manifest['version']=='jm1_b2_delivery_manifest_v1'
assert re.fullmatch('[0-9a-f]{40}',manifest['entry_head'])
for row in manifest['files']:exact(row)
inputs=load(OUT/'input_evidence_index.json')
for row in inputs['files']:exact(row)
source=load(OUT/'source_identity.json')
assert source['entry_head']==manifest['entry_head']
for row in source['source_files']+source['protected_existing_sources']:exact(row)
# Supplemental B1 source/receipt checks, including independently pinned extension.
capsule=load(OUT/'b1_saved_audit_v1.json')
assert capsule['entry_head']==manifest['entry_head']
for row in capsule['files']:
    raw=path_for(row['path']).read_bytes()
    if row['comparison']=='EXACT':
        assert row['extension_sha256'] is None
        exact(row)
    else:
        assert row['path']=='semantic_pallet_planner/src/semantic_pallet_planner/jev_select/packaging_versions.py'
        assert sha(raw[:row['bytes']])==row['sha256']
        assert sha(raw[row['bytes']:])==row['extension_sha256']
# Check local links in this new report; historic navigation hashes aren't rewritten.
report=path_for(load(OUT/'handoff.json')['report'])
for target in re.findall(r'\]\(([^)]+)\)',report.read_text()):
    if '://' not in target and not target.startswith('#'):
        assert (report.parent/target.split('#')[0]).exists(),target
budget=load(OUT/'constructed_budget.json')
assert len(budget['jobs'])==54 and budget['total_suffixes']==48
assert sum(j['send_upper'] for j in budget['jobs'])==budget['global_send_upper']
assert budget['execution_authorized'] is False
refusal=load(OUT/'formal_freeze_refusal.json')
assert refusal['formal_frozen'] is False and refusal['status']=='REFUSED'
print(json.dumps({'version':'jm1_b2_delivery_saved_check_v1','status':'PASS_SAVED_BYTES_ONLY',
    'entry_head':manifest['entry_head'],'delivery_files':len(manifest['files']),
    'input_files':len(inputs['files']),'missing_parent_QA':len(inputs['missing_files']),
    'B1_supplement_files':len(capsule['files']),'current_HEAD_dependency':False,
    'model_candidate_order_monitor_dispatches':0,'formal_freeze':'REFUSED'},ensure_ascii=False))

"""Pure saved-byte fix delivery verification; no project/business imports or Git HEAD use."""
import ast
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent

def load(path):return json.loads(path.read_text())
def sha(raw):return hashlib.sha256(raw).hexdigest()
def check(row):
    path=(ROOT/row['path']).resolve()
    assert not Path(row['path']).is_absolute() and path.is_relative_to(ROOT)
    raw=path.read_bytes()
    assert len(raw)==row['bytes'] and sha(raw)==row['sha256'],row['path']

manifest=load(OUT/'delivery_manifest.json')
assert manifest['version']=='jm1_b2_fix_delivery_manifest_v1'
for row in manifest['files']:check(row)
inputs=load(OUT/'input_evidence_index.json')
for row in inputs['files']:check(row)
source=load(OUT/'source_identity.json')
for row in source['files']:check(row)
protected=load(OUT/'original_artifact_protection.json')
for row in protected['files']:check(row)
replay=load(OUT/'semantic_probe.json')
assert len(replay['cases'])==4 and all(c['observation']['accepted'] is False for c in replay['cases'])
assert replay['original_package_unchanged'] and replay['validation_readonly']
assert replay['sampler_engine_model_solver_dispatches']==0
original=ROOT/'semantic_pallet_planner/outputs/JEV_JM_JM1_B2_QA_20261111_01/probe_saved_point.py'
assert (OUT/'replay_original_qa_probe.py').read_bytes()==original.read_bytes()
for filename in ['negative_semantic_receipts.json','diagnostic_negative_receipts.json']:
    for row in load(OUT/filename)['cases']:
        assert row.get('actual') and row['dispatches']==0
legal=load(OUT/'legal_original_receipt.json')
assert legal['only_result_version_changed'] and legal['current_result']['global_send_upper']==579
assert legal['formal_gate']['status']=='REFUSED' and legal['formal_gate']['formal_frozen'] is False
module=ROOT/source['changed_business_source']
tree=ast.parse(module.read_text())
assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and
    n.func.attr in ('sample','run_episode','assess_candidate','generate_candidates') for n in ast.walk(tree))
report=ROOT/load(OUT/'handoff.json')['report']
for target in re.findall(r'\]\(([^)]+)\)',report.read_text()):
    if '://' not in target and not target.startswith('#'):
        assert (report.parent/target.split('#')[0]).exists(),target
print(json.dumps({'version':'jm1_b2_fix_delivery_check_v1','status':'PASS_SAVED_BYTES_AND_STATIC_CHECKS',
    'delivery_files':len(manifest['files']),'input_files':len(inputs['files']),
    'protected_original_files':len(protected['files']),'source_files':len(source['files']),
    'original_QA_cases_refused':4,'forbidden_dispatches':0,'current_HEAD_dependency':False,
    'historical_navigation_gap':'RETAINED','independent_QA':'PENDING'},ensure_ascii=False))

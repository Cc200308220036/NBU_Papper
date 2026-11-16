"""Read-only fix identity/delivery checks; no production module imports."""
import hashlib
import json
from pathlib import Path

ROOT=Path.cwd();OUT=Path(__file__).resolve().parent
def load(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
seal=load(OUT/'delivery_manifest.json')
actual={p.relative_to(OUT).as_posix():sha(p) for p in OUT.rglob('*') if p.is_file() and p.name!='delivery_manifest.json'}
assert actual==seal['package_files']
for path,h in seal['external_delivery_files'].items():assert sha(ROOT/path)==h,path
src=load(OUT/'source_manifest.json');pkg=ROOT/src['package_root']
actual={p.relative_to(pkg).as_posix():sha(p) for p in pkg.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(pkg).parts)}
assert actual==src['files']
old=load(ROOT/src['parent_source_manifest']['path'])
assert sha(ROOT/src['parent_source_manifest']['path'])==src['parent_source_manifest']['sha256']
changed=sorted(k for k,h in old['files'].items() if actual[k]!=h)
assert changed==sorted(src['changed_production_files']) and len(changed)==2
assert set(old['files'])==set(actual)
for ref in src['protected_files']:
    assert sha(ROOT/ref['path'])==ref['sha256'],ref['path']
before=load(OUT/'before_fix_probe.json');after=load(OUT/'after_fix_probe.json')
assert before['status']=='FAIL_CONFIRMED_BEFORE_FIX' and before['exception_type']=='decimal.InvalidOperation'
assert before['input_sha256']==after['input_sha256']
r=after['returned'];assert r['status']=='ERROR' and r['spaces']==[] and r['surface'] is None
assert r['error']['code']=='UNSUPPORTED_GEOMETRY_NUMBER'
checks=load(OUT/'checks.json');assert checks['issue_id']=='QA-GP1-E01'
assert all(x['status']=='PASS' for x in checks['items'])
assert checks['independent_qa']=='PENDING' and checks['GP2']=='NOT_RUN_NOT_ADMITTED'
h=load(OUT/'handoff.json');assert h['stop'] and h['next_stage_admission']=='INDEPENDENT_QA_ONLY'
assert not h['old_manifest_resigned']
print(json.dumps(dict(status='PASS_READ_ONLY_FIX_DELIVERY',source_files=len(actual),changed=changed,
                      old_failure_preserved=True,qa='PENDING',no_algorithm_rerun=True),indent=2))

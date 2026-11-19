from pathlib import Path
import hashlib, json, subprocess
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p, geometry_kernel_completion as c
from semantic_pallet_planner.jev_select.contracts import digest,validate_schema
from semantic_pallet_planner.jev_select.geometry_native_protocol import wire
from semantic_pallet_planner.jev_select.candidate_backends import _identity
root=Path('semantic_pallet_planner')
base=root/'outputs'
new=base/'GEOM_CANDIDATES_GP5_P2_R1_EXTERNAL_REVIEW_BINDING_20261119_01'
old=base/'GEOM_CANDIDATES_GP5_P2_REAL_MONITOR_PREPARATION_20261119_01'
load=lambda f: json.loads(f.read_bytes())
rawsha=lambda raw: hashlib.sha256(raw).hexdigest()
src=root/'src/semantic_pallet_planner'
head='942303143502621b89a7a6be66ac6ef550cf90ff'
def blob(rev,path):
    return subprocess.check_output(['git','show',f'{rev}:{path}'])
def manifest(path,revision):
    rows=load(path)['files']
    for row in rows:
        data=blob(revision,row['path'])
        assert rawsha(data)==row['sha256'] and len(data)==row.get('size_bytes',row.get('bytes')),row['path']
    return len(rows)
n=manifest(new/'delivery_manifest.json','2c4f8e87dca43452ea7f5d643f81d6d6b56ee372'); print('current manifest entries',n)
assert manifest(old/'delivery_manifest.json','34bc67d2')==27
assert manifest(base/'GEOM_CANDIDATES_GP5_P2_REAL_MONITOR_PREPARATION_QA_20261119_01/delivery_manifest.json',head)==6
history=load(new/'historical_identity.json')['files']
assert len(history)==31 and all(rawsha(Path(f).read_bytes())==h for f,h in history.items())
before,after=(load(new/name) for name in ('source_before.json','source_manifest.json'))
files={str(f.relative_to(src)):rawsha(f.read_bytes()) for f in src.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(src).parts)}
assert len(files)==591 and files==after['files']
assert _identity()['source_identity']==after['source_identity']==digest(files)
assert before['files']==load(old/'source_manifest.json')['files']
assert len(before['files'])==591 and digest(before['files'])==before['source_identity']
assert {f for f,h in files.items() if h!=before['files'][f]}=={'jev_select/packaging_geometry_protocol.py','jev_select/geometry_kernel_completion.py'}
plan=load(new/'acceptance_plan_DRAFT.json')
validate_schema(wire(plan,'geometry_order_plan_v1'),plan)
assert plan['status']=='DRAFT' and plan['call_ledger_path'] is None and plan['source_identity']==after['source_identity']
assert digest(plan)==load(new/'identity_receipt.json')['new_draft_digest']
fixture={**plan,'environment_digest':digest(p.environment())}
p.validate_order_plan(fixture)
for task,case in zip(plan['tasks'],('K01','K02'),strict=True):
    raw=(new/f'{case}_task.json').read_bytes()
    assert raw==(old/f'{case}_task.json').read_bytes()
    assert p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=task['raw_sha256'])['identity']==task
coverage=c.required_coverage(plan)
assert coverage==load(new/'required_coverage.json')
main=load(new/'matrix_DRAFT.json')['rows']
assert len(main)==4 and [{k:r[k] for k in x} for r,x in zip(main,coverage['primary'],strict=True)]==coverage['primary']
assert all(r['actual']=='NOT_RUN' and Path(r['raw_input']).is_file() and r['monitor_evidence_required']=='REAL_KERNEL' for r in main)
resumes=load(new/'recovery_DRAFT.json')['rows']
assert len(resumes)==6 and [{k:r[k] for k in ('job_id','phase')} for r in resumes]==coverage['recovery']
assert all(r['status']=='NOT_RUN' and r['generation_publication_selection']==[0,0,0] for r in resumes)
assert sum(r['new_assessment'] for r in resumes)==2 and sum(r['new_commit'] for r in resumes)==4
budget=load(new/'budget_PROPOSAL.json')
assert budget['status']=='PROPOSAL_NOT_AUTHORIZATION' and (plan['assessment_limit'],plan['solver_limit'])==(8,128)
assert len(load(new/'run_denominator_NOT_RUN.json')['rows'])==4 and all(r['status']=='NOT_RUN' for r in load(new/'run_denominator_NOT_RUN.json')['rows'])
assert set(load(new/'call_accounting.json')['actual'].values())=={0}
print('33 historical manifest entries, 31 unchanged historical files, 591 production files; DRAFT 4+6, 8/128 proposal; all actual counts zero.')

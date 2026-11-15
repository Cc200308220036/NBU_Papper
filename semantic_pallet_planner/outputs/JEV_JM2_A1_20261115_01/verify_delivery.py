"""Read-only A1 final manifest, feature/provenance and source protection checks."""
import base64,hashlib,json
from pathlib import Path
from verify_saved_public import ROOT,OUT,BASE,read,checked,pointer,m

manifest=read(OUT/'delivery_manifest.json')
for row in manifest['files']:
    p=ROOT/row['path'];raw=p.read_bytes()
    assert len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256'],row['path']
assert not any('SKILL/' in row['path'] for row in manifest['files'])
raw_log=read(OUT/'tests_attempt_01.stderr.raw.json');raw=base64.b64decode(raw_log['raw_base64'])
assert len(raw)==raw_log['bytes'] and hashlib.sha256(raw).hexdigest()==raw_log['sha256']
assert (OUT/'tests_attempt_01.stderr').read_text()=='\n'.join(line.rstrip() for line in raw.decode().splitlines())+'\n'
identity=read(OUT/'source_identity.json');source=read(OUT/'source_manifest.json')
package=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
for path,sha in source.items():assert hashlib.sha256((package/path).read_bytes()).hexdigest()==sha
assert m.digest(source)==identity['source_digest']
old=read(BASE/'JEV_JM1_B2_FREEZE_CLOSURE_20261112_01/source_manifest.json')
changed=[k for k,v in old.items() if source.get(k)!=v]
assert set(changed)=={'jev_select/packaging_versions.py','jev_select/contracts.py'}
for name in ('contracts.py','packaging_versions.py'):
    assert hashlib.sha256((OUT/'entry_source_bytes'/name).read_bytes()).hexdigest()==old['jev_select/'+name]
origins=read(OUT/'field_origin_index.json');saved=read(OUT/'saved_public_validation.json')
assert len(origins['points'])==len(saved['points'])==5
for p in saved['points']:
    folder=OUT/'saved_public_checks'/p['point_id'];h=read(folder/'historical_input.json');c=read(folder/'current_input.json')
    hs=read(folder/'historical_signature.json');cs=read(folder/'current_signature.json');b=read(folder/'action_contrast_binding.json')
    assert m.build_signature(h)==hs and m.build_signature(c)==cs
    assert hs['features']==cs['features']
    assert m.bind_contrast(h,b['roles']['A']['exact_action']['candidate_id'],b['roles']['B']['exact_action']['candidate_id'],current=c)==b
    assert b['status']=='AMBIGUOUS_DIAGNOSTIC' and b['execution_eligible'] is False
for p in origins['points']:
    for feature in p['features'].values():
        for r in feature['historical']+feature['current']+[feature['output']]:pointer(checked(r),r['pointer'])
    for role in p['action_roles'].values():
        for k in ('saved_action','current_action'):pointer(checked(role[k]),role[k]['pointer'])
assert read(OUT/'scenario_feature_spec.json')==m.feature_spec()
assert read(OUT/'acceptance.json')['next_stage_admission']=='INDEPENDENT_QA_ONLY'
assert all(x==0 for x in read(OUT/'handoff.json')['actual_operations'].values())
for point in read(OUT/'inherited_evidence_boundary.json')['points']:
    if point['point_id'].startswith('P01'):assert point['repeat_conflict']
    if point['point_id'].startswith('P04'):assert not point['repeat_registered']
report=ROOT/read(OUT/'handoff.json')['report'];assert report.exists()
assert report.name in report.with_name('README.md').read_text()
print(json.dumps(dict(status='PASS',manifest_files=len(manifest['files']),source_files=len(source),
      inherited_existing_source_changes=changed,old_schemas_unchanged=True,real_public_points=5,
      same_function_same_population=True,originals_not_resigned=True,model_calls=0,LP=0)))

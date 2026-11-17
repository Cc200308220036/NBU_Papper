"""N1 bounded hand constructions and byte faults, never a public order run.

Writes this new package only. No legacy collector/fixture is overwritten.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path.cwd()
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'semantic_pallet_planner/tests/unit'))
import test_geometry_runtime_n1 as t
from semantic_pallet_planner.jev_select.geometry_runtime_input import local_identity


def write(name,value):
    path=OUT/name
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(t.c.encode(value))


def blob(name,raw):
    path=OUT/name
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(raw)


def shafile(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


states={name:t.current_scene(t.SCENES[name]) for name in ('empty','platform','three','nonstackable')}
states['rounded_ledger']=t.rounded_ledger_scene()
states['native_identity']=t.current_scene(t.scene([t.placed('base',-0.0,0.0,0,2,2,2)]))
states['real_height_disagreement']=t.current_scene(t.scene(buffer=[t.item(h=2.0004)]))
expected={'empty':'OK','platform':'OK','three':'OK','nonstackable':'OK_EMPTY',
          'rounded_ledger':'OK','native_identity':'OK','real_height_disagreement':'ERROR'}
summary=[]
for name,state in states.items():
    before=t.c.encode(state)
    n,g,b=t.snapshot(state)
    v=t.validate(n,g,b,identities=t.IDENTITIES,current_state=state,
                 observation=t.observation(state,t.INSTRUCTION,[]))
    r=t.runtime_generate(g,native_snapshot_raw=n,binding=b,identities=t.IDENTITIES)
    assert t.c.encode(state)==before
    assert r['status']==expected[name],(name,r['error'])
    if name=='real_height_disagreement':
        assert r['error']['code']=='PHYSICAL_CHECK_DISAGREEMENT' and r['candidates']==[]
    for row in r['audit']['items']:
        if r['status']!='ERROR':assert row['final_candidates']<=16
    assert len(r['candidates'])<=48
    blob(f'cases/{name}/B_native.json',n)
    blob(f'cases/{name}/B_geometry.json',g)
    write(f'cases/{name}/binding.json',b)
    write(f'cases/{name}/result.json',r)
    summary.append({'case':name,'status':r['status'],'error':r['error'],
                    'final_candidates':len(r['candidates']),
                    'native_sha256':t.c.sha(n),'geometry_sha256':t.c.sha(g),
                    'binding_digest':t.digest(b),'input_state_unchanged':True,
                    'scope':'hand-constructed current state; real original physics; no PCT'})

n,g,b=t.snapshot(states['empty'])
faults=[]
variants=[]
geo=t.c.decode(g);geo['payload']['buffer_items'][0]['mass_kg']='2'
variants.append(('changed_geometry_leaf',n,t.c.encode(geo),b,'RUNTIME_SNAPSHOT_MISMATCH'))
geo=t.c.decode(g);geo['profile']='geometry_runtime_binary64_exact_v1'
variants.append(('wrong_profile',n,t.c.encode(geo),b,'RUNTIME_INPUT_INVALID'))
variants.append(('duplicate_json_key',n,g[:-1]+b',"profile":"duplicate"}',b,'RUNTIME_INPUT_INVALID'))
variants.append(('nonzero_underflow',n.replace(b'"mass_kg":1',b'"mass_kg":1e-999',1),g,b,'RUNTIME_NUMBER_UNREPRESENTABLE'))
bad=copy.deepcopy(b);bad['source_manifest_digest']='0'*64
variants.append(('source_identity_drift',n,g,bad,'RUNTIME_SNAPSHOT_MISMATCH'))
for name,native,geometry,binding,code in variants:
    r=t.runtime_generate(geometry,native_snapshot_raw=native,binding=binding,identities=t.IDENTITIES)
    assert r['status']=='ERROR' and r['candidates']==[] and r['error']['code']==code,(name,r)
    blob(f'faults/{name}/B_native.json',native)
    blob(f'faults/{name}/B_geometry.json',geometry)
    write(f'faults/{name}/binding.json',binding)
    write(f'faults/{name}/result.json',r)
    faults.append({'case':name,'error':r['error'],'scope':'deliberately invalid byte/binding fixture; no physical checker stub'})

a=t.placed('a',0,0,0,4,4,2)
a['supported_load_kg']=1
upper=t.placed('b',0,0,1.9999999999999998,4,4,2)
upper['support_fractions']=[{'item_id':'a','fraction':1.0}]
conflict=t.current_scene(t.scene([a,upper]))
try:
    t.snapshot(conflict)
except t.GeometryError as exc:
    assert exc.code=='RUNTIME_EXACT_STATE_CONFLICT'
    write('faults/exact_prefix_conflict/current_state.json',conflict)
    write('faults/exact_prefix_conflict/error.json',{'code':exc.code,'detail':exc.detail,
          'stage':'capture validation, no candidate generation','fixture':'tiny positive overlap; no snapping'})
else:
    raise AssertionError('exact conflicting prefix accepted')

legacy=[]
old=ROOT/'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP2_20261117_01/constructed'
for name in ('empty','platform','noninteger'):
    input_path=old/f'{name}_input.json';result_path=old/f'{name}_result.json'
    result=t.generate(input_path.read_bytes())
    assert t.c.encode(result)==t.c.encode(json.loads(result_path.read_bytes()))
    write(f'legacy_regression/{name}_actual.json',result)
    legacy.append({'case':name,'input_path':str(input_path.relative_to(ROOT)),
                   'input_sha256':shafile(input_path),'saved_result_sha256':shafile(result_path),
                   'complete_semantics_order_audit_equal':True})

assert not any(n.startswith('semantic_pallet_planner.jev_select.stability') for n in sys.modules)
write('case_summary.json',{'version':'geometry_n1_case_summary_v1','cases':summary,'faults':faults,
                          'legacy_regression':legacy,'collection_generation_calls':len(states)+len(variants)+len(legacy),
                          'counts_scope':'collector only; tests have separate bounded calls in unittest logs',
                          'model_calls':0,'PCT_calls':0,'orders':0,
                          'test_double_physics':False,'stability_modules_imported':False})
config=t.runtime_config()
write('config_snapshot.json',config)
write('local_identity.json',{'identity':local_identity(config),'environment':t.c.environment(),
                           'fixture_external_identities':t.IDENTITIES,
                           'external_identity_scope':'synthetic labels, not a real dataset/task/monitor admission'})
package=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
source={p.relative_to(package).as_posix():shafile(p) for p in sorted(package.rglob('*'))
        if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(package).parts)}
prior=json.loads((ROOT/'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP2_20261117_01/source_manifest.json').read_bytes())['files']
changed=[n for n in prior if source.get(n)!=prior[n]]
added=sorted(set(source)-set(prior))
assert changed==['planner/space_candidates/generator.py'],changed
assert len(added)==3,added
write('source_manifest.json',{'version':'geometry_n1_source_manifest_v1','files':source,
       'count':len(source),'changed_existing':changed,'added':added,
       'old_source_files_unchanged':len(prior)-len(changed),'historical_manifests_resigned':False})
for name in changed+added:
    blob('source_snapshot/'+name,(package/name).read_bytes())
print(json.dumps({'normal_constructions':len(states),'byte_faults':len(variants),
                  'complete_legacy_comparisons':len(legacy),'source_files':len(source),
                  'real_height_error':'PHYSICAL_CHECK_DISAGREEMENT','PCT_calls':0,'models':0},ensure_ascii=False))

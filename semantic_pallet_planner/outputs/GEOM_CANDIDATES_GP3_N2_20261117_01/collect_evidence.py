"""N2 current hand states and request artifacts only. No run_episode or solver."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types

ROOT=Path.cwd();OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'semantic_pallet_planner/tests/unit'))
import test_geometry_public_n2 as n2
t=n2.t


def write(name,value):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(t.c.encode(value))


def blob(name,raw):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)


summary=[]
cases={'empty':t.current_scene(),'rounded_ledger':t.rounded_ledger_scene(),
       'nonstackable':t.current_scene(t.SCENES['nonstackable']),
       'singleton':t.current_scene(t.scene(length=2,width=4))}
for name,state in cases.items():
    before=t.c.encode(state);pair=[]
    write(f'inputs/{name}_current_state.json',state)
    for backend in n2.GEOMETRY_BACKENDS:
        cfg=n2.config(backend);times={}
        req,pol,bundle,ctx=n2.inputs(state,cfg,job='construction_'+backend,timings=times)
        n2.validate_context(ctx,req,bundle,cfg)
        audit=bundle.audit
        pair.append((audit['native_bytes_hex'],audit['geometry_bytes_hex'],audit['common_binding'],audit['common_admission']))
        base=f'cases/{name}/{backend}'
        blob(base+'/B_native.json',bytes.fromhex(audit['native_bytes_hex']))
        blob(base+'/B_geometry.json',bytes.fromhex(audit['geometry_bytes_hex']))
        write(base+'/config.json',cfg);write(base+'/bundle.json',bundle.data)
        write(base+'/audit.json',audit);write(base+'/telemetry.json',bundle.telemetry)
        write(base+'/context.json',ctx.data);write(base+'/observation.json',req)
        write(base+'/public_policy.json',pol.data);write(base+'/timings.json',times)
        body=ctx.data['request_body']
        write(base+'/request.json',body)
        assert body is None or len(t.c.encode(body))<=96000
        assert t.c.encode(state)==before
        summary.append({'case':name,'backend':backend,'route':ctx.data['route'],
            'final_candidates':len(bundle.data['physical_candidates']),'common_input_digest':bundle.data['common_input_digest'],
            'backend_binding_digest':bundle.data['backend_binding_digest'],
            'request_bytes':None if body is None else len(t.c.encode(body)),
            'input_state_unchanged':True,'generation_status':'OK' if bundle.data['physical_candidates'] else 'OK_EMPTY'})
    assert pair[0]==pair[1], 'backend-dependent common artifacts'

badledger=t.rounded_ledger_scene();badledger['placed_items'][0]['supported_load_kg']=7
height=t.current_scene(t.scene(buffer=[t.item(h=2.0004)]))
errors=[]
for name,state,scope in [('bad_saved_ledger',badledger,'COMMON_INPUT_ERROR'),
                         ('real_height_disagreement',height,'BACKEND_INTERNAL_ERROR')]:
    write(f'inputs/{name}_current_state.json',state)
    before=t.c.encode(state)
    for backend in n2.GEOMETRY_BACKENDS:
        cfg=n2.config(backend)
        try:n2.inputs(state,cfg)
        except n2.GeometryConstructionError as exc:
            assert exc.scope==scope
            if name=='real_height_disagreement':assert exc.code=='PHYSICAL_CHECK_DISAGREEMENT'
            base=f'failures/{name}/{backend}'
            write(base+'/audit.json',exc.audit);write(base+'/config.json',cfg)
            write(base+'/telemetry.json',exc.telemetry)
            write(base+'/error.json',{'scope':exc.scope,'code':exc.code,'detail':str(exc),
                'bundle_returned':False,'fallback':False,'state_unchanged':t.c.encode(state)==before,
                'physical_checker_stub':False})
            errors.append({'case':name,'backend':backend,'scope':exc.scope,'code':exc.code})
        else:raise AssertionError('fault not rejected')
        assert t.c.encode(state)==before

baseline_raw=subprocess.check_output(['git','show','d69d904f09686c323edcf949f7e01022a7d564cb:semantic_pallet_planner/src/semantic_pallet_planner/jev_select/candidates.py'])
blob('baseline_snapshot/reviewed_candidates.py',baseline_raw)
module=types.ModuleType('semantic_pallet_planner.jev_select._n2_legacy_evidence')
module.__package__='semantic_pallet_planner.jev_select'
exec(compile(baseline_raw,'reviewed_candidates.py','exec'),module.__dict__)
legacy=[]
for name in ('empty','platform'):
    s=t.current_scene(t.SCENES[name]);req=t.observation(s,t.INSTRUCTION,[])
    old=module.CandidateProvider().build(s,req,n2.generator_config()).data
    now=n2.CandidateProvider().build(s,req,n2.generator_config()).data
    assert t.c.encode(old)==t.c.encode(now)
    write('legacy/'+name+'_reviewed.json',old);write('legacy/'+name+'_current.json',now)
    legacy.append({'case':name,'full_canonical_bytes_equal':True,'source_commit':'d69d904f09686c323edcf949f7e01022a7d564cb',
        'scope':'reviewed provider implementation with identical current config/dependencies; not historical order replay'})

assert not any(x.startswith(('semantic_pallet_planner.jev_select.stability.exact_adapter',
                            'semantic_pallet_planner.jev_select.stability.balance_adapter','scipy.optimize')) for x in sys.modules)
write('case_summary.json',{'version':'geometry_n2_case_summary_v1','cases':summary,'errors':errors,
    'legacy_provider':legacy,'request_size_overflow_test':'EXPLICIT_FACTS_TEST_DOUBLE_IN_UNIT_NOT_REAL_STATE',
    'collector_provider_constructions':16,'provider_count_scope':'8 positive/normal-empty + 4 errors + 4 legacy baseline/current calls; tests counted separately',
    'model_calls':0,'orders':0,'PCT_LP_calls':0,
    'parent_A03':'PARTIAL','GP4':'NOT_READY'})
pkg=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
source={p.relative_to(pkg).as_posix():sha(p) for p in sorted(pkg.rglob('*')) if p.is_file()
        and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(pkg).parts)}
prior=json.loads((ROOT/'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N1_20261117_01/source_manifest.json').read_bytes())['files']
changed=[k for k in prior if source.get(k)!=prior[k]];added=sorted(set(source)-set(prior))
write('source_manifest.json',{'version':'geometry_n2_source_manifest_v1','files':source,'count':len(source),
    'changed_existing':changed,'added':added,'unchanged_N1_files':len(prior)-len(changed),
    'historical_manifests_resigned':False})
for name in changed+added:blob('source_snapshot/'+name,(pkg/name).read_bytes())
for name in ('test_geometry_public_n2.py','test_geometry_runtime_n1.py','test_space_candidates_gp2.py'):
    blob('test_snapshot/'+name,(ROOT/'semantic_pallet_planner/tests/unit'/name).read_bytes())
print(json.dumps({'paired_manual_states':4,'successful_bundles':8,'classified_failures':4,
    'legacy_full_byte_comparisons':2,'production_files':len(source),'changed_existing':changed,
    'added':added,'model_calls':0,'run_episode_calls':0,'PCT_LP_calls':0},ensure_ascii=False))

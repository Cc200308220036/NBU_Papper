"""Independent stdlib saved-evidence and static binding witness. No production calls."""
from pathlib import Path
from decimal import Decimal
from fractions import Fraction
import ast,hashlib,json,subprocess

DEV=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N2_20261117_01')
PKG=Path('semantic_pallet_planner/src/semantic_pallet_planner')
HEAD='2b47a1fa550262761d3155e428f9a95b5ebf1611'
def encode(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(v):return hashlib.sha256(v).hexdigest()
def digest(v):return sha(encode(v))
def read(p):return json.loads(p.read_bytes())
def seal(v):assert v['record_digest']==digest({k:x for k,x in v.items() if k!='record_digest'})
def num(v):
    assert type(v) in (int,float)
    d=Decimal(v) if type(v) is int else Decimal(repr(v));assert d.is_finite()
    if not d:return '0'
    s=format(d,'f');return s.rstrip('0').rstrip('.') if '.' in s else s
ITEM={'item_id','dimensions_mm','mass_kg','stackable','top_load_limit_kg_synthetic'}
PLACED=ITEM|{'pose','oriented_size_mm','supported_load_kg','support_fractions'}
def payload(s):return {'container':{k:s['container'][k] for k in ('length_mm','width_mm','max_height_mm','max_payload_kg')},'placed_items':[{k:p[k] for k in PLACED} for p in s['placed_items']],'buffer_items':[{**{k:p['item'][k] for k in ITEM},'arrival_index':p['arrival_index']} for p in sorted(s['pending_items'],key=lambda x:x['arrival_index'])]}
def convert(v,k=''):
    if type(v) in (int,float):return v if k in ('yaw_deg','arrival_index') else num(v)
    if type(v) is dict:return {k:convert(x,k) for k,x in v.items()}
    if type(v) is list:return [convert(x,k) for x in v]
    return v
m=read(DEV/'delivery_manifest.json')
for row in m['files']:
    p=Path(row['path']);raw=p.read_bytes()
    if sha(raw)!=row['sha256'] and p.as_posix()=='docs/03_阶段产出分析/几何规划模块/README.md':
        raw=subprocess.run(['git','show',HEAD+':'+p.as_posix()],check=True,capture_output=True).stdout
    assert sha(raw)==row['sha256'] and len(raw)==row['size_bytes'],str(p)
src=read(DEV/'source_manifest.json')['files']
actual={p.relative_to(PKG).as_posix():sha(p.read_bytes()) for p in PKG.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(PKG).parts)}
assert src==actual
guards=[]
for filename,names in [('episode.py',{'run_episode','_run_episode_v2'}),('execution.py',{'commit_physical'}),('selector.py',{'result'})]:
    nodes=ast.parse((PKG/'jev_select'/filename).read_text()).body
    for node in nodes:
        if isinstance(node,ast.FunctionDef) and node.name in names:
            assert isinstance(node.body[1],ast.Expr) and node.body[1].value.func.id=='reject_geometry_execution'
            guards.append(filename+':'+node.name)
assert len(guards)==4
cs=read(PKG/'jev_select/schemas/config_v14.schema.json')
assert cs['additionalProperties'] is False and cs['properties']['construction_only']['const'] is True
assert cs['properties']['execution_version']['const']=='geometry_construction_only_v1'
pairs={};rows=[];total=0
for p in sorted((DEV/'cases').glob('*/*')):
    nraw=(p/'B_native.json').read_bytes();graw=(p/'B_geometry.json').read_bytes()
    n,g,a,b,cfg,ctx,body=[read(p/name) for name in ('B_native.json','B_geometry.json','audit.json','bundle.json','config.json','context.json','request.json')]
    assert encode(n)==nraw and encode(g)==graw
    assert encode(g['payload'])==encode(convert(payload(n['current_state'])))
    common,adm,back=a['common_binding'],a['common_admission'],a['backend_binding']
    for v in (common,adm,back):seal(v)
    assert sha(nraw)==common['native_snapshot_sha256']==g['native_snapshot_sha256']
    assert sha(graw)==common['geometry_input_sha256']
    assert common['source_identity']==digest(src)==cfg['runtime_identity']['source_identity']
    assert common['geometry_values_digest']==digest(g['payload'])
    assert g['profile']==common['profile']=='geometry_runtime_shortest_decimal_v1'
    assert a['native_bytes_hex']==nraw.hex() and a['geometry_bytes_hex']==graw.hex()
    assert digest(a)==b['geometry_audit_digest']
    assert digest(common)==b['common_input_digest']==back['common_input_digest']==adm['common_input_digest']
    assert digest(adm)==back['admission_digest'] and adm['status']=='PASS'
    assert digest(back)==b['backend_binding_digest']
    assert digest(cfg)==back['config_digest']==ctx['local_binding']['config_digest']
    assert cfg['candidate_backend']==b['candidate_backend']==back['candidate_backend']
    assert cfg['generator_config_digest']==b['generator_config_digest']==back['generator_config_digest']
    pool=b['physical_candidates'];assert encode(pool)==encode(b['selectable_candidates'])
    assert digest(pool)==b['physical_digest']==b['selectable_digest']==a['final_candidates_digest']
    assert encode(a['generation_counts'])==encode(b['generation_counts'])
    assert sum(r['returned'] for r in b['generation_counts'])==len(pool)<=48
    assert len({c['candidate_id'] for c in pool})==len(pool)
    for item in n['current_state']['pending_items']:
        assert sum(c['pick_item_id']==item['item']['item_id'] for c in pool)<=16
    assert encode(body)==encode(ctx['request_body'])
    for fld,key in [('mapping_digest','display_mapping'),('model_state_digest','model_state'),('criteria_digest','criteria'),('request_body_digest','request_body')]:assert ctx['local_binding'][fld]==digest(ctx[key])
    mapped=ctx['display_mapping'];assert set(mapped)==set(ctx['criteria']) and len(mapped)==len(pool)
    byid={c['candidate_id']:c for c in pool}
    for label,ref in mapped.items():
        c=byid[ref['candidate_id']];assert ref['candidate_digest']==digest(c)
        assert encode(ctx['criteria'][label]['pose'])==encode(c['pose'])
    if body is not None:
        assert len(encode(body))<=96000 and body['state']['memories']==[]
        assert not any(word in encode(body).decode() for word in ('geometry_audit','e2_original_v1','ems_surface_hybrid_v1','profile','host','monitor','SURFACE_CORNER'))
    else:assert ctx['route'] in ('SINGLETON_BYPASS','STOP_NO_PHYSICAL_CANDIDATE')
    saved=[{k:x[k] for k in ('item_id','supported_load_kg','support_fractions')} for x in n['current_state']['placed_items']]
    assert encode(saved)==encode(adm['ledger_views']['saved'])
    pairs.setdefault(p.parent.name,[]).append((nraw,graw,encode(common),encode(adm)))
    rows.append({'case':p.parent.name,'backend':cfg['candidate_backend'],'final_candidates':len(pool),'route':ctx['route'],'request_bytes':len(encode(body)) if body is not None else None})
    total+=len(pool)
assert len(pairs)==4 and all(len(v)==2 and v[0]==v[1] for v in pairs.values())
errors=[]
for p in sorted((DEV/'failures').glob('*/*/error.json')):
    e=read(p);a=read(p.parent/'audit.json')
    assert not e['bundle_returned'] and not e['fallback'] and e['state_unchanged']
    if e['scope']=='COMMON_INPUT_ERROR':assert a['backend_binding'] is None
    else:assert e['code']=='PHYSICAL_CHECK_DISAGREEMENT' and a['common_admission']['status']=='PASS'
    errors.append({'path':str(p),'scope':e['scope'],'code':e['code']})
for name in ('empty','platform'):assert encode(read(DEV/'legacy'/f'{name}_reviewed.json'))==encode(read(DEV/'legacy'/f'{name}_current.json'))
# Witness inputs are real archived records. This computes their identities only;
# acceptance through production ContextBuilder is a SOURCE DERIVATION, not a run.
p=DEV/'cases/empty';cfg=read(p/'e2_original_v1/config.json');audit=read(p/'ems_surface_hybrid_v1/audit.json');b=read(p/'ems_surface_hybrid_v1/bundle.json')
witness={'issue':'GP3-N2-BIND-01','classification':'STATIC_SOURCE_DERIVATION_WITH_ARCHIVED_INPUTS_NOT_PRODUCTION_REPRODUCTION','external_config_path':str(p/'e2_original_v1/config.json'),'bundle_path':str(p/'ems_surface_hybrid_v1/bundle.json'),'audit_path':str(p/'ems_surface_hybrid_v1/audit.json'),'same_config_version':cfg['version']==audit['config']['version'],'same_observation_digest':read(p/'e2_original_v1/observation.json')['observation_digest']==b['observation_digest'],'external_backend':cfg['candidate_backend'],'bundle_backend':b['candidate_backend'],'external_config_digest':digest(cfg),'bundle_backend_bound_config_digest':audit['backend_binding']['config_digest'],'required_config_identity_equal':digest(cfg)==audit['backend_binding']['config_digest'],'required_generator_config_equal':cfg['generator_config_digest']==b['generator_config_digest'],'missing_edge':'external config -> bundle.audit.config/backend_binding.config_digest','source_trace':['ContextBuilder.__init__ validates external config Schema only','PublicBusinessGuard.filter checks v14 version and internally validates bundle using its own audit.config','build_context uses external config_digest/runtime_identity but copies bundle backend_binding_digest/generator_config_digest','validate_runtime_context checks external config against context and bundle binding against context separately; reconstruction repeats same mixed pair'],'production_ContextBuilder_calls':0,'candidate_generation':0}
assert witness['same_config_version'] and witness['same_observation_digest']
assert not witness['required_config_identity_equal'] and not witness['required_generator_config_equal']
print(json.dumps({'status':'PASS_ARCHIVE_CHECKS_WITH_BLOCKING_STATIC_FINDING','manifest_files':len(m['files']),'source_files':len(src),'paired_hand_states':4,'final_saved_candidates':total,'rows':rows,'saved_errors':errors,'legacy_saved_pairs':2,'execution_guards_checked_static_only':guards,'static_binding_witness':witness,'production_imports':0,'candidate_generation':0,'run_episode_calls':0,'PCT_LP_models':0},ensure_ascii=False,indent=2))

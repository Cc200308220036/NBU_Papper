"""Independent stdlib saved-fact checks, no production imports/candidate calls."""
from pathlib import Path
from decimal import Decimal
import copy,hashlib,json,subprocess,collections,ast
DEV=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N2_R1_20261117_01')
OUT=Path('semantic_pallet_planner/outputs')
PKG=Path('semantic_pallet_planner/src/semantic_pallet_planner')
HEAD='81a9a6ecb4023b2eaa7a8b0fe82d9e550b931f38'
SYNC='ce67791e146a3660725ef734a568b4d7dee1c42b'
OLD='2b47a1fa550262761d3155e428f9a95b5ebf1611'
NAV='docs/03_阶段产出分析/几何规划模块/README.md'
def read(p):return json.loads(p.read_bytes())
def enc(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(b):return hashlib.sha256(b).hexdigest()
def digest(v):return sha(enc(v))
def blob(rev,path):return subprocess.run(['git','show',rev+':'+path],check=True,capture_output=True).stdout
s=read(DEV/'source_manifest.json')
actual={p.relative_to(PKG).as_posix():sha(p.read_bytes()) for p in PKG.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(PKG).parts)}
assert actual==s['files'] and len(actual)==534
oldsrc=read(OUT/'GEOM_CANDIDATES_GP3_N2_20261117_01/source_manifest.json')['files']
changed=sorted(k for k in oldsrc if actual.get(k)!=oldsrc[k])
assert changed==sorted(s['changed_existing']) and len(changed)==3 and set(actual)==set(oldsrc)
for k in changed:
    assert sha((DEV/'source_snapshot'/k).read_bytes())==actual[k]
    assert sha((DEV/'baseline_source'/k).read_bytes())==oldsrc[k]
# Pin only known externally changed source/navigation to its original Git identity.
manifest_counts={}
for name,rev in [('GEOM_CANDIDATES_GP3_N2_20261117_01',OLD),('GEOM_CANDIDATES_GP3_N2_QA_20261117_01',SYNC),('GEOM_CANDIDATES_GP3_N2_R1_20261117_01',HEAD)]:
    m=read(OUT/name/'delivery_manifest.json')
    for row in m['files']:
        p=Path(row['path']);data=p.read_bytes()
        if sha(data)!=row['sha256']:
            if p.as_posix()==NAV or (name=='GEOM_CANDIDATES_GP3_N2_20261117_01' and p.as_posix() in {str(PKG/k) for k in changed}):data=blob(rev,p.as_posix())
        assert sha(data)==row['sha256'],(name,str(p))
        assert len(data)==row['size_bytes']
    manifest_counts[name]=len(m['files'])
# Exact archived input digests and four entry results before/after.
before,after=read(DEV/'before_reproduction.json'),read(DEV/'after_same_input.json')
oldempty=OUT/'GEOM_CANDIDATES_GP3_N2_20261117_01/cases/empty'
oldcfg=read(oldempty/'e2_original_v1/config.json');old_audit=read(oldempty/'ems_surface_hybrid_v1/audit.json')
assert before['input_config_digest']==after['input_config_digest']==digest(oldcfg)
assert before['bundle_config_digest']==after['bundle_config_digest']==digest(old_audit['config'])
assert [r['entry'] for r in before['rows']]==[r['entry'] for r in after['rows']]
assert len(before['rows'])==4 and all(r['result']=='ACCEPTED_MISMATCH_FAIL' for r in before['rows'])
assert all(r['result']=='REJECTED' and r['error'].startswith('geometry_config_bundle_mismatch:') for r in after['rows'])
ctx=read(DEV/'before_mismatched_context.json')
assert ctx['local_binding']['config_digest']==digest(oldcfg)
assert ctx['local_binding']['backend_binding_digest']==digest(old_audit['backend_binding'])
configs={};saved_candidates=0
for d in sorted((DEV/'current_pairs').iterdir()):
    cfg,b,a,ctx=[read(d/(n+'.json')) for n in ('config','bundle','audit','context')]
    configs[d.name]=cfg
    assert digest(cfg)==a['backend_binding']['config_digest']==ctx['local_binding']['config_digest']
    assert enc(cfg)==enc(a['config']) and cfg['candidate_backend']==b['candidate_backend']==d.name
    assert cfg['runtime_identity']['source_identity']==digest(actual)
    assert digest(a)==b['geometry_audit_digest']
    nraw=bytes.fromhex(a['native_bytes_hex']);graw=bytes.fromhex(a['geometry_bytes_hex'])
    common=a['common_binding'];admission=a['common_admission'];back=a['backend_binding']
    for row in (common,admission,back):assert row['record_digest']==digest({k:v for k,v in row.items() if k!='record_digest'})
    assert common['native_snapshot_sha256']==sha(nraw) and common['geometry_input_sha256']==sha(graw)
    assert digest(common)==b['common_input_digest']==back['common_input_digest']==admission['common_input_digest']
    assert digest(back)==b['backend_binding_digest']==ctx['local_binding']['backend_binding_digest']
    assert enc(b['physical_candidates'])==enc(b['selectable_candidates'])
    assert digest(b['physical_candidates'])==b['physical_digest']==b['selectable_digest']
    assert len(b['physical_candidates'])<=48
    for key,field in [('config_digest',None),('mapping_digest','display_mapping'),('model_state_digest','model_state'),('criteria_digest','criteria'),('request_body_digest','request_body')]:
        assert ctx['local_binding'][key]==digest(cfg if field is None else ctx[field])
    assert ctx['local_binding']['runtime_identity']==cfg['runtime_identity']
    assert ctx['local_binding']['generator_config_digest']==b['generator_config_digest']==cfg['generator_config_digest']
    body=ctx['request_body'];assert len(enc(body))<=96000
    assert not any(w in enc(body).decode() for w in ('e2_original_v1','ems_surface_hybrid_v1','geometry_audit','monitor','profile','host'))
    saved_candidates+=len(b['physical_candidates'])
# Reconstruct only CONFIG RECORDS from test recipes, never states or candidates.
rows=read(DEV/'consumer_matrix.json');assert len(rows)==170
keys=set();groups=collections.Counter();entries={'filter','ContextBuilder','direct_F0','public_facts','full_context','direct_context','context_config_bundle_only'}
for r in rows:
    name=r['case'];backend=r['backend'];cfg=copy.deepcopy(configs[backend]);frozen=copy.deepcopy(cfg)
    if name=='valid_pair':assert r['result']=='PASS' and r['config_digest']==digest(cfg);continue
    if name.startswith('cross_backend_'):cfg=copy.deepcopy(configs[name[len('cross_backend_'):]])
    elif name in ('selector','data_identity','task_identity','monitor_identity'):
        if name=='selector':cfg['selector']='local_first_test_double'
        else:cfg['runtime_identity'][name]=digest('R1_other_'+name)
        plain={k:v for k,v in cfg.items() if k!='runtime_identity'}
        cfg['runtime_identity']['strategy_identity']=digest({'config':plain,'source_identity':cfg['runtime_identity']['source_identity']})
    elif name.startswith('invalid_'):
        fld=name[len('invalid_'):];vals={'numerical_profile':'unknown','construction_only':False,'generator_config_digest':'0'*64,'max_request_bytes':95999,'unexpected':True};cfg[fld]=vals[fld]
    elif name=='source_drift':cfg['runtime_identity']['source_identity']='0'*64
    elif name=='matching_historical_source':cfg=read(oldempty/backend/'config.json');frozen=copy.deepcopy(cfg)
    else:raise AssertionError(name)
    assert r['config_digest']==digest(cfg) and r['frozen_config_digest']==digest(frozen),(name,backend)
    assert r['result']=='REJECTED' and r['entry'] in entries
    if name.startswith('cross_backend_') or name in ('selector','data_identity','task_identity','monitor_identity','source_drift'):assert r['error'].startswith('geometry_config_bundle_mismatch:')
    if name=='matching_historical_source':assert 'construction config/source/backend drift' in r['error']
    key=(name,backend,r['entry']);assert key not in keys;keys.add(key);groups[(name,backend)]+=1
assert len(keys)==168 and len(groups)==24 and all(n==7 for n in groups.values())
# Guard/contract protections remain present, checked statically, never executed.
for fn,names in [('episode.py',{'run_episode','_run_episode_v2'}),('execution.py',{'commit_physical'}),('selector.py',{'result'})]:
    for node in ast.parse((PKG/'jev_select'/fn).read_text()).body:
        if isinstance(node,ast.FunctionDef) and node.name in names:assert node.body[1].value.func.id=='reject_geometry_execution'
for log,n in [('r1_tests_01.log',5),('geometry_public_n2.log',11),('geometry_runtime_n1.log',13),('space_candidates_gp2.log',13)]:
    text=(DEV/log).read_text();assert f'Ran {n} tests' in text and '\nOK\n' in text
print(json.dumps({'status':'PASS_INDEPENDENT_SAVED_FACTS_ONLY','production_files':534,'changed_files':changed,'unchanged_files':531,'manifests':manifest_counts,'before_after_entries':4,'consumer_records':170,'rejection_combinations':24,'entries_per_combination':7,'config_recipe_digests_verified':168,'normal_pairs':2,'saved_final_candidates':saved_candidates,'original_validator':'FAIL_NAVIGATION_USES_HEAD','independent_historical_navigation':'PASS_PINNED_GIT_BLOBS','production_imports':0,'candidate_generation':0,'F0_production_calls':0,'orders_PCT_LP_models':0,'checkpoint_resume':'NOT_RUN'},ensure_ascii=False,indent=2))

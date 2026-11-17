"""Independent R1 saved-fact checks. No project imports, replay or solver."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

OUT = Path(__file__).parent
DEV = OUT.parent / 'GEOM_CANDIDATES_GP5_P1_R1_20261117_01'
SRC = Path('semantic_pallet_planner/src/semantic_pallet_planner')
HEAD = '0c7cacb2dc58fcf97c1d4a682f65fb42b9cfe377'

def read(p): return json.loads(p.read_bytes())
def sha(b): return hashlib.sha256(b).hexdigest()
def digest(v):
    return sha(json.dumps(v, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode())

manifest = read(DEV / 'delivery_manifest.json')
for r in manifest['files']:
    raw = (subprocess.check_output(['git', 'show', HEAD+':'+r['path']])
           if Path(r['path']).name == 'README.md' else Path(r['path']).read_bytes())
    assert len(raw) == r['size_bytes'] and sha(raw) == r['sha256'], r['path']
source = read(DEV / 'source_manifest.json')
current = {str(p.relative_to(SRC)):sha(p.read_bytes()) for p in SRC.rglob('*')
           if p.is_file() and p.suffix in ('.py','.json')
           and not {'tests','__pycache__'}.intersection(p.relative_to(SRC).parts)}
assert current == source['files'] and digest(current) == source['source_identity']
before = read(DEV / 'before_source_manifest.json')['files']
assert before == read(DEV.parent / 'GEOM_CANDIDATES_GP5_P1_20261117_01/source_manifest.json')['files']
modified = sorted(k for k in before if before[k] != current.get(k))
added = sorted(set(current)-set(before))
assert len(modified) == 8 and len(added) == 5 and not set(before)-set(current)
assert all(current[k] == h for k,h in before.items() if '/schemas/' in k and '_v16.' not in k
           and k not in ('jev_select/schemas/geometry_order_metrics_v1.schema.json',
                         'jev_select/schemas/geometry_order_run_v1.schema.json'))
protected = read(DEV / 'protected_identity_check.json')['protected_files']
for k,h in protected.items(): assert before[k] == current[k] == h
functions = []
for k in modified+added:
    assert (DEV/'code_snapshot'/k).read_bytes() == (SRC/k).read_bytes()
    if k.endswith('.py'):
        tree = ast.parse((SRC/k).read_text())
        functions.extend({'file':k,'name':n.name,'line':n.lineno} for n in ast.walk(tree)
                         if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)))
    else: read(SRC/k)

holes = []
def walk(v, filename, pointer=''):
    if isinstance(v,dict):
        typ = v.get('type')
        if (typ == 'object' or isinstance(typ,list) and 'object' in typ):
            if v.get('maxProperties') != 0 and not any(k in v for k in ('properties','patternProperties','additionalProperties','$ref')):
                holes.append({'file':filename,'pointer':pointer})
        for k,x in v.items(): walk(x,filename,pointer+'/'+k)
    elif isinstance(v,list):
        for i,x in enumerate(v): walk(x,filename,pointer+'/'+str(i))
for rel in modified+added:
    if '/schemas/' in rel: walk(read(SRC/rel),rel)
assert not holes

E = DEV/'final_evidence'
recovery = {}
for phase in ('SELECTED','MONITORED','COMMITTED'):
    d=read(E/'test_accounted_driver_and_recovery'/phase/'accounted_result.json')
    s=d['summary'];a=s['accounting']
    expected={'selector_calls':0,'singleton_executions':0,'monitor_entries':int(phase=='SELECTED'),
              'monitor_reuses':int(phase=='MONITORED'),'commit_attempts':int(phase!='COMMITTED'),
              'commit_successes':int(phase!='COMMITTED')}
    assert a['invocation_delta']==expected and a['cumulative']['commit_successes']==s['placed_items']==1
    assert s['completed'] and s['planned_items']==1
    recovery[phase]={'delta':expected,'cumulative':a['cumulative'],'evidence':'TEST_DOUBLE_ARCHIVE_ONLY'}
k02=read(E/'test_k01_local_first_targets_and_k02_singleton_counts/K02_accounted.json')['summary']
assert k02['accounting']['cumulative']=={'selector_calls':1,'singleton_executions':1,'monitor_entries':2,
       'monitor_reuses':0,'commit_attempts':2,'commit_successes':2}
assert k02['fixed_container_utilization']==2/3 and k02['envelope_utilization']==1
assert k02['placed_item_ratio']==k02['placed_volume_ratio']==k02['placed_mass_ratio']==1
negative=read(E/'test_completion_contract_missing_duplicate_error_only_no_commit_recovery/completion_contract_results.json')
assert len(negative['negative'])==9 and all(r['result']=='REJECTED' for r in negative['negative'])
assert len(negative['coverage']['primary'])==4 and len(negative['coverage']['recovery'])==6
assert negative['positive']=='PURE_COVERAGE_ONLY' and negative['business_dispatch']==0
for backend,y in [('e2_original_v1',-150),('ems_surface_hybrid_v1',150)]:
    chosen=read(E/'test_k01_local_first_targets_and_k02_singleton_counts'/('K01_target_'+backend+'.json'))
    assert chosen['pose']=={'x_mm':-260,'y_mm':y,'z_base_mm':0,'yaw_deg':90}
    assert chosen['oriented_size_mm']==[80,100,60]

occurrences={'checkpoints':0,'marked_monitor':0,'account_ledgers':0,'blobs':0}
def facts(v):
    if isinstance(v,dict):
        if v.get('version')=='jev_checkpoint_v16':
            assert v['record_digest']==digest({k:x for k,x in v.items() if k!='record_digest'})
            occurrences['checkpoints']+=1
        if v.get('version')=='selected_action_monitor_v1':
            assert v['result_digest']==digest(v['result'])
            assert v['credential_digest']==digest({k:x for k,x in v.items() if k!='credential_digest'})
            assert v['result']['diagnostics']['TEST_DOUBLE'] is True
            occurrences['marked_monitor']+=1
        if v.get('version')=='geometry_order_accounting_v1':
            assert [i['index'] for i in v['invocations']]==list(range(len(v['invocations'])))
            assert all(v['cumulative'][k]==sum(i['delta'][k] for i in v['invocations']) for k in v['cumulative'])
            occurrences['account_ledgers']+=1
        for x in v.values():facts(x)
    elif isinstance(v,list):
        for x in v:facts(x)
excluded_negative_contracts = []
for p in E.rglob('*.json'):
    if p.name.startswith('contract_') and 'test_completion_contract_missing_duplicate_error_only_no_commit_recovery' in p.parts:
        excluded_negative_contracts.append(str(p))
        continue
    facts(read(p))
for p in E.rglob('blobs/*'):
    if p.is_file():
        assert sha(p.read_bytes())==p.name
        occurrences['blobs']+=1
integer=read(E/'test_integer_multistep_type_conflict_is_preserved_technical_failure/integer_type_conflict.json')
assert integer['summary']['placed_items']==1 and integer['summary']['termination_reason']=='RUNTIME_INPUT_INVALID'
den=read(E/'test_real_tasks_admin_adaptation_and_formal_gates_before_episode/run_denominator.json')
assert len(den['rows'])==8 and all(r['status']=='NOT_RUN' for r in den['rows'])
result={'schema':'geometry_gp5_p1_r1_saved_qa_v1','status':'PASS_SAVED_FACTS_ONLY',
        'manifest_members':len(manifest['files']),'source_identity':source['source_identity'],
        'source_files':len(current),'modified':modified,'added':added,'protected_files':len(protected),
        'source_drift':False,'schema_unconstrained_object_nodes':holes,'functions':functions,
        'recovery':recovery,'K02_accounting':k02['accounting'],'completion_contract':negative,
        'occurrences_not_independent_cases':occurrences,'excluded_fabricated_positive_and_negative_contract_files':excluded_negative_contracts,'NUM-01':'OPEN_PRESERVED',
        'real_jobs':'8_NOT_RUN','production_imports':0,'business_execution':0,
        'limitation':'No business tests or production completion gate execution; genuine kernel instrumentation NOT_RUN'}
(OUT/'saved_evidence_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('PASS: independent source/old protection/schema structure/saved counters and digests; no production imports')

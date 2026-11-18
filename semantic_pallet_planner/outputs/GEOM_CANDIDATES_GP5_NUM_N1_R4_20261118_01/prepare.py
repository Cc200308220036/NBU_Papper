"""One-shot identity preparation only. No candidates, kernels or episodes."""
import hashlib,json,sys,subprocess,traceback,shutil
from pathlib import Path
O=Path(__file__).resolve().parent
ROOT=Path.cwd(); SRC=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
R3=O.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R3_20261118_01'
QA=O.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R3_QA_20261118_01'
def read(p):return json.loads(Path(p).read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
def write(n,v):(O/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def main():
    assert not (O/'preparation_started.json').exists(),'NO_RETRY'
    write('preparation_started.json',{'one_shot':True,'interpreter':sys.executable})
    from semantic_pallet_planner.jev_select.contracts import digest,canonical
    from semantic_pallet_planner.jev_select import geometry_order_execution as e,packaging_geometry_protocol as p
    from semantic_pallet_planner.jev_select.geometry_native_protocol import identity_fields,policy_digest
    from semantic_pallet_planner.jev_select.stability.runtime import environment as monitor_environment
    from semantic_pallet_planner.jev_select.geometry_runtime_contracts import environment,same_native
    actual={str(f.relative_to(SRC)):sha(f.read_bytes()) for f in SRC.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(SRC).parts)}
    assert actual==read(R3/'source_manifest.json')['files'] and digest(actual)=='94e4c37838f0a82f84c200d12fbed5d92c93eb7486085e9c3014c514ba886fa2','SOURCE_DRIFT'
    checks=[]
    for folder,rev in ((R3,'498e0cf2dcd21220af4503e7b3e7277598d5b534'),(QA,'64565e51e7758533a0ecb9b52f2611c791712a9f')):
        for row in read(folder/'delivery_manifest.json')['files']:
            f=Path(row['path']);raw=subprocess.check_output(['git','show',rev+':'+str(f)]) if f.name=='README.md' else f.read_bytes()
            assert sha(raw)==row['sha256'] and len(raw)==row['size_bytes'],str(f)
        checks.append({'manifest':str((folder/'delivery_manifest.json').relative_to(ROOT)),'members':len(read(folder/'delivery_manifest.json')['files']),'sha256':sha((folder/'delivery_manifest.json').read_bytes()),'navigation_revision':rev})
    monitor=read(R3/'original_monitor_config.readonly.json')['stability_monitor']
    observed=monitor_environment()
    write('environment_review.json',{'expected':monitor['execution_environment'],'observed':observed,'differences':{k:{'expected':monitor['execution_environment'].get(k),'observed':v} for k,v in observed.items() if not same_native(v,monitor['execution_environment'].get(k))},'runtime_environment':environment(),'dependencies':monitor['algorithm_identity']['dependencies'],'status':'PENDING_ORIGINAL_PREFLIGHT'})
    e.validate_monitor_snapshot(monitor) # Original dependency/source/env checks; never freeze.
    tasks=[]
    for case in ('K02_INT','K02'):
        origin=O.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R1_20261118_01'/('GP5_SYNTH_'+case+'.raw.json')
        raw=origin.read_bytes();t=p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=sha(raw));tasks.append(t)
        (O/origin.name).write_bytes(raw);write('GP5_SYNTH_'+case+'.identity.json',t['identity'])
    plan=p.prepare_order_plan(tasks,data_identity=digest('NUM_N1_R4_FIXED_SYNTHETIC'),scope=p.DEVELOPMENT,native=True)
    adm={**identity_fields(plan),'version':'geometry_development_binding_v2','scope':p.DEVELOPMENT,'evidence':'TEST_DOUBLE','plan_digest':digest(plan)}
    configs={j['job_id']:e.load_order_config(plan,j['job_id'],monitor_snapshot=monitor,admission=adm) for j in plan['jobs']}
    assert len(configs)==8 and policy_digest()=='fe12fc1dec4d7004d813bef76162648ac916adb9e2006b92b163aeadb54fe4cb'
    write('source_manifest.json',{'files':actual,'source_files':len(actual),'source_identity':digest(actual),'production_changed':False})
    for name,value in (('plan',plan),('admission',adm),('configs',configs),('monitor_snapshot',monitor)) :write(name+'.json',value)
    shutil.copyfile(R3/'original_validation_scope.readonly.json',O/'original_validation_scope.readonly.json')
    scope=read(R3/'intended_scope.json');scope.update(unit='GP5_NUM_N1_R4_ENVIRONMENT_AND_VALIDATION_ENTRYPOINT',freeze_status='PASS',execution_authorized=False,execution_gate='EXPLICIT_SUBSEQUENT_USER_ASSIGNMENT_REQUIRED',X_H_names=read(O/'original_validation_scope.readonly.json')['X_H'])
    write('validation_scope.json',scope)
    write('strategy_identity.json',{'policy_digest':policy_digest(),'key_equivalence':'geometry_native_shape_key_equivalence_v1','config_digests':{k:digest(v) for k,v in configs.items()},'runtime_strategy_identities':{k:v['runtime_identity']['strategy_identity'] for k,v in configs.items()},'data':{t['identity']['task_id']:t['identity'] for t in tasks}})
    review=read(O/'environment_review.json');review.update(status='PASS_ORIGINAL_FULL_PREFLIGHT',configs_preflighted=8);write('environment_review.json',review)
    write('baseline_receipt.json',{'entry_head':'498e0cf2dcd21220af4503e7b3e7277598d5b534','actual_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'branch':'dev/jev-select','upstream':'origin/dev/jev-select','initial_worktree':'CLEAN','initial_index':'EMPTY','pull':'normal attempt FETCH_HEAD read-only; escalated git pull --ff-only fast-forward success','historical_manifests':checks,'production_source_identity':digest(actual)})
    print('PASS original full monitor/dependency environment checks; unchanged591 R3 source; eight configs frozen; business execution NOT_AUTHORIZED')
if __name__=='__main__':
    try:main()
    except BaseException as exc:
        write('stop.json',{'status':'FIRST_UNEXPECTED_PREPARATION_FAILURE_STOPPED','type':type(exc).__name__,'detail':str(exc),'traceback':traceback.format_exc(),'no_retry':True});raise

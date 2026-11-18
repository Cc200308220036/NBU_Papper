"""Metadata/preflight only; preserve R4 and QA original bytes."""
import hashlib,json,subprocess,traceback,shutil
from pathlib import Path
I=Path(__file__).resolve().parent;ROOT=Path.cwd();R4=I.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R4_20261118_01';QA=I.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R4_QA_20261118_01'
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,v):(I/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def main():
    assert not (I/'baseline_receipt.json').exists(),'NO_RETRY'
    from semantic_pallet_planner.jev_select.contracts import digest
    from semantic_pallet_planner.jev_select import geometry_order_execution as order
    from semantic_pallet_planner.jev_select.stability.runtime import environment
    src=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
    actual={str(f.relative_to(src)):sha(f) for f in src.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(src).parts)}
    assert actual==read(R4/'source_manifest.json')['files'] and digest(actual)=='94e4c37838f0a82f84c200d12fbed5d92c93eb7486085e9c3014c514ba886fa2'
    manifests=[]
    for folder,rev in ((R4,'b9a26d59d17b3136aef0e1be81bab4bab68c42e9'),(QA,'8b2a10a5')):
        for row in read(folder/'delivery_manifest.json')['files']:
            p=Path(row['path']);b=subprocess.check_output(['git','show',rev+':'+str(p)]) if p.name=='README.md' else p.read_bytes()
            assert hashlib.sha256(b).hexdigest()==row['sha256'] and len(b)==row['size_bytes'],str(p)
        manifests.append({'manifest':str((folder/'delivery_manifest.json').relative_to(ROOT)),'members':len(read(folder/'delivery_manifest.json')['files']),'sha256':sha(folder/'delivery_manifest.json'),'navigation_revision':rev})
    for rel,h in read(R4/'frozen_identity.json')['files'].items():assert sha(Path(rel))==h,rel
    mon=read(R4/'monitor_snapshot.json');observed=environment();write('environment_receipt.json',{'expected':mon['execution_environment'],'observed':observed,'status':'PENDING','dependencies':mon['algorithm_identity']['dependencies']})
    order.validate_monitor_snapshot(mon)
    plan=read(R4/'plan.json');adm=read(R4/'admission.json');configs=read(R4/'configs.json')
    for j in plan['jobs']:assert order.load_order_config(plan,j['job_id'],monitor_snapshot=mon,admission=adm)==configs[j['job_id']]
    write('environment_receipt.json',{'expected':mon['execution_environment'],'observed':observed,'status':'PASS_ORIGINAL_FULL_ENV_AND_DEPENDENCY_PREFLIGHT','configs_preflighted':8,'dependencies':mon['algorithm_identity']['dependencies']})
    for name in ('source_manifest.json','plan.json','admission.json','configs.json','monitor_snapshot.json','strategy_identity.json','policy_identity.json','admin_input_identity.json','original_validation_scope.readonly.json','GP5_SYNTH_K02_INT.raw.json','GP5_SYNTH_K02_INT.identity.json','GP5_SYNTH_K02.raw.json','GP5_SYNTH_K02.identity.json'):
        shutil.copyfile(R4/name,I/name)
    scope=read(R4/'validation_scope.json');scope.update(unit='GP5_NUM_N1_R5_VALIDATION_ISOLATION_AND_COVERAGE',execution_authorized=False,execution_gate='EXPLICIT_SUBSEQUENT_USER_ASSIGNMENT_REQUIRED',input_output_isolation='NEW_EXPLICIT_ABSENT_RUN_ROOT_REQUIRED')
    write('validation_scope.json',scope)
    write('archive_member_identity.json',{'files':{str(f.relative_to(ROOT)):sha(f) for folder in (R4,QA) for f in folder.rglob('*') if f.is_file()},'full_original_archives':True})
    write('baseline_receipt.json',{'entry_head':'b9a26d59d17b3136aef0e1be81bab4bab68c42e9','actual_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'branch':'dev/jev-select','upstream':'origin/dev/jev-select','initial_worktree':'CLEAN','initial_index':'EMPTY','pull':'normal FETCH_HEAD read-only; escalated ff-only succeeded','source_files':591,'source_identity':digest(actual),'manifests':manifests,'R4_frozen_members_verified':len(read(R4/'frozen_identity.json')['files'])})
    print('PASS unchanged591 source, original R4/QA manifests and1215 frozen members, full environment/dependencies and8 configs; no business execution')
if __name__=='__main__':
    try:main()
    except BaseException as exc:write('stop.json',{'type':type(exc).__name__,'detail':str(exc),'traceback':traceback.format_exc(),'no_retry':True});raise

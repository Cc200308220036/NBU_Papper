"""One-shot independent seal: R6 pinned revision and R7 current namespaces."""
import ast,json,subprocess,traceback
from pathlib import Path
from lineage import read,sha,relative,SRC,SOURCE,current_source,verify_rows,verify_freeze
from scope_guard import UNIT,ALLOWED,LIMITS,Guard
I=Path(__file__).resolve().parent;B=Path('semantic_pallet_planner/outputs');R8=B/'GEOM_CANDIDATES_GP5_NUM_N1_R8_20261119_01';R6=B/'GEOM_CANDIDATES_GP5_NUM_N1_R6_20261118_01'
def write(name,v):(I/name).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def main():
    assert not (I/'seal_started.json').exists(),'NO_RETRY_OR_RESEAL'
    write('seal_started.json',{'unit':UNIT,'execution_authorized':False})
    revision=subprocess.check_output(['git','rev-parse','1dbc8f30^{commit}'],text=True).strip()
    historical={}
    # All source references in R6 freeze resolved at the pinned R6 revision.
    # Other immutable archived bytes remain checked at their repository paths.
    for inventory in (R6/'frozen_identity.json',R8/'historical_inventory.readonly.json',R8/'archive_member_identity.json'):
        for original,h in read(inventory)['files'].items():
            path=relative(original);kind='git' if inventory==R6/'frozen_identity.json' and path.startswith(SRC) else 'archive'
            row={'path':path,'kind':kind,'sha256':h}
            if kind=='git':row['revision']=revision
            key=(kind,path,row.get('revision',''))
            if key in historical:assert historical[key]['sha256']==h,'HISTORICAL_IDENTITY_CONFLICT'
            historical[key]=row
    # Bind complete original R8 and QA packages, preserving the failed seal/stop.
    for folder in (R8,B/'GEOM_CANDIDATES_GP5_NUM_N1_R8_QA_20261119_01'):
        for f in folder.rglob('*'):
            if f.is_file() and '__pycache__' not in f.parts:
                path=relative(str(f));historical[('archive',path,'')]={'path':path,'kind':'archive','sha256':sha(f.read_bytes())}
    verify_rows(list(historical.values()))
    from semantic_pallet_planner.jev_select.contracts import digest
    current=current_source();assert len(current)==591 and current==read(I/'source_manifest.json')['files'] and digest(current)==SOURCE,'CURRENT_SOURCE_MISMATCH'
    from semantic_pallet_planner.jev_select import geometry_order_execution as order
    mon=read(I/'monitor_snapshot.json');order.validate_monitor_snapshot(mon)
    plan=read(I/'plan.json');adm=read(I/'admission.json');configs=read(I/'configs.json');Guard(plan)
    for job in plan['jobs']:assert order.load_order_config(plan,job['job_id'],monitor_snapshot=mon,admission=adm)==configs[job['job_id']]
    for f in I.glob('*.py'):ast.parse(f.read_bytes())
    root=str(B/'GEOM_CANDIDATES_GP5_NUM_N1_R8_R1_RUN_20261119_01');assert not Path(root).exists()
    files={str(Path(SRC)/p):h for p,h in current.items()}
    for f in Path('semantic_pallet_planner/tests/unit').iterdir():
        if f.suffix in ('.py','.json'):files[str(f)]=sha(f.read_bytes())
    for f in I.iterdir():
        if f.suffix in ('.py','.json'):files[relative(str(f))]=sha(f.read_bytes())
    value={'schema':'geometry_num_n1_r8_r1_freeze_v1','unit':UNIT,'source_identity':SOURCE,'source_files':591,'historical_revision':revision,'historical_source_identity':read(R6/'source_manifest.json')['source_identity'],'historical_members':list(historical.values()),'current_members':[{'path':p,'kind':'archive','sha256':h} for p,h in sorted(files.items())],'allowed_jobs':ALLOWED,'limits':LIMITS,'run_root':root,'execution_authorized':False,'authorization_receipt':'NOT_ISSUED','old_E_used':21,'old_E_cap':21,'carryover':False}
    write('frozen_identity.json',value);verify_freeze(I)
    write('seal_receipt.json',{'status':'PASS','historical_members':len(historical),'current_members':len(files),'historical_revision':revision,'historical_source_identity':value['historical_source_identity'],'current_source_identity':SOURCE,'source_files':591,'configs_preflighted':8,'all_manifest_member_paths':'REPOSITORY_RELATIVE','old_packages_modified':False,'execution_authorized':False})
    print('PASS independent R8-R1 seal; historical',len(historical),'current',len(files),'source591 configs8; no dispatch')
if __name__=='__main__':
    try:main()
    except BaseException as e:
        write('stop.json',{'type':type(e).__name__,'detail':str(e),'traceback':traceback.format_exc(),'no_retry':True});raise

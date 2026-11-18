"""Read-only identities/J00 assertions plus byte-identical new-root preparation.
No candidate generation, episode, monitor, freezer or solver invocation.
"""
import hashlib,json,shutil,subprocess
from pathlib import Path
from geometry_native_assertions_r2 import assert_episode_shapes,same_native
from semantic_pallet_planner.jev_select import geometry_order_execution as o,packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.geometry_runtime_contracts import environment
from test_geometry_order_p1 import SNAP

OUT=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_NUM_N1_R2_20261118_01')
OLD=OUT.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R1_20261118_01'
QA=OUT.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R1_QA_20261118_01'

def sha(b):return hashlib.sha256(b).hexdigest()
def read(p):return json.loads(p.read_bytes())
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def hashes(root):return {str(f.relative_to(root)):sha(f.read_bytes()) for f in root.rglob('*') if f.is_file()}

checked=[]
for folder,rev in ((OLD,'cb9575d0e3c8f719b371effdc16eaad517e66e1e'),(QA,'c1bc0184e16e04b1fe91d75c410d93ec47f37db5')):
    manifest=folder/'delivery_manifest.json';m=read(manifest)
    for row in m['files']:
        f=Path(row['path']);raw=subprocess.check_output(['git','show',rev+':'+str(f)]) if f.name=='README.md' else f.read_bytes()
        assert sha(raw)==row['sha256'] and len(raw)==row['size_bytes'],str(f)
    checked.append({'manifest':str(manifest),'sha256':sha(manifest.read_bytes()),'members':len(m['files']),'navigation_revision':rev})
src=Path('semantic_pallet_planner/src/semantic_pallet_planner')
current={str(f.relative_to(src)):sha(f.read_bytes()) for f in src.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(src).parts)}
original=read(OLD/'source_manifest.json');assert current==original['files'] and digest(current)=='be3486f6f90f4c4b3ec2696aaf8fee24353d4b83af78892576962e437370cd89'
plan=read(OLD/'plan.json');admission=read(OLD/'admission.json');configs=read(OLD/'configs.json');monitor=read(OLD/'monitor_snapshot.json');scope=read(OLD/'validation_scope.json')
assert same_native(monitor,SNAP) and digest(plan)==scope['plan_digest']
assert plan['environment_digest']==digest(environment()),'ENVIRONMENT_IDENTITY_DRIFT'
for job in plan['jobs']:
    cfg=o.load_order_config(plan,job['job_id'],monitor_snapshot=monitor,admission=admission)
    assert same_native(cfg,configs[job['job_id']]) and digest(cfg)==scope['config_digests'][job['job_id']],'CONFIG_OR_DEPENDENCY_DRIFT'
for case in ('K02_INT','K02'):
    name='GP5_SYNTH_'+case;raw=(OLD/(name+'.raw.json')).read_bytes()
    adapted=p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=sha(raw))
    assert same_native(adapted['identity'],read(OLD/(name+'.identity.json')))
episode=read(OLD/'E/jobs/J00/episode.json');run=read(OLD/'E/run.json');account=read(OLD/'E/jobs/J00/accounting.json')
assert run['rows'][0]['status']=='COMPLETE' and all(r['status']=='NOT_RUN' for r in run['rows'][1:])
rows=assert_episode_shapes(episode);assert len(rows)==2 and episode['summary']['completed'] and account['cumulative']['commit_successes']==2
save('J00_saved_validation.json',{'production_status':'COMPLETE_EXISTING_SAVED_RESULT','validation_status':'PASS_CORRECTED_ASSERTIONS_READ_ONLY','executed_this_round':False,'rows':rows,'source_episode':str(OLD/'E/jobs/J00/episode.json'),'source_sha256':sha((OLD/'E/jobs/J00/episode.json').read_bytes()),'monitors_added':0,'commits_added':0})
# Freeze identical bytes. Never rewrite the old manifests/inputs/config/checkpoint.
for name in ('source_manifest.json','plan.json','admission.json','configs.json','monitor_snapshot.json','validation_scope.json','GP5_SYNTH_K02_INT.raw.json','GP5_SYNTH_K02_INT.identity.json','GP5_SYNTH_K02.raw.json','GP5_SYNTH_K02.identity.json'):
    (OUT/name).write_bytes((OLD/name).read_bytes())
prior=hashes(OLD/'E')
assert not (OUT/'prefix_snapshot').exists() and not (OUT/'continuation').exists()
shutil.copytree(OLD/'E',OUT/'prefix_snapshot');shutil.copytree(OUT/'prefix_snapshot',OUT/'continuation')
assert hashes(OUT/'prefix_snapshot')==hashes(OUT/'continuation')==prior
save('prefix_provenance.json',{'source_root':str(OLD/'E'),'preserved_snapshot':str(OUT/'prefix_snapshot'),'continuation_root':str(OUT/'continuation'),'files':prior,'initial_copies_byte_identical':True,'record_path_note':'Original record paths retained verbatim; copied metadata is not rewritten or re-signed. New jobs use the new root.'})
save('baseline_receipt.json',{'entry_head':'c1bc0184e16e04b1fe91d75c410d93ec47f37db5','actual_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'branch':'dev/jev-select','upstream':'origin/dev/jev-select','initial_worktree':'CLEAN','initial_index':'EMPTY','pull':'user_completed_pull; agent redundant pending pull cancelled (exit130) after verifying HEAD','source_identity':digest(current),'source_files':len(current),'manifests':checked,'environment':environment(),'old_failed_E_monitors':1,'R1_J00_E_monitors':2,'consumed_E':3,'remaining_E_jobs':['J01','J02','J03','J04','J05','J06','J07'],'new_E_monitor_cap':14,'R_resumes_cap':6,'R_monitor_cap':2,'R_commit_cap':4,'R_new_generation_bridge_selection':0,'X_H_monitor_cap':1})
print('PASS same591 production set/bytes, all8 config/plan/data/monitor/environment identities; J00 saved-only; identical prefix copies')

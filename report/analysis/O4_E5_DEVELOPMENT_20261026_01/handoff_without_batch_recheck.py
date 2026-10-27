"""Finish delivery from existing runtime checks, per the user's no-batch-recheck instruction.

No episode/verify_episode/verify_results/verify_experiment/prepare_remote call is
made here. Business execution remains the unmodified frozen development_v2.
"""
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
import yaml
from semantic_pallet_planner.o4.common import read,write,digest
from semantic_pallet_planner.o4.extensions.e2.experiment import files,seal,verify_seal,new_output
from semantic_pallet_planner.o4.extensions.e2.remote import prompt
from semantic_pallet_planner.o4.extensions.e5.experiment import validate_plan,online_jobs,protection_check,PACKAGE
from semantic_pallet_planner.o4.extensions.e5.delivery import accounting_views,lightweight_results,visuals
from semantic_pallet_planner.o4.extensions.e5.metrics import aggregate
from semantic_pallet_planner.o4.extensions.e5.online import ONLINE_VERSION,validate_online_plan
from semantic_pallet_planner.o4.remote.transport import ModelConfig

WS=Path('/home/cyw/NBU_Papper');BASE=WS/'semantic_pallet_planner/outputs'
OUT=WS/'report/analysis/O4_E5_DEVELOPMENT_20261026_01'
PLAN=BASE/'PLAN_O4_E5_090_OFFLINE_READY_20261026_06'
EXP=BASE/'EXP_O4_E5_090_OFFLINE_20261026_06'
ONLINE=BASE/'PLAN_O4_E5_090_ONLINE_READY_20261026_01'
POLICY='user_requested_runtime_checks_without_extra_batch_recheck_20261026_v1'
plan,data,config=validate_plan(PLAN)
assert not (EXP/'delivery_manifest.json').exists(), 'Do not change a sealed experiment'
jobs=read(EXP/'audit/jobs.json')
assert len(jobs)==240 and all(j['status']=='PASS' for j in jobs)
assert not (EXP/'audit/episode_recomputation.json').exists()
policy={'version':POLICY,'user_instruction':'不需要对240条都做复查，我觉得意义不大',
        'runtime_checked_jobs':240,'extra_full_batch_recheck':'SKIPPED_BY_USER',
        'standalone_verify_command':'NOT_RUN','original_remote_prepare_full_recheck':'NOT_RUN',
        'kept':'first-run protocol/state/planning/reference checks, existing repeat/restore comparisons, metrics aggregation and file hashes',
        'original_spec_deviation':'post-run all-episode recomputation requirement waived by explicit later user instruction',
        'raw_episode_records_modified':False,'real_api_attempts':0}
write(EXP/'verification_policy.json',policy)
script=Path(__file__);target=EXP/'orchestration_snapshot'/script.name;target.parent.mkdir(exist_ok=True);shutil.copy2(script,target)
write(EXP/'audit/postprocessing_control.json',{'matrix_process_exit':130,'reason':'stopped after 240 first-run jobs, before extra full batch recheck, per user',
      'previous_full_recheck_supervisor_stopped':True,'policy':POLICY,'orchestration_sha256':hashlib.sha256(script.read_bytes()).hexdigest()})

# Summarize saved checks, without replaying their trajectories.
checks=[];coverage=[];maxima={'per_object':0,'joint':0,'depth':0,'beam':0,'successors':0};commits=0
source_completions=Counter();construct_completions=Counter()
for j in jobs:
    check=read(EXP/f"audit/jobs/{j['job_id']}.json")
    assert check and all(value is True for value in check.values())
    checks.append({'job_id':j['job_id'],'evidence':f"audit/jobs/{j['job_id']}.json",'checked_during_initial_execution':True})
    r=read(EXP/f"episodes/{j['job_id']}.json");s=r['summary']
    assert s['execution_status']=='PASS' and s['violating_steps']==0 and not s['final_business_violations']
    table=source_completions if j['source_kind']=='development_order' else construct_completions
    table[(j['backend'],j['planner'])]+=s['completed']
    for e in r['events']:
        commits+=bool(e.get('action'))
        if 'diagnostics' not in e:continue
        coverage.append({'job_id':j['job_id'],'compilation_id':e['compilation']['compilation_id'],**e['diagnostics']})
        maxima['joint']=max(maxima['joint'],len(e['candidates']))
        maxima['per_object']=max(maxima['per_object'],max((len(g['candidates']) for g in e['groups']),default=0))
        t=e['search_trace']
        for key,field in (('depth','max_depth'),('beam','max_beam'),('successors','evaluations')):maxima[key]=max(maxima[key],t.get(field,0))
assert all(maxima[k]<=v for k,v in {'per_object':16,'joint':48,'depth':3,'beam':8,'successors':256}.items())
write(EXP/'audit/runtime_checks_summary.json',checks);write(EXP/'audit/coverage.json',coverage)
write(EXP/'audit/readonly_verify.json',{'status':'SKIPPED_BY_USER','extra_full_batch_recompute_completed':False,
      'runtime_check_records_summarized':len(checks),'scope':'saved first-run checks, no post-run trajectory replay','new_api_attempts':0})
for directory,filename in (('repeats','repeats'),('restores','restores')):
    paths=sorted((EXP/directory).glob('*.json'));assert len(paths)==120
    write(EXP/f'audit/{filename}.json',[{'job_id':p.stem,'saved_file':str(p.relative_to(EXP)),
          'comparison_performed_during_initial_execution':True,'post_run_recomputation':'SKIPPED_BY_USER'} for p in paths])
views=accounting_views(EXP,data,jobs)
summary=aggregate(lightweight_results(EXP,jobs),jobs);write(EXP/'metrics/summary.json',summary)
for name,n in (('regression',180),('invalid',48),('gold',12)):
    rows=read(EXP/f'metrics/{name}.json');assert len(rows)==n and all(r['passed'] for r in rows)
print('Existing runtime results and metrics summarized; no trajectories replayed',flush=True)

# Reuse the already executed same-snapshot fault evidence, rather than run it again.
faults=read(OUT/'preflight_faults_snapshot06.json');assert len(faults)==42 and all(r['passed'] for r in faults)
shutil.copytree(OUT/'preflight_faults_snapshot06',EXP/'faults')
write(EXP/'audit/faults.json',faults)
extra=[]
for name in ('extra_fault_audit.json','extra_state_fault_audit.json','nonfinite_fault_audit.json','collision_fault_audit.json'):
    result=read(OUT/name);assert result['status']=='PASS';assert all(r['passed'] for r in result['faults']);extra+=result['faults']
    write(EXP/'audit'/name,result)
assert len(extra)==17
write(EXP/'audit/fault_evidence_provenance.json',{'executed_before_primary_matrix_finalization':True,'same_frozen_source':str(PLAN),
      'source':str(OUT/'preflight_faults_snapshot06'),'copied_to':'faults/','extra_checks':17,'reexecuted':False})
# First generation of the public image artifacts; no planner/episode replay.
image_report=visuals(EXP,data,jobs)
protection=protection_check(read(PLAN/'private/protected.before.json'),plan['workspace_root'])
assert protection['status']=='PASS' and image_report['all_verified']
write(EXP/'audit/protected.json',protection)
assert files(PACKAGE)==plan['source_files']
assert read(OUT/'tests_v2_source_binding.json')['status']=='PASS'
for rel,sha in read(OUT/'tests_v2_before.json').items():assert hashlib.sha256((WS/rel).read_bytes()).hexdigest()==sha

report={'scope':'O4_E5_090_CURRENT_SCOPE','status':'PASS_UNDER_USER_REVISED_POLICY','offline_status':'PASS_UNDER_USER_REVISED_POLICY',
        'verification_policy':POLICY,'extra_full_batch_recheck':'SKIPPED_BY_USER','original_full_recheck_gate':'USER_WAIVED',
        'gates':{**{f'E5-{i:02d}':'PASS' for i in range(1,11) if i!=9},'E5-09':'PARTIAL_USER_WAIVER_EXTRA_FULL_RECHECK'},
        'runtime_checked_jobs':240,'planned_main_episodes':192,'planned_construct_episodes':48,'recorded_episodes':240,
        'independent_repeats':120,'restores':120,'repeat_restore_scope':'compared during initial execution; not batch-recomputed afterwards',
        'semantic_regression':180,'invalid_regression':48,'mixed_gold':12,'tests':80,'faults':42,'extra_fault_checks':17,
        'actual_physical_submissions':commits,'resource_maxima':maxima,'visual':image_report,'accounting_views':views,'protected':protection,
        'real_compile_status':'NOT_RUN','prior_e1_e2_real_compile_status':'PASS','real_online_status':'NOT_RUN',
        'unseen_generalization':'NOT_MEASURED','visual_increment':'NOT_MEASURED','e3_status':'DEFERRED','e4_status':'OUT_OF_SCOPE',
        'yaw_degrees':[0,90],'new_api_attempts':0}
write(EXP/'acceptance_report.json',report)
(EXP/'README.md').write_text('E5 0/90 execution completed. 240 first-run checks,120 repeats/restores. Extra full batch recheck SKIPPED BY USER.\nRead acceptance_report.json and verification_policy.json; do not claim the original full-recompute gate passed. Real API NOT_RUN.\n')
seal(EXP)
print('Offline files sealed under the explicitly revised verification policy',flush=True)

# Assemble a real plan from frozen data/source and sealed runtime evidence.
# The strict original prepare_remote entry intentionally remains unused because
# it would trigger the extra full offline recomputation the user cancelled.
verify_seal(EXP)
model=ModelConfig(**yaml.safe_load((WS/'semantic_pallet_planner/configs/o4_d_deepseek_flash.yaml').read_text()));model.validate()
root=new_output(ONLINE,(PLAN,EXP));online_jobs_list=online_jobs(data)
maximum=sum(j['attempt_limit'] for j in online_jobs_list);assert maximum==3100 and len(online_jobs_list)==240
online={'version':ONLINE_VERSION,'scope':'O4_E5_090_CURRENT_SCOPE','jobs':online_jobs_list,'planned_jobs':240,'prefix_jobs':20,
        'maximum_api_attempts':maximum,'prefix_maximum_api_attempts':sum(j['attempt_limit'] for j in online_jobs_list[:20]),
        'data_digest':digest(data),'config_digest':digest(config),'model_digest':digest(model.snapshot()),
        'source_files':plan['source_files'],'font_sha256':plan['font_sha256'],'development_plan':str(PLAN),'offline_experiment':str(EXP),
        'offline_delivery_digest':digest(read(EXP/'delivery_manifest.json')),'e3_status':'DEFERRED','e4_status':'OUT_OF_SCOPE',
        'offline_verification_policy':policy,'preparation_mode':'runtime evidence and file seals, no extra full trajectory recheck'}
assert online['prefix_maximum_api_attempts']==260
write(root/'plan.json',online);write(root/'model.snapshot.json',model.snapshot());write(root/'config.snapshot.json',config)
write(root/'private/input_snapshot.json',data);write(root/'verification_policy.json',policy);(root/'prompt.txt').write_text(prompt())
shutil.copytree(PLAN/'code_snapshot',root/'code_snapshot');shutil.copytree(PLAN/'documentation',root/'documentation')
shutil.copy2(script,root/'documentation'/script.name)
(root/'README.md').write_text('E5 real API plan,240 jobs; first20 then resume220; global attempt cap3100,prefix cap260.\nPrepared under explicit user waiver of extra offline full batch replay. Read verification_policy.json. No real API requests made.\n')
seal(root);validate_online_plan(root)
write(OUT/'runtime_checked_delivery.json',{'status':'PASS_UNDER_USER_REVISED_POLICY','policy':policy,'offline':report,
      'online_plan':{'path':str(root),'jobs':240,'prefix_jobs':20,'maximum_api_attempts':3100,'prefix_maximum_api_attempts':260,
                     'metadata_source_model_and_seal_validation':'PASS','trajectory_replay':'NOT_RUN'},
      'source_completions':{'/'.join(k):v for k,v in source_completions.items()},
      'construct_completions':{'/'.join(k):v for k,v in construct_completions.items()},'real_api_attempts':0})
write(OUT/'delivery_stage.json',{'stage':'READY_UNDER_USER_REVISED_POLICY','extra_full_batch_recheck':'SKIPPED_BY_USER',
      'offline_experiment':str(EXP),'online_plan':str(root),'real_api_attempts':0})
print(json.dumps({'status':'PASS_UNDER_USER_REVISED_POLICY','runtime_checked_jobs':240,'extra_full_batch_recheck':'SKIPPED_BY_USER',
      'online_plan':str(root),'real_api_attempts':0},indent=2),flush=True)

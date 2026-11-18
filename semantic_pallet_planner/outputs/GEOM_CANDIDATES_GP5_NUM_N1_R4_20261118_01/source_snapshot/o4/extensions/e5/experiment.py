"""Frozen E5 plans and resumable offline execution; no implicit network paths."""
import contextlib
import hashlib
import io
import shutil
from pathlib import Path
from ...common import read,write,digest,O4Error
from ....config import WORKSPACE,generator_config,load_config
from ..e2.experiment import files,seal,verify_seal
from ..e2.planning import METHODS
from ..e2.validation import gold
from ..e2.witnesses import verify as witness
from ..e2.visual import FONT
from . import VERSION,EXPECTED_CONFIG
from . import validation
from .data import source_tasks,construct_tasks,mixed_gold
from .backends import LocalCompiler
from .episode import episode,verify_episode,stable
from .storage import atomic,exclusive,new_output,record_failures,phase

PACKAGE=Path(__file__).resolve().parents[3]
SPEC='docs/02_阶段实施方案/O4/O4E5混合约束完整订单闭环开发与验收规范_20261026.md'
HANDBOOK='docs/04_运行与复核手册/O4E5混合约束完整订单运行及API交接_20261026.md'
DEVELOPMENT='docs/03_阶段产出分析/O4/O4E5混合约束完整订单开发与验收_20261026.md'


def validate_extension(extension):
    if not isinstance(extension,dict) or set(extension)!=set(EXPECTED_CONFIG):raise O4Error('unsupported_e5_config','closed frozen config fields required')
    for key,expected in EXPECTED_CONFIG.items():
        try:equal=digest(extension[key])==digest(expected)
        except (TypeError,ValueError):equal=False
        if not equal:raise O4Error('unsupported_e5_config',f'$.{key}: differs from frozen 0/90 contract')
    return extension


def offline_jobs(data):
    return [{'job_id':f"{t['task_id']}_{b}_{m}",'task_id':t['task_id'],'backend':b,'planner':m,
             'source_kind':t['source_kind'],'source_order_key':t['source_order_key'],'configuration':t['configuration'],'planned_items':len(t['items']),'attempt_limit':0,'status':'NOT_RUN'}
            for t in data['tasks']+data['constructs'] for b in ('public_parser','oracle_ast') for m in METHODS]


def online_jobs(data):
    tasks=data['tasks'];priority=[t for t in tasks if (t['source_index'],t['configuration']) in ((0,0),(1,1))]
    ordered=priority+[t for t in tasks if t not in priority]
    return [{'job_id':f"{t['task_id']}_{b}_{m}",'task_id':t['task_id'],'backend':b,'planner':m,
             'source_kind':t['source_kind'],'source_order_key':t['source_order_key'],'configuration':t['configuration'],'planned_items':len(t['items']),'attempt_limit':2*(len(t['items'])+1) if b.startswith('remote_') else 0,'status':'NOT_RUN'}
            for t in ordered for b,m in [*((b,'single') for b in ('public_parser','remote_text','remote_image','oracle_ast')),
                                         *((b,m) for m in METHODS[1:] for b in ('remote_text','oracle_ast'))]]


def protection_check(manifest,workspace):
    bad=[name for name,sha in manifest.items() if not (Path(workspace)/name).is_file() or hashlib.sha256((Path(workspace)/name).read_bytes()).hexdigest()!=sha]
    return {'status':'FAIL' if bad else 'PASS','checked':len(manifest),'changed':bad}


@record_failures('prepare')
def prepare(output,protection):
    root=new_output(output)
    phase('reading_sources_and_declared_fixtures')
    sources,tasks=source_tasks(WORKSPACE);constructs=construct_tasks()
    witnesses=[witness(t,physical_only=t['negative']) for t in constructs]
    if not all(w['passed'] for w in witnesses):raise O4Error('invalid_manual_witness')
    # Run before freezing to catch malformed declared examples, not to select
    # natural sources or change any expected order completion.
    data={'version':VERSION,'sources':sources,'tasks':tasks,'constructs':constructs,'gold':mixed_gold(),
          'regression_inputs':validation.inputs(),'manual_witnesses':witnesses}
    if not all(r['passed'] for r in validation.mixed(data['gold'])):raise O4Error('invalid_mixed_gold')
    from ..e2.data import dataset
    data['shared_contract_fixtures']=dataset()
    config=generator_config(load_config());config['o4_e2']=read(WORKSPACE/'semantic_pallet_planner/configs/o4_e2_offline_v1.json')
    extension=read(WORKSPACE/'semantic_pallet_planner/configs/o4_e5_090_offline_v2.json')
    validate_extension(extension)
    if extension['search']!=config['o4_e2']['search']:raise O4Error('unsupported_e5_config','search differs from frozen E2 planner')
    config['o4_e5']=extension
    old=read(protection)
    protected=protection_check(old,WORKSPACE)
    if protected['status']!='PASS':raise O4Error('protected_sources_changed',str(protected['changed'][:10]))
    phase('freezing_validated_plan')
    write(root/'private/input_snapshot.json',data);write(root/'private/sources.json',sources)
    write(root/'private/tasks.json',tasks+constructs);write(root/'private/protected.before.json',old)
    write(root/'config.snapshot.json',config)
    for rel in (SPEC,HANDBOOK,DEVELOPMENT):
        dest=root/'documentation'/Path(rel).name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(WORKSPACE/rel,dest)
    from ....runners.o4_e5 import main
    helptext=io.StringIO()
    for command in ([],['prepare'],['validate-plan'],['offline-run'],['verify'],['remote-prepare'],['remote-run']):
        helptext.write('\n$ o4_e5 '+' '.join(command+['--help'])+'\n')
        with contextlib.redirect_stdout(helptext):
            try:main(command+['--help'])
            except SystemExit as exc:
                if exc.code:raise
    (root/'documentation/cli_help.txt').write_text(helptext.getvalue())
    target=root/'code_snapshot/semantic_pallet_planner/src/semantic_pallet_planner'
    shutil.copytree(PACKAGE,target,ignore=shutil.ignore_patterns('__pycache__'))
    tests=root/'tests';tests.mkdir()
    for base in ('unit','integration'):
        for path in (WORKSPACE/f'semantic_pallet_planner/tests/{base}').glob('*e5*.py'):shutil.copy2(path,tests/path.name)
    jobs=offline_jobs(data)
    plan={'version':VERSION,'scope':'O4_E5_090_CURRENT_SCOPE','workspace_root':str(WORKSPACE),
          'data_digest':digest(data),'config_digest':digest(config),'source_files':files(PACKAGE),
          'font_sha256':hashlib.sha256(Path(FONT).read_bytes()).hexdigest(),'protected_digest':digest(old),
          'jobs':jobs,'planned_main_episodes':192,'planned_construct_episodes':48,
          'planned_gold':12,'planned_semantic_regression':180,'planned_invalid_regression':48,
          'planned_oracle_repeats':120,'planned_oracle_restores':120,'new_api_attempts':0,
          'e3_status':'DEFERRED','e4_status':'OUT_OF_SCOPE'}
    if len(jobs)!=240:raise O4Error('invalid_job_denominator')
    write(root/'plan.json',plan);seal(root)
    return {'status':'PASS','planned_main_episodes':192,'planned_construct_episodes':48,'new_api_attempts':0}


def validate_plan(root):
    root=Path(root);verify_seal(root)
    plan=read(root/'plan.json');data=read(root/'private/input_snapshot.json');config=read(root/'config.snapshot.json')
    if plan['version']!=VERSION or plan['data_digest']!=digest(data) or plan['config_digest']!=digest(config) or plan['jobs']!=offline_jobs(data):raise O4Error('invalid_plan_binding')
    if files(PACKAGE)!=plan['source_files']:raise O4Error('code_snapshot_mismatch','use frozen code_snapshot with python -P')
    if hashlib.sha256(Path(FONT).read_bytes()).hexdigest()!=plan['font_sha256']:raise O4Error('render_font_changed')
    return plan,data,config


def initialize(root,plan_root,plan,data,config,*,mode):
    for name in ('plan.json','config.snapshot.json'):shutil.copy2(Path(plan_root)/name,root/name)
    write(root/'private/input_snapshot.json',data)
    write(root/'private/sources.json',data['sources']);write(root/'private/tasks.json',data['tasks']+data['constructs'])
    write(root/'manifest.json',{'version':VERSION,'mode':mode,'plan_root':str(Path(plan_root).resolve()),
         'manifest_scope':'immutable_creation_metadata; current status is in acceptance_report.json',
         'plan_delivery_digest':digest(read(Path(plan_root)/'delivery_manifest.json')),'e3_status':'DEFERRED','e4_status':'OUT_OF_SCOPE',
         'real_online_status':'NOT_RUN' if mode=='offline' else 'IN_PROGRESS','unseen_generalization':'NOT_MEASURED','visual_increment':'NOT_MEASURED'})


@record_failures('offline-run')
def offline_run(plan_root,output,*,resume=False,max_jobs=None):
    plan_root=Path(plan_root).resolve();plan,data,config=validate_plan(plan_root)
    if max_jobs is not None and (type(max_jobs)is not int or max_jobs<1):raise O4Error('invalid_job_limit')
    if resume:
        root=Path(output).resolve()
        if (root/'delivery_manifest.json').exists():raise O4Error('sealed_experiment','completed artifacts are immutable')
        if read(root/'manifest.json')['plan_delivery_digest']!=digest(read(plan_root/'delivery_manifest.json')):raise O4Error('resume_plan_changed')
    else:
        root=new_output(output,(plan_root,));initialize(root,plan_root,plan,data,config,mode='offline');atomic(root/'audit/jobs.json',copy_jobs(plan['jobs']))
    phase('running_offline_matrix')
    with exclusive(root/'run.lock'):
        jobs=read(root/'audit/jobs.json');tasks={t['task_id']:t for t in data['tasks']+data['constructs']}
        if [{k:v for k,v in j.items() if k!='status'} for j in jobs]!=[{k:v for k,v in j.items() if k!='status'} for j in plan['jobs']]:raise O4Error('job_registry_changed')
        regression,invalid,pairs=validation.run(data['regression_inputs'])
        write(root/'metrics/regression.json',regression);write(root/'metrics/invalid.json',invalid);write(root/'metrics/regression_pairs.json',pairs)
        write(root/'metrics/gold.json',validation.mixed(data['gold']));write(root/'private/manual_witnesses.json',data['manual_witnesses'])
        processed=0
        for job in jobs:
            if job['status']=='PASS':
                # Validate saved predecessors before accepting a resumed run.
                saved=read(root/f"episodes/{job['job_id']}.json");verify_episode(saved,tasks[job['task_id']],config);continue
            if job['status']=='FAIL':raise O4Error('failed_job_requires_new_version',job['job_id'])
            if max_jobs is not None and processed>=max_jobs:break
            task=tasks[job['task_id']];cp=root/f"checkpoints/{job['job_id']}.json"
            checkpoint=read(cp) if resume and cp.exists() else None
            job['status']='IN_PROGRESS';atomic(root/'audit/jobs.json',jobs)
            compiler=LocalCompiler(job['backend'],task['reference_policy'] if job['backend']=='oracle_ast' else None)
            try:
                result=episode(task,job['backend'],job['planner'],config,compiler,job['job_id'],resume=checkpoint,on_checkpoint=lambda c,phase:atomic(cp,c))
                restore_points=result.pop('checkpoints');restore_checkpoint=restore_points[-1] if restore_points else checkpoint
                check=verify_episode(result,task,config)
                if result['summary']['execution_status']!='PASS' or result['summary']['final_business_violations']:raise O4Error('offline_execution_failed')
                if task['source_kind']=='constructed' and result['summary']['completed']!=task['expected_by_planner'][job['planner']]:raise O4Error('construct_expectation_failed')
                if job['backend']=='oracle_ast':
                    repeated=episode(task,job['backend'],job['planner'],config,compiler,job['job_id']);repeated.pop('checkpoints')
                    restored=episode(task,job['backend'],job['planner'],config,compiler,job['job_id'],resume=restore_checkpoint);restored.pop('checkpoints')
                    if stable(repeated)!=stable(result) or stable(restored)!=stable(result):raise O4Error('repeat_or_restore_mismatch')
                    write(root/f"repeats/{job['job_id']}.json",repeated);write(root/f"restores/{job['job_id']}.json",{'checkpoint':restore_checkpoint,'result':restored})
                write(root/f"episodes/{job['job_id']}.json",result);write(root/f"audit/jobs/{job['job_id']}.json",check)
            except Exception as exc:
                job['status']='FAIL';atomic(root/'audit/jobs.json',jobs)
                write(root/'acceptance_report.json',{'status':'FAIL','offline_status':'FAIL','failed_job':job['job_id'],'error':str(exc),
                      'planned_jobs':len(jobs),'job_statuses':{s:sum(j['status']==s for j in jobs) for s in ('PASS','FAIL','IN_PROGRESS','NOT_RUN')},'new_api_attempts':0})
                seal(root);raise
            job['status']='PASS';atomic(root/'audit/jobs.json',jobs);processed+=1
            atomic(root/'progress.json',{'planned_jobs':len(jobs),'passed_jobs':sum(j['status']=='PASS' for j in jobs),'new_api_attempts':0})
        if any(j['status']!='PASS' for j in jobs):
            report={'status':'PARTIAL','offline_status':'PARTIAL','e3_status':'DEFERRED','e4_status':'OUT_OF_SCOPE','real_compile_status':'NOT_RUN','real_online_status':'NOT_RUN','unseen_generalization':'NOT_MEASURED','visual_increment':'NOT_MEASURED','recorded_jobs':sum(j['status']=='PASS' for j in jobs),'planned_jobs':len(jobs),'new_api_attempts':0}
            atomic(root/'acceptance_report.json',report);return report
        from .delivery import finalize_offline
        phase('finalizing_offline_evidence')
        report=finalize_offline(root,plan_root,plan,data,config)
        seal(root);return report


def copy_jobs(jobs):return [{**j} for j in jobs]

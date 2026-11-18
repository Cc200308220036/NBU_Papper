"""Explicit real online plan/run/continuation. Fake transports are test-only."""
import copy
import hashlib
import shutil
from pathlib import Path
import yaml
from ...common import read,write,digest,O4Error,canonical
from ...remote.transport import ChatTransport,ModelConfig
from ..e2.experiment import seal,verify_seal,files
from ..e2.remote import prompt,parse_response
from ..e2.visual_verify import verify as verify_image
from ..e2.visual import facts
from .experiment import VERSION,PACKAGE,validate_plan,online_jobs,initialize
from .episode import episode,verify_episode
from .backends import Ledger,LocalCompiler,RemoteCompiler
from .storage import atomic,exclusive,new_output,record_failures,phase
from .metrics import aggregate
from .delivery import lightweight_results,accounting_views

ONLINE_VERSION='o4_e5_090_real_online_v1'


@record_failures('remote-prepare')
def prepare_remote(development_plan,offline_experiment,model_config,output):
    dev=Path(development_plan).resolve();plan,data,config=validate_plan(dev)
    offline=Path(offline_experiment).resolve();verify_seal(offline)
    if read(offline/'acceptance_report.json')['offline_status']!='PASS' or read(offline/'manifest.json')['plan_delivery_digest']!=digest(read(dev/'delivery_manifest.json')):
        raise O4Error('offline_acceptance_required')
    from .delivery import verify_experiment
    proof=verify_experiment(offline)
    if proof['episode_records_recomputed']!=240 or proof.get('saved_repeats_verified')!=120 or proof.get('saved_restores_verified')!=120:raise O4Error('incomplete_offline_proof')
    model=ModelConfig(**yaml.safe_load(Path(model_config).read_text()));model.validate()
    root=new_output(output,(dev,offline));phase('freezing_online_plan');jobs=online_jobs(data)
    if len(jobs)!=240 or len({j['job_id'] for j in jobs})!=240:raise O4Error('invalid_online_jobs')
    maximum=sum(j['attempt_limit'] for j in jobs)
    online={'version':ONLINE_VERSION,'scope':'O4_E5_090_CURRENT_SCOPE','jobs':jobs,'planned_jobs':240,'prefix_jobs':20,
            'maximum_api_attempts':maximum,'prefix_maximum_api_attempts':sum(j['attempt_limit'] for j in jobs[:20]),
            'data_digest':digest(data),'config_digest':digest(config),'model_digest':digest(model.snapshot()),
            'source_files':plan['source_files'],'font_sha256':plan['font_sha256'],
            'development_plan':str(dev),'offline_experiment':str(offline),
            'offline_delivery_digest':digest(read(offline/'delivery_manifest.json')),'e3_status':'DEFERRED','e4_status':'OUT_OF_SCOPE'}
    write(root/'plan.json',online);write(root/'model.snapshot.json',model.snapshot());write(root/'config.snapshot.json',config)
    write(root/'private/input_snapshot.json',data);(root/'prompt.txt').write_text(prompt())
    shutil.copytree(dev/'code_snapshot',root/'code_snapshot');shutil.copytree(dev/'documentation',root/'documentation')
    seal(root)
    return {'status':'PASS','planned_jobs':240,'prefix_jobs':20,'maximum_api_attempts':maximum,'prefix_maximum_api_attempts':online['prefix_maximum_api_attempts'],'new_api_attempts':0}


def validate_online_plan(root):
    root=Path(root).resolve();verify_seal(root);plan=read(root/'plan.json');data=read(root/'private/input_snapshot.json');config=read(root/'config.snapshot.json')
    if plan['version']!=ONLINE_VERSION or plan['jobs']!=online_jobs(data) or plan['data_digest']!=digest(data) or plan['config_digest']!=digest(config) or plan['model_digest']!=digest(read(root/'model.snapshot.json')) or (root/'prompt.txt').read_text()!=prompt():raise O4Error('invalid_online_plan')
    if files(PACKAGE)!=plan['source_files']:raise O4Error('code_snapshot_mismatch')
    from ..e2.visual import FONT
    if hashlib.sha256(Path(FONT).read_bytes()).hexdigest()!=plan['font_sha256']:raise O4Error('render_font_changed')
    return plan,data,config


@record_failures('remote-run')
def remote_run(plan_root,output,budget,*,remote=False,resume=False,max_jobs=None,transport=None):
    if not remote:raise O4Error('remote_explicit_flag_required')
    plan_root=Path(plan_root).resolve();plan,data,config=validate_online_plan(plan_root)
    if type(budget)is not int or not 0<=budget<=plan['maximum_api_attempts']:raise O4Error('invalid_api_budget')
    if max_jobs is not None and (type(max_jobs)is not int or max_jobs<1):raise O4Error('invalid_job_limit')
    model=ModelConfig(**read(plan_root/'model.snapshot.json'))
    if plan.get('test_fixture_only') and transport is None:raise O4Error('test_fixture_requires_injected_transport')
    if transport is None:
        import os
        if not os.environ.get(model.api_key_env):raise O4Error('missing_api_key')
        transport=ChatTransport(model)
    elif not transport.test_double:raise O4Error('injected_real_transport_forbidden')
    if transport.config.snapshot()!=model.snapshot():raise O4Error('transport_parameters_changed')
    if resume:
        root=Path(output).resolve()
        if (root/'delivery_manifest.json').exists():raise O4Error('sealed_experiment')
        manifest=read(root/'manifest.json')
        if manifest['plan_delivery_digest']!=digest(read(plan_root/'delivery_manifest.json')) or manifest['test_double']!=transport.test_double:raise O4Error('resume_plan_changed')
        if read(root/'model.snapshot.json')!=model.snapshot():raise O4Error('resume_model_parameters_changed')
    else:
        root=new_output(output,(plan_root,));initialize(root,plan_root,plan,data,config,mode='remote_online')
        manifest=read(root/'manifest.json');manifest['test_double']=transport.test_double;write(root/'manifest.json',manifest)
        shutil.copy2(plan_root/'model.snapshot.json',root/'model.snapshot.json')
        atomic(root/'audit/jobs.json',copy.deepcopy(plan['jobs']))
    phase('running_online_matrix')
    with exclusive(root/'run.lock'):
        jobs=read(root/'audit/jobs.json');tasks={t['task_id']:t for t in data['tasks']}
        strip=lambda rows:[{k:v for k,v in j.items() if k!='status'} for j in rows]
        if strip(jobs)!=strip(plan['jobs']):raise O4Error('job_registry_changed')
        ledger=Ledger(root,budget,{j['job_id']:j['attempt_limit'] for j in jobs if j['backend'].startswith('remote_')},test_double=transport.test_double,resume=resume)
        compiler=RemoteCompiler(root,transport,ledger,recover=resume);processed=0
        for job in jobs:
            if job['status'] in ('PASS','FAIL','PARTIAL'):
                path=root/f"episodes/{job['job_id']}.json"
                if path.exists():verify_episode(read(path),tasks[job['task_id']],config)
                continue
            if max_jobs is not None and processed>=max_jobs:break
            if job['backend'].startswith('remote_') and ledger.report()['remaining_attempts']==0:break
            job['status']='IN_PROGRESS';atomic(root/'audit/jobs.json',jobs)
            task=tasks[job['task_id']];cp=root/f"checkpoints/{job['job_id']}.json"
            checkpoint=read(cp) if resume and cp.exists() else None
            backend=compiler.bound('text' if job['backend']=='remote_text' else 'image') if job['backend'].startswith('remote_') else LocalCompiler(job['backend'],task['reference_policy'] if job['backend']=='oracle_ast' else None)
            try:
                result=episode(task,job['backend'],job['planner'],config,backend,job['job_id'],resume=checkpoint,on_checkpoint=lambda c,phase:atomic(cp,c))
                result.pop('checkpoints');verify_episode(result,task,config)
                write(root/f"episodes/{job['job_id']}.json",result);job['status']=result['summary']['execution_status']
            except Exception as exc:
                atomic(root/'audit/runtime_error.json',{'job_id':job['job_id'],'error':str(exc),'resume_checkpoint':str(cp) if cp.exists() else None})
                # Preserve IN_PROGRESS with its checkpoint and already debited
                # attempts; do not silently consume new calls after a bug.
                atomic(root/'audit/jobs.json',jobs);refresh(root,plan,data,jobs,ledger,complete=False)
                raise
            atomic(root/'audit/jobs.json',jobs);atomic(root/'audit/budget.json',ledger.report());processed+=1
        complete=all(j['status'] in ('PASS','FAIL') for j in jobs)
        report=refresh(root,plan,data,jobs,ledger,complete=complete)
        if complete:
            try:proof=verify_online(root)
            except Exception as exc:
                report.update(status='FAIL',real_online_status='FAIL',verification_error=str(exc));atomic(root/'acceptance_report.json',report);raise
            write(root/'audit/online_recomputation.json',proof);seal(root)
        return report


def refresh(root,plan,data,jobs,ledger,*,complete):
    root=Path(root);summary=aggregate(lightweight_results(root,jobs),jobs);write(root/'metrics/summary.json',summary)
    compilations=[read(p) for p in sorted((root/'responses').glob('*/*.json'))]
    report={'scope':'O4_E5_090_REAL_ONLINE','status':'PASS' if complete else 'PARTIAL',
            'status_scope':'measurement_execution_and_accounting_not_model_accuracy',
            'planned_jobs':len(jobs),'recorded_episodes':summary['recorded_episodes'],'job_statuses':summary['job_statuses'],
            'real_online_status':('PASS' if complete else 'PARTIAL') if not ledger.test_double else 'NOT_RUN',
            'offline_status':'NOT_RUN' if plan.get('test_fixture_only') else 'PASS',
            'real_compile_status':('PASS' if complete and all(c['response'] is not None for c in compilations) else 'PARTIAL') if not ledger.test_double else 'NOT_RUN',
            'new_api_attempts':ledger.report()['real_api_attempts'],'test_double':ledger.test_double,'prior_e1_e2_real_compile_status':'PASS','unseen_generalization':'NOT_MEASURED','visual_increment':'NOT_MEASURED',
            'e3_status':'DEFERRED','e4_status':'OUT_OF_SCOPE','real_api_attempts':ledger.report()['real_api_attempts'],
            'first_valid':sum(c['first_valid'] for c in compilations),'repaired_valid':sum(c['repaired_valid'] for c in compilations),
            'invalid_or_unfinished_compilations':sum(c['response'] is None for c in compilations)}
    accounting_views(root,data,jobs)
    atomic(root/'audit/budget.json',ledger.report());atomic(root/'acceptance_report.json',report);return report


def verify_online(root,sealed=None):
    """Validate actual saved HTTP requests/responses and bound state transitions."""
    root=Path(root);plan=read(root/'plan.json');data=read(root/'private/input_snapshot.json');config=read(root/'config.snapshot.json')
    jobs=read(root/'audit/jobs.json');tasks={t['task_id']:t for t in data['tasks']};checked=0
    model=ModelConfig(**read(root/'model.snapshot.json'));transport=ChatTransport(model)
    strip=lambda rows:[{k:v for k,v in j.items() if k!='status'} for j in rows]
    if strip(jobs)!=strip(plan['jobs']):raise O4Error('job_registry_changed')
    if files(PACKAGE)!=plan['source_files']:raise O4Error('code_snapshot_mismatch')
    ledger=read(root/'audit/ledger.json');attempts=ledger['attempts'];ids=[]
    limits={j['job_id']:j['attempt_limit'] for j in plan['jobs'] if j['backend'].startswith('remote_')}
    if ledger['job_limits']!=limits or len(attempts)>ledger['budget'] or any(a['job_id'] not in limits for a in attempts) or any(sum(a['job_id']==j for a in attempts)>limit for j,limit in limits.items()):raise O4Error('ledger_budget_changed')
    if [a['attempt_id'] for a in attempts]!=list(range(1,len(attempts)+1)):raise O4Error('ledger_identity_changed')
    for p in sorted((root/'responses').glob('*/*.json')):
        c=read(p);source=c['source_request'];attached=c['compiled_request'];envelope=c['envelope']
        if c['compilation_id']!=f'{p.parent.name}_{p.stem}' or c['prompt_digest']!=digest(prompt()):raise O4Error('compilation_identity_changed')
        if c['source_digest']!=digest(source) or envelope['public_request']!=attached or envelope['visual_facts']!=facts(source):raise O4Error('saved_compilation_changed')
        # Verify text-generated source PNG too, as well as image attachment.
        imagepath=f"public/images/{c['compilation_id']}.png";asset={'path':imagepath,'sha256':hashlib.sha256((root/imagepath).read_bytes()).hexdigest()}
        verify_image(source,root,asset)
        if c['backend']=='remote_image' and attached['images']!=[asset]:raise O4Error('saved_image_attachment_changed')
        if c['backend']=='remote_text' and attached['images']:raise O4Error('saved_text_attachment_changed')
        diagnostic=None;matching=[a for a in attempts if a['compilation_id']==c['compilation_id']]
        if c['attempt_ids']!=[a['attempt_id'] for a in matching] or len(matching)>2:raise O4Error('saved_attempt_mapping_changed')
        response=None
        for index,a in enumerate(matching):
            ids.append(a['attempt_id'])
            if a['job_id']!=p.parent.name or (index and matching[0]['status'] not in ('invalid_ast','invalid_binding')):raise O4Error('saved_attempt_transition_changed')
            if a['repair']!=(index==1) or digest(transport.body(envelope,root,prompt(),diagnostic))!=a['body_digest']:raise O4Error('saved_request_body_changed')
            if a['status']=='in_flight':continue
            if a['raw_text'] is not None and json_load(a['raw_text'])!=a['payload']:raise O4Error('saved_http_payload_changed')
            if a['status']=='provider_error' and a['payload'] is None:
                diagnostic=a['repair_diagnostic'];continue
            try:response=parse_response(a['payload'],attached);status='valid';diagnostic=None
            except O4Error as exc:status=exc.code;diagnostic={'code':exc.code,'detail':str(exc),'repair_scope':'format/bindings only; no reference answer'}
            if status!=a['status'] or diagnostic!=a['repair_diagnostic']:raise O4Error('saved_parse_status_changed')
        if c['response']!=response:raise O4Error('saved_response_changed')
    if sorted(ids)!=list(range(1,len(attempts)+1)) or len(attempts)>ledger['budget']:raise O4Error('saved_attempt_denominator_changed')
    for job in jobs:
        p=root/f"episodes/{job['job_id']}.json"
        if not p.exists():
            if job['status'] in ('PASS','FAIL','PARTIAL'):raise O4Error('missing_job_result')
            continue
        r=read(p);verify_episode(r,tasks[job['task_id']],config);checked+=1
        if r['job_id']!=job['job_id'] or r['summary']['execution_status']!=job['status']:raise O4Error('job_result_identity_changed')
        for e in r['events']:
            if 'compilation' in e and job['backend'].startswith('remote_'):
                comp=e['compilation'];saved=read(root/f"responses/{job['job_id']}/D{int(comp['compilation_id'].rsplit('_D',1)[1]):04d}.json")
                if saved!=comp:raise O4Error('episode_saved_compilation_changed')
    if aggregate(lightweight_results(root,jobs),jobs)!=read(root/'metrics/summary.json'):raise O4Error('aggregate_metrics_changed')
    return {'status':'PASS','sealed_files':sealed,'episode_records_recomputed':checked,'http_attempts_verified':len(attempts),'new_api_attempts':0}


def json_load(text):
    import json
    try:
        payload=json.loads(text);canonical(payload);return payload
    except (ValueError,TypeError):return None

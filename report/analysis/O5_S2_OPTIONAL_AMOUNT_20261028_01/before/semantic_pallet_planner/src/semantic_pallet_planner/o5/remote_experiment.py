"""S2 frozen draft plans, offline HTTP fixtures and network-free replay verification."""
import copy
import csv
import html
import json
import shutil
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw
from .common import ROOT, O5Error, atomic, digest, read, sha, new_directory, exclusive
from .config import load
from .data import validate_dataset
from .experiment import source_files, dependencies
from .episode import run_episode, verify_journal, validate_task
from .metrics import summarize
from .public_request import build
from .candidates import generate
from .remote_config import TEMPLATE, validate, gaps, require_cost, money
from .remote_budget import Budget
from .remote_runtime import Runtime
from .remote_transport import ChatHTTPTransport
from .testing import fixture_task

SPECS = ['docs/02_阶段实施方案/O5/O5直接VLM基线与自然语言经验沉淀开发及验收规范_20261027.md',
         'docs/02_阶段实施方案/O5/O5S2真实VLM接入与D0Pilot开发及验收规范_20261028.md']
PLAN_KEYS = {'schema_version','stage','mode','status','gaps','dataset_path','dataset_digest','physical',
             'profile','tasks_digest','jobs','source_files','dependencies','documents','preflight_tasks',
             'maximum_selection_attempts','real_api_attempts','error_policy'}


def validate_run(state,plan):
    keys={'schema_version','identity','plan','mode','jobs'}
    if state.get('mode')=='REAL_D0_PILOT':keys|={'campaign','auth_digest'}
    if (set(state)!=keys or state['schema_version']!='o5_s2_run_v1'
            or state['mode'] not in ('REAL_D0_PILOT','OFFLINE_HTTP_FIXTURE')):
        raise O5Error('REMOTE_RUN_SCHEMA_ERROR')
    if len(state['jobs'])!=len(plan['jobs']):
        raise O5Error('JOB_REGISTRY_CHANGED')
    for job,expected in zip(state['jobs'],plan['jobs']):
        if (set(job)!=set(expected)|{'status','error'} or any(job[k]!=v for k,v in expected.items())
                or job['status'] not in ('NOT_RUN','IN_PROGRESS','COMPLETE','CHECKPOINTED','STOPPED')):
            raise O5Error('JOB_REGISTRY_CHANGED')
    return state


def fixture_profile():
    p=copy.deepcopy(TEMPLATE)
    p.update(provider='OFFLINE_HTTP_FIXTURE',endpoint='https://offline.invalid/v1/chat/completions',
             model='FIXTURE_NOT_A_REAL_MODEL',returned_model='FIXTURE_NOT_A_REAL_MODEL',
             snapshot_note='synthetic contract only',account_id='NO_REAL_ACCOUNT',credential_env='O5_FIXTURE_KEY',
             seed_support='UNSUPPORTED')
    p['token_bound'].update(framing_tokens=128,per_image_tokens=256,evidence='SYNTHETIC_TEST_BOUND_NOT_PROVIDER_FACT')
    p['pricing'].update(currency='TEST_UNITS',input_per_million='1',output_per_million='2',fixed_per_request='0',
                         source='SYNTHETIC_TEST_PRICE_NOT_REAL',verified_at='fixture',
                         coverage='input_includes_images_all_fees_bounded')
    p['limits'].update(preflight_amount='10',pilot_amount='10',total_amount='20')
    return validate(p)


def prepare(dataset, output, profile=None, stage='pilot', fixture=False):
    if stage not in ('preflight','pilot'):
        raise O5Error('INVALID_REMOTE_STAGE')
    cfg=load();p=validate(profile if profile is not None else TEMPLATE)
    data= {'scope':'SYNTHETIC_PROTOCOL_FIXTURE'} if fixture else validate_dataset(dataset)
    tasks=([fixture_task(14),fixture_task(20,220,180,80)] if fixture else
           read(Path(dataset)/'private/development.json')[:8])
    if fixture:
        for i,t in enumerate(tasks):
            t['task_id']+=str(i);t['source_cluster_id']+=str(i)
    elif [t['task_id'] for t in tasks]!=[f'development_{i:03d}' for i in range(1,9)]:
        raise O5Error('PILOT_TASKS_CHANGED')
    jobs=[{'job_id':f'J{i+1:03d}_{m}','task_id':t['task_id'],'method':m,
           'attempt_limit':2*len(t['items']) if m=='D0' else 0,'phase':'pilot'}
          for i,t in enumerate(tasks) for m in ('G0','D0')]
    missing=gaps(p)
    if stage=='pilot' and not fixture:
        missing.append('verified_preflight_result_and_authorization_required')
    dest=new_directory(output)
    (dest/'private').mkdir(mode=0o700)
    atomic(dest/'private/tasks.json',tasks);(dest/'private/tasks.json').chmod(0o400)
    probes=[]
    for name,colors in [('workspace',['red','blue']),('candidates',['green','yellow'])]:
        assets=[]
        for index,(asset,color) in enumerate(zip(('workspace','candidates'),colors)):
            path=dest/'probes'/name/(asset+'.png');path.parent.mkdir(parents=True,exist_ok=True)
            img=Image.new('RGB',(256,256),'white');draw=ImageDraw.Draw(img)
            if index==0:draw.ellipse((48,48,208,208),fill=color)
            else:draw.rectangle((48,48,208,208),fill=color)
            img.save(path)
            assets.append({'asset_id':asset,'path':str(path.relative_to(dest)),'sha256':sha(path),
                           'width':256,'height':256,'expected_fact':color+('_circle' if index==0 else '_square')})
        probes.append({'task_id':'probe_'+name,'attempt_limit':1,'images':assets,
                       'prompt':'First image is workspace; second is candidates. Return only JSON with workspace and candidates: color_shape in each image. No packing action.'})
    # Contract preflight uses a fixed public state, never an entire order result.
    pool,_=generate(tasks[0]['container'],[],tasks[0]['items'][0],0,cfg)
    req,mapping=build(tasks[0]['container'],[],tasks[0]['items'][0],pool,cfg,['S2_PREFLIGHT',0],dest/'contract')
    atomic(dest/'contract/request.json',req)
    atomic(dest/'private/contract_mapping.json',mapping)
    plan={'schema_version':'o5_s2_remote_plan_v1','stage':stage,
          'mode':'OFFLINE_HTTP_FIXTURE' if fixture else 'REMOTE_DRAFT',
          'status':'OFFLINE_FIXTURE_ONLY' if fixture else 'DRAFT_NOT_EXECUTABLE','gaps':missing,
          'dataset_path':'SYNTHETIC_FIXTURE' if fixture else str(Path(dataset).resolve()),
          'dataset_digest':digest(data),'physical':cfg,'profile':p,'tasks_digest':digest(tasks),
          'jobs':jobs,'source_files':source_files(),'dependencies':dependencies(),
          'documents':{s:sha(ROOT/s) for s in SPECS},'preflight_tasks':probes+[
              {'task_id':'probe_contract','attempt_limit':2,'request_digest':digest(req)}],
          'maximum_selection_attempts':sum(j['attempt_limit'] for j in jobs),'real_api_attempts':0,
          'error_policy':{'format_repairs':1,'service_retries':0,'first_429':'HALT',
                          'consecutive_5xx_stop':2,'unknown':'HALT_CAMPAIGN_NO_RESEND'}}
    atomic(dest/'plan.json',plan)
    for name in plan['source_files']:
        if not name.startswith('/'):
            target=dest/'code_snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/name,target)
    for name in SPECS:
        target=dest/'documents'/Path(name).name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/name,target)
    files={str(f.relative_to(dest)):sha(f) for f in dest.rglob('*') if f.is_file()}
    atomic(dest/'seal.json',{'schema_version':'o5_s2_plan_seal_v1','plan_digest':digest(plan),'files':files})
    return {'status':plan['status'],'path':str(dest),'gaps':missing,'planned_jobs':len(jobs),
            'maximum_selection_attempts':plan['maximum_selection_attempts'],'real_api_attempts':0}


def validate_plan(root):
    root=Path(root);plan=read(root/'plan.json');seal=read(root/'seal.json')
    if set(plan)!=PLAN_KEYS or plan['schema_version']!='o5_s2_remote_plan_v1':
        raise O5Error('REMOTE_PLAN_SCHEMA_ERROR')
    validate(plan['profile'])
    if (digest(plan)!=seal['plan_digest'] or plan['source_files']!=source_files()
            or plan['dependencies']!=dependencies() or any(sha(root/n)!=h for n,h in seal['files'].items())
            or any(sha(ROOT/n)!=h for n,h in plan['documents'].items())):
        raise O5Error('PLAN_OR_SOURCE_DRIFT')
    tasks=read(root/'private/tasks.json')
    if digest(tasks)!=plan['tasks_digest']:
        raise O5Error('REMOTE_TASKS_CHANGED')
    if plan['dataset_path']!='SYNTHETIC_FIXTURE':
        if digest(validate_dataset(plan['dataset_path']))!=plan['dataset_digest']:
            raise O5Error('DATASET_CHANGED')
        if tasks!=read(Path(plan['dataset_path'])/'private/development.json')[:8]:
            raise O5Error('PILOT_TASKS_CHANGED')
    expected=[{'job_id':f'J{i+1:03d}_{m}','task_id':t['task_id'],'method':m,
               'attempt_limit':2*len(t['items']) if m=='D0' else 0,'phase':'pilot'}
              for i,t in enumerate(tasks) for m in ('G0','D0')]
    if plan['jobs']!=expected or sum(j['attempt_limit'] for j in expected)!=plan['maximum_selection_attempts']:
        raise O5Error('REMOTE_JOB_MATRIX_CHANGED')
    return plan,tasks


class FixtureWire:
    test_double=True

    def __init__(self,script=None):
        self.script=list(script or []);self.calls=[]

    def post(self,endpoint,body,credential,timeout):
        self.calls.append(copy.deepcopy(body))
        req=json.loads(body['messages'][1]['content'][0]['text'])['public_input']
        answer={'request_id':req['request_id'],'state_hash':req['state_hash'],'action':'PLACE',
                'candidate_id':req['candidates'][0]['candidate_id']}
        entry=self.script.pop(0) if self.script else 'valid'
        if isinstance(entry,BaseException):raise entry
        if callable(entry):entry=entry(req,answer)
        if isinstance(entry,tuple):return entry
        content=json.dumps(answer) if entry=='valid' else entry
        return 200,{'x-request-id':'OFFLINE-HTTP-RECEIPT'},json.dumps({'id':'fixture',
            'model':'FIXTURE_NOT_A_REAL_MODEL','choices':[{'finish_reason':'stop','message':{'content':content}}],
            'usage':{'prompt_tokens':100,'completion_tokens':40}}).encode()


def budget_jobs(plan):
    return {j['job_id']:{'phase':'pilot','attempt_limit':j['attempt_limit']} for j in plan['jobs']}


def execute_fixture(plan_root, output, *, resume=False, stop_after=None, max_jobs=None, wire=None):
    plan_root=Path(plan_root).resolve();plan,tasks=validate_plan(plan_root)
    if plan['mode']!='OFFLINE_HTTP_FIXTURE' or plan['status']!='OFFLINE_FIXTURE_ONLY':
        raise O5Error('FIXTURE_COMMAND_REJECTS_REMOTE_PLAN')
    for v in (stop_after,max_jobs):
        if v is not None and (type(v) is not int or v<1):raise O5Error('INVALID_JOB_LIMIT')
    root=Path(output).resolve() if resume else new_directory(output)
    identity=digest([plan,str(root)])
    wire=wire if wire is not None else FixtureWire()
    if wire.test_double is not True:raise O5Error('OFFLINE_FIXTURE_WIRE_REQUIRED')
    with exclusive(root/'run.lock'):
        if resume:
            state=read(root/'run.json')
            validate_run(state,plan)
            if state['identity']!=identity or state['plan']!=str(plan_root):raise O5Error('RUN_IDENTITY_CHANGED')
        else:
            state={'schema_version':'o5_s2_run_v1','identity':identity,'plan':str(plan_root),'mode':plan['mode'],
                   'jobs':[{**j,'status':'NOT_RUN','error':None} for j in plan['jobs']]}
            atomic(root/'run.json',state)
        if [{k:j[k] for k in plan['jobs'][i]} for i,j in enumerate(state['jobs'])]!=plan['jobs']:
            raise O5Error('JOB_REGISTRY_CHANGED')
        budget=Budget(root/'campaign',plan['profile'],identity,budget_jobs(plan),True,create=not resume)
        if budget.load()['halt']:raise O5Error(budget.state['halt'])
        transport=ChatHTTPTransport(plan['profile'],wire)
        by_id={t['task_id']:t for t in tasks};processed=0
        for job in state['jobs']:
            if job['status']=='COMPLETE':
                verify_job(root,plan,by_id[job['task_id']],job,budget);continue
            if max_jobs is not None and processed>=max_jobs:break
            directory=root/'jobs'/job['job_id'];runtime=Runtime(budget,job['job_id'],plan['profile'],plan['physical'],directory,transport)
            job['status']='IN_PROGRESS';atomic(root/'run.json',state)
            try:
                result=run_episode(by_id[job['task_id']],job['method'],plan['physical'],directory,
                    job['job_id'],identity,attempt_limit=job['attempt_limit'],resume=(directory/'checkpoint.json').exists(),
                    stop_after=stop_after,_runtime=runtime)
                job['status']='CHECKPOINTED' if result.get('execution_status')=='CHECKPOINTED' else 'COMPLETE'
                if budget.load()['halt']:
                    raise O5Error(budget.state['halt'])
            except O5Error as error:
                job['error']=error.code;job['status']='STOPPED';atomic(root/'run.json',state)
                raise
            atomic(root/'run.json',state);processed+=1
        return {'status':'PASS' if all(j['status']=='COMPLETE' for j in state['jobs']) else 'PARTIAL',
                'completed_jobs':sum(j['status']=='COMPLETE' for j in state['jobs']),
                'planned_jobs':len(state['jobs']),'mode':plan['mode'],'new_api_attempts':0,
                'offline_http_attempts':len(budget.load()['attempts']),'accounted_test_units':budget.totals()}


def verify_job(root,plan,task,job,budget,*,allow_prefix=False):
    directory=root/'jobs'/job['job_id']
    result=read(directory/'result.json') if (directory/'result.json').is_file() else None
    cp=read(directory/'checkpoint.json')
    # Construction only checks the saved reference; original files must remain read-only.
    if not (directory/'ledger.json').is_file():raise O5Error('MISSING_LEDGER')
    runtime=Runtime(budget,job['job_id'],plan['profile'],plan['physical'],directory)
    expected_identity=digest([task,job['method'],plan['physical'],job['job_id'],budget.identity,job['attempt_limit']])
    if cp['identity']!=expected_identity:raise O5Error('CHECKPOINT_IDENTITY_CHANGED')
    placed=[];journals=[];terminal=False
    validate_task(task,plan['physical'])
    for i,checksum in enumerate(cp['journal_digests']):
        if terminal or i>=len(task['items']):raise O5Error('EVENT_AFTER_TERMINAL')
        step=directory/f'decisions/{i:03d}';journal=read(step/'journal.json')
        if digest(journal)!=checksum:raise O5Error('CHECKPOINT_JOURNAL_CHANGED')
        placed=verify_journal(journal,task,placed,i,plan['physical'],budget.identity,job['job_id'],step)
        runtime.verify(journal,job['method'],step);journals.append(journal)
        terminal=journal['reason']!='PLACED'
    reason=journals[-1]['reason'] if terminal else ('ALL_ITEMS_PLACED' if len(placed)==len(task['items']) else None)
    if reason=='ALL_ITEMS_PLACED' and len(placed)!=len(task['items']):raise O5Error('PREMATURE_SUCCESS')
    if cp['placed']!=placed or cp['cursor']!=len(placed) or cp['reason']!=reason:
        raise O5Error('CHECKPOINT_STATE_CHANGED')
    if result is None:
        if not allow_prefix:raise O5Error('MISSING_RESULT')
        pending=directory/f'decisions/{len(placed):03d}'
        if reason is None and (pending/'request.json').is_file():
            from .public_request import image_bytes
            pool,_=generate(task['container'],placed,task['items'][len(placed)],len(placed),plan['physical'])
            with tempfile.TemporaryDirectory(prefix='o5-s2-pending-') as tmp:
                req,mapping=build(task['container'],placed,task['items'][len(placed)],pool,plan['physical'],
                                  [budget.identity,job['job_id'],len(placed)],Path(tmp))
            if req!=read(pending/'request.json') or mapping!=read(pending/'mapping.private.json'):
                raise O5Error('PENDING_REQUEST_CHANGED')
            image_bytes(req,pending)
        return {'checkpoint_only':True,'job_id':job['job_id'],'verified_decisions':len(journals)}
    expected={'schema_version':'o5_episode_result_v1','job_id':job['job_id'],'task_id':task['task_id'],
              'source_cluster_id':task['source_cluster_id'],'method':job['method'],'test_double':budget.test_double,
              'summary':summarize(task,placed,reason,journals),
              'decisions':[f'decisions/{i:03d}/journal.json' for i in range(len(journals))],'final_state':placed}
    expected['summary']['result_scope']=runtime.result_scope
    if result!=expected:raise O5Error('RESULT_RECOMPUTATION_MISMATCH')
    referenced=[identity for j in journals for identity in j['attempt_ids']]
    if referenced!=[r['attempt_id'] for r in budget.rows(job['job_id'])]:raise O5Error('UNACCOUNTED_REMOTE_ATTEMPT')
    return result


def verify(root):
    root=Path(root).resolve();state=read(root/'run.json');plan,tasks=validate_plan(state['plan'])
    validate_run(state,plan)
    real=state['mode']=='REAL_D0_PILOT'
    if real:
        from .remote_authorized import campaign_identity,jobs_for,verify_preflight,saved_authorization
        saved_authorization(plan,root,state,'pilot')
        binding=read(Path(state['plan'])/'preflight_binding.json')
        evidence=verify_preflight(binding['preflight'])
        if (plan['mode']!='REMOTE_DRAFT' or plan['status']!='READY_FOR_OPERATOR_AUTHORIZATION'
                or evidence['status']!='PASS' or state['campaign']!=evidence['campaign']
                or state['identity']!=campaign_identity(plan)):
            raise O5Error('PREFLIGHT_BINDING_CHANGED')
    elif state['identity']!=digest([plan,str(root)]) or state['mode']!=plan['mode']:
        raise O5Error('RUN_IDENTITY_CHANGED')
    if len(state['jobs'])!=len(plan['jobs']) or any({k:j.get(k) for k in e}!=e for j,e in zip(state['jobs'],plan['jobs'])):
        raise O5Error('JOB_REGISTRY_CHANGED')
    budget=Budget(state['campaign'] if real else root/'campaign',plan['profile'],state['identity'],
                  jobs_for(plan) if real else budget_jobs(plan),not real)
    by_id={t['task_id']:t for t in tasks};results=[];prefixes=[]
    for j in state['jobs']:
        if j['status']=='COMPLETE':results.append(verify_job(root,plan,by_id[j['task_id']],j,budget))
        elif (root/'jobs'/j['job_id']/'checkpoint.json').is_file():
            checked=verify_job(root,plan,by_id[j['task_id']],j,budget,allow_prefix=True)
            if checked.get('checkpoint_only'):prefixes.append(checked)
            else:results.append(checked)
    known={digest(read(f)) for f in (root/'jobs').glob('*/decisions/*/request.json')}
    if any(r['phase']=='pilot' and r['request_digest'] not in known for r in budget.load()['attempts']):raise O5Error('UNACCOUNTED_REMOTE_ATTEMPT')
    complete=len(results)==len(state['jobs']) and all(j['status']=='COMPLETE' for j in state['jobs']) and not budget.state['halt']
    return {'schema_version':'o5_s2_verification_v1','status':'PASS' if complete else 'PARTIAL',
            'planned_jobs':len(state['jobs']),'verified_jobs':len(results),'results':results,
            'verified_prefixes':prefixes,
            'budget':budget.totals(),'halt':budget.state['halt'],'new_api_attempts':0,
            'mode':state['mode'],'model_performance':'REAL_PILOT_ONLY' if real else 'NOT_MEASURED'}


def report(root,output):
    checked=verify(root);dest=new_directory(output)
    atomic(dest/'verification.json',checked)
    rows=[{'job_id':r['job_id'],'method':r['method'],**r['summary']} for r in checked['results']]
    with (dest/'orders.csv').open('w') as stream:
        if rows:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    label=('Real D0 pilot; descriptive results only.' if checked['mode']=='REAL_D0_PILOT' else
           'HTTP/transport fixture only. Real API calls: 0. No VLM performance measured.')
    (dest/'report.html').write_text('<!doctype html><meta charset="utf-8"><h1>O5 S2 verification</h1>'
        '<p>'+label+'</p><pre>'+
        html.escape(json.dumps({k:v for k,v in checked.items() if k!='results'},ensure_ascii=False,indent=2))+'</pre>'
        +''.join('<h2>'+html.escape(r['job_id'])+'</h2><pre>'+html.escape(json.dumps(r['summary'],indent=2))+'</pre>' for r in checked['results']))
    atomic(dest/'manifest.json',{'schema_version':'o5_s2_report_v1','files':{f.name:sha(f) for f in dest.iterdir()},
                               'new_api_attempts':0,'mode':checked['mode'],'source_run':str(Path(root).resolve())})
    return {'status':checked['status'],'verified_jobs':checked['verified_jobs'],'new_api_attempts':0}
